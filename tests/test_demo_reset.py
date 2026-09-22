from uuid import UUID

import httpx
import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from forget_lah.api import create_app
from forget_lah.db import AuditEvent, Clinic, FollowupCase, Membership, Patient, Principal, uid
from forget_lah.detector import detect
from forget_lah.runtime.engine import claim_run, prepare_step, store_proposal
from forget_lah.runtime.models import AgentRun, AgentStep, ModelBudget
from forget_lah.runtime.provider import MockModel
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates


@pytest.fixture(params=["test", "demo"])
def reset_app(store, monkeypatch, request):
    engine, factory = store
    settings = Settings(database_url="sqlite://", app_env=request.param, demo_reset_enabled=True)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    monkeypatch.setattr(
        "forget_lah.demo_reset.read_candidates", lambda _: candidates_from_payload(candidates())
    )
    with TestClient(create_app(settings, engine), base_url="http://localhost:8080") as client:
        assert (
            client.post(
                "/api/auth/login",
                headers={"Origin": settings.public_origin},
                json={"email": "staff@forget-lah.example", "password": TEST_PASSWORD},
            ).status_code
            == 200
        )
        yield client, factory, settings


def mutation(client):
    return {
        "Origin": "http://localhost:8080",
        "X-CSRF-Token": client.cookies.get("forget_lah_csrf"),
        "Idempotency-Key": uid(),
    }


def body(client):
    return {
        "confirmation": "RESET",
        "expected_case_ids": client.get("/api/system").json()["demo_reset_case_ids"],
    }


def test_reset_recreates_source_snapshots_preserves_identity_budget_and_other_clinic(reset_app):
    client, factory, _ = reset_app
    expected = body(client)
    other_id = uid()
    with factory.begin() as db:
        db.add(Clinic(id=other_id, name="Other clinic"))
        db.get(ModelBudget, "organiser").calls = 17
        user = db.scalar(select(Principal))
        credentials = (user.id, user.password_hash)
    # A separate clinic is not part of the reset.
    row = candidates_from_payload(candidates())[0].model_copy(update={"patient_id": UUID(uid())})
    detect(factory, other_id, [row])
    with factory() as db:
        other_case = db.scalar(select(FollowupCase.id).where(FollowupCase.clinic_id == other_id))
    response = client.post("/api/demo/reset", headers=mutation(client), json=expected)
    assert response.status_code == 200, response.text
    new_ids = response.json()["case_ids"]
    assert len(new_ids) == 3 and not set(new_ids).intersection(expected["expected_case_ids"])
    with factory() as db:
        assert db.get(FollowupCase, other_case)
        assert db.get(ModelBudget, "organiser").calls == 17
        user = db.scalar(select(Principal))
        assert credentials == (user.id, user.password_hash)
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0
        for case_id in new_ids:
            audit = db.scalar(select(AuditEvent).where(AuditEvent.case_id == case_id))
            assert audit.event_type == "CASE_IDENTIFIED"
            assert "source_candidate" in audit.details
    assert client.get("/api/me").status_code == 200
    # Retrying an old request cannot erase the freshly recreated cases.
    assert (
        client.post("/api/demo/reset", headers=mutation(client), json=expected).status_code == 409
    )
    assert set(body(client)["expected_case_ids"]) == set(new_ids)


@pytest.mark.parametrize(
    "restriction", ["flag", "csrf", "origin", "signed_out", "membership", "confirmation"]
)
def test_reset_authorisation_and_confirmation(reset_app, restriction):
    client, factory, settings = reset_app
    expected, headers = body(client), mutation(client)
    if restriction == "flag":
        settings.demo_reset_enabled = False
        assert not client.get("/api/system").json()["demo_reset_enabled"]
    elif restriction == "csrf":
        headers["X-CSRF-Token"] = "invalid"
    elif restriction == "origin":
        headers["Origin"] = "https://other.example"
    elif restriction == "signed_out":
        client.cookies.clear()
    elif restriction == "membership":
        with factory.begin() as db:
            db.scalar(select(Membership)).active = False
    else:
        expected["confirmation"] = "not confirmed"
    response = client.post("/api/demo/reset", headers=headers, json=expected)
    assert response.status_code == (
        401 if restriction == "signed_out" else 422 if restriction == "confirmation" else 403
    )
    with factory() as db:
        assert set(db.scalars(select(FollowupCase.id))) == set(expected["expected_case_ids"])


