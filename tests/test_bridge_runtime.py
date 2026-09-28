import json

import httpx
import pytest
from alembic import command
from alembic.config import Config
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_bridge import FakeBridgeAnalyzer, bridge_client, mutation_headers, upload_csv
from test_doctor_actions_dynamic import SCAN_NOTE, scan_model
from test_postgres import postgres_schema as postgres_schema
from test_runtime import drain, event, headers, view

from forget_lah.api import create_app
from forget_lah.db import BridgeEpisode, BridgeIntakeRecord, FollowupCase, uid
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.models import BridgeConfirmation
from forget_lah.runtime.provider import MockModel, ModelReply, decision_formats_for
from forget_lah.seed import seed
from forget_lah.settings import Settings


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def bridge_runtime(request):
    store = request.getfixturevalue("store" if request.param == "sqlite" else "postgres_schema")
    engine, factory = store
    if request.param == "postgres":
        command.upgrade(Config("alembic.ini"), "head")
        seed(factory, "staff@forget-lah.example", TEST_PASSWORD)
    client = bridge_client(store, FakeBridgeAnalyzer())
    try:
        batch = upload_csv(client).json()
        client.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        ).raise_for_status()
    finally:
        client.__exit__(None, None, None)
    settings = Settings(
        app_env="test",
        agent_model_mode="mock",
        agent_min_interval_seconds=0,
        patient_simulator_enabled=True,
        mock_clinic_followup_key=None,
    )
    with TestClient(create_app(settings, engine), base_url="http://localhost:8080") as client:
        client.post(
            "/api/auth/login",
            headers={"Origin": "http://localhost:8080"},
            json={"email": "staff@forget-lah.example", "password": TEST_PASSWORD},
        ).raise_for_status()
        with factory() as db:
            case = db.scalar(select(FollowupCase).where(FollowupCase.trigger == "UPCOMING"))
            case_id = case.id
        tools = ClinicTools(
            "http://must-not-be-used",
            factory=factory,
            transport=httpx.MockTransport(
                lambda _: pytest.fail("Bridge must not call a clinic API")
            ),
        )
        yield (factory, client, settings), tools, case_id


def begin(runtime, tools, case_id):
    snapshot = view(runtime[1], case_id)
    assert snapshot["patient_simulator"]["available"]
    runtime[1].post(
        f"/api/cases/{case_id}/agent/runs",
        headers=headers(runtime[1]),
        json={"expected_case_version": snapshot["case_version"]},
    ).raise_for_status()
    drain(runtime, tools=tools)


def receipts(factory):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(BridgeConfirmation))


class OmarReplyModel(MockModel):
    """Replay observed reply intents, without a paid model call."""

    def __init__(self, delegate=None):
        self.delegate = delegate or MockModel()

    def decide(self, obs, **kwargs):
        if "REVIEW_NEEDS" in decision_formats_for(obs) and obs["latest_event"]["content"] in {
            "yes",
            "ok",
        }:
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "REVIEW_NEEDS",
                        "reason_code": "PATIENT_NEEDS_REVIEWED",
                        "reply_event_id": obs["latest_event"]["id"],
                        "updates": [],
                        "appointment_intent": "CONFIRM",
                        "appointment_request_quote": obs["latest_event"]["content"],
                    }
                )
            )
        review = obs["simulation"].get("attendance_review")
        if obs["role"] == "engagement" and review and obs["latest_event"]["content"] == "ok":
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "INTERPRET_ATTENDANCE",
                        "reason_code": "PATIENT_ATTENDANCE_REVIEWED",
                        "reply_event_id": review["reply_event_id"],
                        "source_step_id": review["source_step_id"],
                        "confirmed": True,
                        "unsupported_question": "NONE",
                    }
                )
            )
        return self.delegate.decide(obs, **kwargs)


def test_bridge_ok_completes_with_local_idempotent_receipt(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    with runtime[0]() as db:
        original = {r.id: r.normalized for r in db.scalars(select(BridgeIntakeRecord))}
    begin(runtime, tools, case_id)
    event(runtime[1], case_id, "demo_reply", "ok").raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel())
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "completed", result
    assert result["handoff"] is None
    assert result["plan"]["attendance"] == "Confirmation recorded in Forget-lah"
    assert "recorded your confirmation" in result["patient_simulator"]["messages"][-1]["body"]
    assert receipts(runtime[0]) == 1
    with runtime[0]() as db:
        saved = db.scalar(select(BridgeConfirmation))
        receipt, version = saved.receipt, saved.source_version
        case = db.get(FollowupCase, case_id)
        binding = {
            "clinic_id": case.clinic_id,
            "patient_id": case.patient_id,
            "source_episode_ref": case.source_episode_ref,
        }
        assert {r.id: r.normalized for r in db.scalars(select(BridgeIntakeRecord))} == original
    operation = {
        "operation_id": receipt["receipt_id"],
        "run_id": receipt["run_id"],
        "expected_version": receipt["episode_version"],
        "expected_source_version": version,
    }
    assert tools.confirm(binding, operation).data == receipt
    assert tools.confirm(binding, operation).data == receipt
    assert receipts(runtime[0]) == 1
    assert tools.confirm(binding, {**operation, "run_id": uid()}).error_code == "SOURCE_CONFLICT"
    assert (
        tools.confirm({**binding, "clinic_id": uid()}, operation).error_code == "SOURCE_NOT_FOUND"
    )


@pytest.mark.parametrize("answer", ["yes", "no"])
def test_bridge_scan_check_gates_confirmation(bridge_runtime, answer):
    runtime, tools, case_id = bridge_runtime
    with runtime[0].begin() as db:
        case = db.get(FollowupCase, case_id)
        row = db.scalar(
            select(BridgeIntakeRecord).where(
                BridgeIntakeRecord.source_episode_ref == case.source_episode_ref
            )
        )
        row.normalized = {**row.normalized, "doctor_notes": SCAN_NOTE}
        row.raw = {**row.raw, "Free text": SCAN_NOTE}
        episode = db.scalar(
            select(BridgeEpisode).where(BridgeEpisode.source_episode_ref == case.source_episode_ref)
        )
        episode.normalized = dict(row.normalized)
    begin(runtime, tools, case_id)
    event(runtime[1], case_id, "demo_reply", "yes").raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel(scan_model()))
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "waiting", result
    assert result["patient_simulator"]["messages"][-1]["kind"] == "doctor_instruction_check"
    assert receipts(runtime[0]) == 0
    event(runtime[1], case_id, "demo_reply", answer).raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel(scan_model()))
    result = view(runtime[1], case_id)
    if answer == "yes":
        assert result["run"]["status"] == "completed", result
        assert result["handoff"] is None
        assert receipts(runtime[0]) == 1
    else:
        assert receipts(runtime[0]) == 0
        assert result["run"]["status"] == "escalated", result
        assert all(not m["evidence"].get("slots") for m in result["patient_simulator"]["messages"])


def test_bridge_rejects_stale_source_and_unproven_or_invented_operations(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    with runtime[0]() as db:
        case = db.get(FollowupCase, case_id)
        binding = {
            "clinic_id": case.clinic_id,
            "patient_id": case.patient_id,
            "source_episode_ref": case.source_episode_ref,
        }
    context = tools.execute("read_followup_context", binding)
    operation = {
        "operation_id": uid(),
        "run_id": uid(),
        "expected_version": context.data["episode_version"],
        "expected_source_version": context.source_version,
    }
    assert tools.confirm(binding, operation).error_code == "CONFIRMATION_EVIDENCE_REQUIRED"
    assert tools.confirm(binding, {**operation, "slot_id": uid()}).error_code == "SOURCE_INVALID"
    with runtime[0].begin() as db:
        db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == binding["source_episode_ref"]
            )
        ).version += 1
    assert tools.confirm(binding, operation).error_code == "SOURCE_CONFLICT"
    assert receipts(runtime[0]) == 0