@pytest.mark.parametrize("invalid", [False, True])
def test_reset_source_failure_leaves_old_history_intact(reset_app, monkeypatch, invalid):
    client, factory, _ = reset_app
    expected = body(client)

    def source(_):
        if invalid:
            return candidates_from_payload(candidates())[:1]
        raise httpx.ConnectError("source unavailable")

    monkeypatch.setattr("forget_lah.demo_reset.read_candidates", source)
    assert (
        client.post("/api/demo/reset", headers=mutation(client), json=expected).status_code == 503
    )
    with factory() as db:
        assert set(db.scalars(select(FollowupCase.id))) == set(expected["expected_case_ids"])
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 3


def test_reset_reseed_failure_rolls_back_deletion(reset_app, monkeypatch):
    client, factory, _ = reset_app
    expected = body(client)

    def fail(*_):
        raise RuntimeError("injected seed failure")

    monkeypatch.setattr("forget_lah.demo_reset.save_candidate", fail)
    with pytest.raises(RuntimeError, match="injected seed failure"):
        client.post("/api/demo/reset", headers=mutation(client), json=expected)
    with factory() as db:
        assert set(db.scalars(select(FollowupCase.id))) == set(expected["expected_case_ids"])
        assert db.scalar(select(func.count()).select_from(Patient)) == 3


def test_reset_rejects_unexpected_records(reset_app):
    client, factory, _ = reset_app
    expected = body(client)
    with factory.begin() as db:
        db.scalar(select(Patient)).display_alias = "Unexpected patient"
    assert (
        client.post("/api/demo/reset", headers=mutation(client), json=expected).status_code == 409
    )
    assert set(body(client)["expected_case_ids"]) == set(expected["expected_case_ids"])


def test_reset_requires_pause_and_discards_late_worker_result(reset_app):
    client, factory, settings = reset_app
    case = client.get("/api/cases").json()[0]
    response = client.post(
        f"/api/cases/{case['id']}/agent/runs",
        headers=mutation(client),
        json={"expected_case_version": case["case_version"]},
    )
    assert response.status_code == 202
    expected = body(client)
    assert (
        client.post("/api/demo/reset", headers=mutation(client), json=expected).status_code == 409
    )
    run_id, token = claim_run(factory)
    work = prepare_step(factory, settings, run_id, token)
    reply = MockModel().decide(work["observation"])
    assert (
        client.post("/api/demo/reset", headers=mutation(client), json=expected).status_code == 409
    )
    snapshot = client.get(f"/api/cases/{case['id']}/agent").json()
    assert (
        client.post(
            f"/api/cases/{case['id']}/agent/events",
            headers=mutation(client),
            json={
                "run_id": run_id,
                "expected_case_version": snapshot["case_version"],
                "kind": "pause",
            },
        ).status_code
        == 202
    )
    assert (
        client.post("/api/demo/reset", headers=mutation(client), json=expected).status_code == 200
    )
    assert not store_proposal(factory, settings, run_id, token, work["step_id"], reply)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert db.scalar(select(func.count()).select_from(AgentStep)) == 0


def test_reset_defaults_off():
    assert Settings(database_url="sqlite://", _env_file=None).demo_reset_enabled is False