@pytest.mark.parametrize("include_intake", [False, True])
def test_demo_reset_managed_bridge_confirmation_scope(bridge_runtime, include_intake):
    from forget_lah.demo_reset import demo_reset_cases, lock_reset_tables, reset_demo
    from forget_lah.detector import detect
    from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
    from services.mock_clinic.fixtures import candidates

    runtime, tools, case_id = bridge_runtime
    begin(runtime, tools, case_id)
    event(runtime[1], case_id, "demo_reply", "ok").raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel())
    add_option(runtime, case_id)
    source = candidates_from_payload(candidates())
    detect(runtime[0], DEMO_CLINIC_ID, source)
    with runtime[0].begin() as db:
        lock_reset_tables(db)
        from forget_lah.db import BridgeFollowupSlot, BridgeIntakeBatch

        target_ids = [case.id for case in demo_reset_cases(db, include_intake=include_intake)]
        assert (case_id in target_ids) == include_intake
        batches = list(db.scalars(select(BridgeIntakeBatch.id)))
        result = reset_demo(
            db, target_ids, source, include_intake=include_intake, expected_intake_batch_ids=batches
        )
        assert len(result["case_ids"]) == 3
    assert receipts(runtime[0]) == (0 if include_intake else 1)
    if include_intake:
        assert runtime[1].get(f"/api/cases/{case_id}/agent").status_code == 404
        with runtime[0]() as db:
            for model in (BridgeEpisode, BridgeFollowupSlot, BridgeIntakeRecord, BridgeIntakeBatch):
                assert db.scalar(select(func.count()).select_from(model)) == 0
    else:
        assert view(runtime[1], case_id)["run"]["status"] == "completed"


def add_option(runtime, case_id):
    from datetime import UTC, datetime, timedelta

    at = (datetime.now(UTC) + timedelta(days=3)).replace(hour=8, minute=0, second=0, microsecond=0)
    current = view(runtime[1], case_id)["bridge"]
    response = runtime[1].post(
        f"/api/bridge/cases/{case_id}/options",
        headers=headers(runtime[1]),
        json={
            "expected_version": current["version"],
            "starts_at": at.isoformat(),
            "ends_at": (at + timedelta(minutes=30)).isoformat(),
            "doctor": "Clinic team",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["options"][0]


@pytest.mark.parametrize("after_offer", [False, True])
def test_expired_scheduled_bridge_requires_staff_before_offering_or_booking(
    bridge_runtime, monkeypatch, after_offer
):
    from datetime import datetime, timedelta

    from test_adaptation import BarrierModel

    from forget_lah.runtime.failures import escalate_failure

    runtime, tools, case_id = bridge_runtime
    add_option(runtime, case_id)
    begin(runtime, tools, case_id)
    if after_offer:
        event(
            runtime[1], case_id, "demo_reply", "My daughter can accompany me after 3 pm"
        ).raise_for_status()
        drain(runtime, tools=tools, model=BarrierModel())
        assert view(runtime[1], case_id)["patient_simulator"]["messages"][-1]["kind"] == "options"
    before = view(runtime[1], case_id)
    expired_now = datetime.fromisoformat(before["bridge"]["appointment_at"]) + timedelta(minutes=1)
    monkeypatch.setattr("forget_lah.runtime.simulation.utcnow", lambda: expired_now)
    event(
        runtime[1],
        case_id,
        "demo_reply",
        "option 1 is fine" if after_offer else "My daughter can accompany me after 3 pm",
    ).raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "escalated", result
    assert result["handoff"]["reason_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["bridge"]["appointment_at"] == before["bridge"]["appointment_at"]
    assert receipts(runtime[0]) == 0
    assert sum(m["kind"] == "options" for m in result["patient_simulator"]["messages"]) == int(
        after_offer
    )
    assert result["steps"][-1]["origin"] == "rule"
    escalate_failure(runtime[0], runtime[2], result["run"]["id"])
    assert (
        "original appointment time has passed"
        in view(runtime[1], case_id)["patient_simulator"]["messages"][-1]["body"]
    )


@pytest.mark.parametrize("reschedule", [True, False])
def test_bridge_books_and_reschedules_in_owned_tables(bridge_runtime, reschedule):
    from test_adaptation import BarrierModel

    from forget_lah.db import BridgeFollowupSlot

    runtime, tools, case_id = bridge_runtime
    if not reschedule:
        with runtime[0]() as db:
            case_id = db.scalar(select(FollowupCase).where(FollowupCase.trigger == "MISSED")).id
    slot = add_option(runtime, case_id)
    with runtime[0]() as db:
        original = {r.id: r.normalized for r in db.scalars(select(BridgeIntakeRecord))}
    begin(runtime, tools, case_id)
    event(
        runtime[1], case_id, "demo_reply", "My daughter can accompany me after 3 pm"
    ).raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "waiting", result
    assert result["handoff"] is None
    offer = result["patient_simulator"]["messages"][-1]
    assert [s["id"] for s in offer["evidence"]["slots"]] == [slot["id"]], offer
    event(runtime[1], case_id, "demo_reply", "option 1 is fine").raise_for_status()
    drain(runtime, tools=tools)
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "completed", result
    assert result["handoff"] is None
    assert result["bridge"]["appointment_at"] == slot["starts_at"]
    assert result["bridge"]["followup_status"] == "completed"
    assert "Forget-lah" in result["patient_simulator"]["messages"][-1]["body"]
    with runtime[0]() as db:
        assert db.get(BridgeFollowupSlot, slot["id"]).status == "booked"
        saved = db.scalar(select(BridgeConfirmation))
        receipt = saved.receipt
        assert receipt["action"] == ("RESCHEDULE" if reschedule else "BOOK_FOLLOWUP")
        assert {r.id: r.normalized for r in db.scalars(select(BridgeIntakeRecord))} == original
        case = db.get(FollowupCase, case_id)
        binding = {
            "clinic_id": case.clinic_id,
            "patient_id": case.patient_id,
            "source_episode_ref": case.source_episode_ref,
        }
    assert tools.confirm(binding, receipt["request"]).data == receipt
    assert (
        tools.confirm(binding, {**receipt["request"], "slot_id": uid()}).error_code
        == "SOURCE_CONFLICT"
    )
    assert receipts(runtime[0]) == 1
    # Re-importing the original spreadsheet must not undo a managed appointment change.
    from forget_lah.bridge import BridgeRecordAnalysis

    class OriginalImport(FakeBridgeAnalyzer):
        def analyse(self, *args, **kwargs):
            analysis = super().analyse(*args, **kwargs)
            analysis.records = [
                BridgeRecordAnalysis.model_validate(row) for row in original.values()
            ]
            return analysis

    with runtime[0]() as db:
        episode_count = db.scalar(select(func.count()).select_from(BridgeEpisode))
    client = bridge_client((runtime[0].kw["bind"], runtime[0]), OriginalImport())
    try:
        batch = upload_csv(client).json()
        client.post(
            f"/api/bridge/batches/{batch['id']}/approve",
            headers=mutation_headers(client),
            json={"include_review_rows": False},
        ).raise_for_status()
    finally:
        client.__exit__(None, None, None)
    assert view(runtime[1], case_id)["bridge"]["appointment_at"] == slot["starts_at"]
    with runtime[0]() as db:
        assert db.scalar(select(func.count()).select_from(BridgeEpisode)) == episode_count


def test_bridge_option_scope_and_stale_selection(bridge_runtime):
    from test_adaptation import BarrierModel

    runtime, tools, case_id = bridge_runtime
    slot = add_option(runtime, case_id)
    begin(runtime, tools, case_id)
    event(
        runtime[1], case_id, "demo_reply", "My daughter can accompany me after 3 pm"
    ).raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    current = view(runtime[1], case_id)["bridge"]
    endpoint = f"/api/bridge/cases/{case_id}/options/{slot['id']}/withdraw"
    assert (
        runtime[1].post(endpoint, json={"expected_version": current["version"]}).status_code == 403
    )
    assert (
        runtime[1]
        .post(
            endpoint, headers=headers(runtime[1]), json={"expected_version": current["version"] - 1}
        )
        .status_code
        == 409
    )
    runtime[1].post(
        endpoint, headers=headers(runtime[1]), json={"expected_version": current["version"]}
    ).raise_for_status()
    event(runtime[1], case_id, "demo_reply", "option 1 is fine").raise_for_status()
    drain(runtime, tools=tools)
    assert receipts(runtime[0]) == 0
    assert view(runtime[1], case_id)["bridge"]["appointment_at"] != slot["starts_at"]
    with runtime[0]() as db:
        case = db.get(FollowupCase, case_id)
        binding = {
            "clinic_id": uid(),
            "patient_id": case.patient_id,
            "source_episode_ref": case.source_episode_ref,
        }
    assert tools.execute("read_followup_context", binding).error_code == "SOURCE_NOT_FOUND"


@pytest.mark.postgres
def test_bridge_migration_backfills_approved_state_without_touching_history(postgres_schema):
    from datetime import timedelta

    from forget_lah.bridge import _candidate
    from forget_lah.db import BridgeEpisode, BridgeIntakeBatch, BridgeIntakeRecord

    engine, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "0012")
    from test_postgres import seed_legacy_membership

    seed_legacy_membership(factory)
    from forget_lah.db import Principal, utcnow

    with factory.begin() as db:
        staff = db.scalar(select(Principal))
        batch = BridgeIntakeBatch(
            clinic_id="00000000-0000-4000-8000-000000000001",
            uploaded_by=staff.id,
            filename="approved.csv",
            file_type="csv",
            sha256="a" * 64,
            status="APPROVED",
        )
        # Use the seeded clinic identity rather than any external/mock table.
        from forget_lah.source import DEMO_CLINIC_ID

        batch.clinic_id = DEMO_CLINIC_ID
        db.add(batch)
        db.flush()
        row = BridgeIntakeRecord(
            clinic_id=batch.clinic_id,
            batch_id=batch.id,
            row_number=2,
            status="IMPORTED",
            patient_id=uid(),
            source_episode_ref="bridge:" + "a" * 40,
            raw={"Patient": "Imported patient"},
            normalized={
                "patient_name": "Imported patient",
                "record_type": "appointment",
                "source_status": "scheduled",
                "specialty": "general",
                "appointment_at": (utcnow() + timedelta(days=1)).isoformat(),
            },
        )
        db.add(row)
        db.flush()
        row_id, original = row.id, dict(row.normalized)
        candidate = _candidate(row)
    from forget_lah.detector import detect

    detect(factory, DEMO_CLINIC_ID, [candidate])
    with factory.begin() as db:
        from forget_lah.runtime.models import AgentRun

        case = db.scalar(select(FollowupCase))
        run = AgentRun(
            clinic_id=case.clinic_id,
            case_id=case.id,
            start_key=uid(),
            start_case_version=1,
            started_by=staff.id,
            authorised_by=staff.id,
            mode="mock",
            status="escalated",
            goal="Follow up",
        )
        db.add(run)
        db.flush()
        run_id = run.id
    command.upgrade(Config("alembic.ini"), "head")
    with factory() as db:
        episode = db.scalar(select(BridgeEpisode))
        assert episode.record_id == row_id and episode.normalized == original
        assert episode.followup_status == "needs_staff"
        assert db.get(BridgeIntakeRecord, row_id).normalized == original
        assert db.get(AgentRun, run_id).status == "escalated"
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from forget_lah.db import Base

    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_bridge_concurrent_confirmation_retry_is_idempotent(bridge_runtime):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    runtime, tools, case_id = bridge_runtime
    if runtime[0].kw["bind"].dialect.name != "postgresql":
        pytest.skip("Row-lock concurrency requires PostgreSQL")
    begin(runtime, tools, case_id)
    event(runtime[1], case_id, "demo_reply", "ok").raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel())
    with runtime[0]() as db:
        saved = db.scalar(select(BridgeConfirmation))
        receipt = saved.receipt
        case = db.get(FollowupCase, case_id)
        binding = {
            "clinic_id": case.clinic_id,
            "patient_id": case.patient_id,
            "source_episode_ref": case.source_episode_ref,
        }
    gate = Barrier(2)

    def retry():
        gate.wait(timeout=5)
        return tools.confirm(binding, receipt["request"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retry(), range(2)))
    assert all(result.status == "succeeded" and result.data == receipt for result in results)
    assert receipts(runtime[0]) == 1


def test_bridge_slots_preserve_singapore_time_after_reload(bridge_runtime):
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    runtime, _, case_id = bridge_runtime
    at = (datetime.now(ZoneInfo("Asia/Singapore")) + timedelta(days=4)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    state = view(runtime[1], case_id)["bridge"]
    payload = {
        "expected_version": state["version"],
        "starts_at": at.isoformat(),
        "ends_at": (at + timedelta(minutes=30)).isoformat(),
        "doctor": "Test clinic team",
    }
    response = runtime[1].post(
        f"/api/bridge/cases/{case_id}/options", headers=headers(runtime[1]), json=payload
    )
    assert response.status_code == 201, response.text
    reloaded = view(runtime[1], case_id)["bridge"]
    option = reloaded["options"][0]
    assert datetime.fromisoformat(option["starts_at"]) == at.astimezone(UTC)
    assert datetime.fromisoformat(option["ends_at"]) == (at + timedelta(minutes=30)).astimezone(UTC)
    payload["expected_version"] = reloaded["version"]
    assert (
        runtime[1]
        .post(f"/api/bridge/cases/{case_id}/options", headers=headers(runtime[1]), json=payload)
        .status_code
        == 409
    )