def test_reset_preserves_bridge_history_and_channel_state(reset_app, store):
    from test_bridge import FakeBridgeAnalyzer, bridge_client, mutation_headers, upload_csv

    from forget_lah.channel_models import (
        ChannelBinding,
        ChannelInbox,
        ChannelOutbox,
        ChannelRoutingState,
    )
    from forget_lah.db import BridgeIntakeRecord
    from forget_lah.runtime.models import PatientPreference

    client, factory, _ = reset_app
    bridge = bridge_client(store, FakeBridgeAnalyzer())
    try:
        batch = upload_csv(bridge).json()
        response = bridge.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(bridge),
            json={"include_review_rows": False},
        )
        assert response.status_code == 200
    finally:
        bridge.__exit__(None, None, None)
    with factory.begin() as db:
        imported = list(
            db.scalars(
                select(FollowupCase).where(FollowupCase.source_episode_ref.startswith("bridge:"))
            )
        )
        case = imported[0]
        case_id, patient_id = case.id, case.patient_id
        imported_ids = {c.id for c in imported}
        user = db.scalar(select(Principal))
        run = AgentRun(
            clinic_id=case.clinic_id,
            case_id=case.id,
            start_key=uid(),
            start_case_version=case.case_version,
            started_by=user.id,
            authorised_by=user.id,
            mode="mock",
            status="running",
            goal="Preserved Bridge review",
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.add(
            PatientPreference(
                clinic_id=case.clinic_id, patient_id=patient_id, preferences={"latest_minute": 900}
            )
        )
        db.add(
            ChannelBinding(
                id="bridge-phone",
                clinic_id=case.clinic_id,
                case_id=case.id,
                recipient="whatsapp:+6590000001",
                enabled=True,
            )
        )
        db.add(
            ChannelInbox(
                sid="bridge-incoming",
                clinic_id=case.clinic_id,
                case_id=case.id,
                body="Preserved reply",
                status="queued",
            )
        )
        db.add(
            ChannelOutbox(
                id="bridge-outgoing",
                message_id="bridge-message",
                clinic_id=case.clinic_id,
                case_id=case.id,
                recipient="whatsapp:+6590000001",
                body="Preserved message",
                status="sending",
            )
        )
        db.add(
            ChannelRoutingState(
                id="bridge-phone", clinic_id=case.clinic_id, data={"active_case_id": case.id}
            )
        )
    expected = body(client)
    assert len(expected["expected_case_ids"]) == 3
    assert not imported_ids.intersection(expected["expected_case_ids"])
    response = client.post("/api/demo/reset", headers=mutation(client), json=expected)
    assert response.status_code == 200, response.text
    with factory() as db:
        assert imported_ids.issubset(set(db.scalars(select(FollowupCase.id))))
        assert db.get(Patient, patient_id)
        assert db.get(AgentRun, run_id).status == "running"
        assert db.get(PatientPreference, (DEMO_CLINIC_ID, patient_id)).preferences == {
            "latest_minute": 900
        }
        assert db.get(ChannelBinding, "bridge-phone").enabled
        assert db.get(ChannelBinding, "bridge-phone").case_id == case_id
        assert db.get(ChannelInbox, "bridge-incoming").body == "Preserved reply"
        assert db.get(ChannelInbox, "bridge-incoming").status == "queued"
        assert db.get(ChannelOutbox, "bridge-outgoing").body == "Preserved message"
        assert db.get(ChannelOutbox, "bridge-outgoing").status == "sending"
        assert db.get(ChannelRoutingState, "bridge-phone").data == {"active_case_id": case_id}
        assert db.scalar(select(func.count()).select_from(BridgeIntakeRecord)) == 2
        assert db.scalar(select(AuditEvent).where(AuditEvent.case_id == case_id))
    assert client.get(f"/api/cases/{case_id}/agent").json()["source_kind"] == "bridge_upload"


def test_reset_rejects_bridge_prefix_without_import_provenance(reset_app):
    client, factory, _ = reset_app
    with factory.begin() as db:
        db.scalar(select(FollowupCase)).source_episode_ref = "bridge:unverified"
    expected = body(client)
    response = client.post("/api/demo/reset", headers=mutation(client), json=expected)
    assert response.status_code == 409
    with factory() as db:
        assert set(db.scalars(select(FollowupCase.id))) == set(expected["expected_case_ids"])


@pytest.mark.parametrize("stale_batch", [False, True])
def test_reset_can_clear_intelligent_intake_and_draft_uploads(reset_app, store, stale_batch):
    from test_bridge import FakeBridgeAnalyzer, bridge_client, mutation_headers, upload_csv

    from forget_lah.db import (
        BridgeEpisode,
        BridgeImportProfile,
        BridgeIntakeBatch,
        BridgeIntakeRecord,
    )

    client, factory, _ = reset_app
    intake = bridge_client(store, FakeBridgeAnalyzer())
    try:
        batch = upload_csv(intake).json()
        intake.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(intake),
            json={"include_review_rows": False},
        ).raise_for_status()
        upload_csv(intake).raise_for_status()  # Unapproved previews must also be cleared.
    finally:
        intake.__exit__(None, None, None)
    state = client.get("/api/system").json()
    expected = {
        "confirmation": "RESET",
        "include_intake": True,
        "expected_case_ids": state["demo_reset_case_ids"] + state["demo_reset_intake_case_ids"],
        "expected_intake_batch_ids": [] if stale_batch else state["demo_reset_intake_batch_ids"],
    }
    assert len(state["demo_reset_intake_batch_ids"]) == 2
    assert len(state["demo_reset_intake_case_ids"]) == 2
    response = client.post("/api/demo/reset", headers=mutation(client), json=expected)
    assert response.status_code == (409 if stale_batch else 200), response.text
    with factory() as db:
        for model in (BridgeEpisode, BridgeIntakeRecord, BridgeImportProfile, BridgeIntakeBatch):
            count = db.scalar(select(func.count()).select_from(model))
            assert count > 0 if stale_batch else count == 0
        assert db.scalar(select(func.count()).select_from(Patient)) == (5 if stale_batch else 3)
    assert client.get("/api/me").status_code == 200
