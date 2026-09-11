import json
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from forget_lah.db import (
    AuditEvent,
    Clinic,
    FollowupCase,
    Job,
    Membership,
    Patient,
    Principal,
    uid,
    utcnow,
)
from forget_lah.detector import detect, trigger_for
from forget_lah.runtime.contracts import parse_decision
from forget_lah.seed import seed
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.worker import claim_job, finish_job
from services.mock_clinic.app import candidates


def test_health_requires_applied_migrations(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_cases_require_authentication(client):
    assert client.get("/api/cases").status_code == 401


def test_login_rejects_cross_origin_and_bad_password(client):
    body = {"email": "staff@forget-lah.example", "password": "incorrect"}
    assert client.post("/api/auth/login", json=body).status_code == 403
    assert (
        client.post(
            "/api/auth/login", headers={"Origin": "https://untrusted.example"}, json=body
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/login", headers={"Origin": "http://localhost:8080"}, json=body
        ).status_code
        == 401
    )


def test_local_login_rate_limit(client):
    for _ in range(10):
        response = client.post(
            "/api/auth/login",
            headers={"Origin": "http://localhost:8080"},
            json={"email": "unknown@forget-lah.example", "password": "incorrect"},
        )
        assert response.status_code == 401
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": "http://localhost:8080"},
            json={"email": "unknown@forget-lah.example", "password": "incorrect"},
        ).status_code
        == 429
    )


def test_logout_requires_csrf_and_revokes_session(signed_client):
    old_session = signed_client.cookies.get("forget_lah_session")
    origin = {"Origin": "http://localhost:8080"}
    assert signed_client.post("/api/auth/logout", headers=origin).status_code == 403
    origin["X-CSRF-Token"] = signed_client.cookies.get("forget_lah_csrf")
    assert signed_client.post("/api/auth/logout", headers=origin).status_code == 204
    signed_client.cookies.set("forget_lah_session", old_session)
    assert signed_client.get("/api/cases").status_code == 401


def test_revoked_membership_is_checked_on_every_request(signed_client, store):
    with store[1].begin() as db:
        db.scalar(select(Membership)).active = False
    assert signed_client.get("/api/cases").status_code == 403


def test_repeat_source_poll_creates_one_case_and_job_per_episode(store):
    factory = store[1]
    rows = candidates_from_payload(candidates())
    assert detect(factory, DEMO_CLINIC_ID, rows) == 3
    assert detect(factory, DEMO_CLINIC_ID, rows) == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(FollowupCase)) == 3
        assert db.scalar(select(func.count()).select_from(Job)) == 3
        assert set(db.scalars(select(FollowupCase.trigger))) == {
            "UPCOMING",
            "MISSED",
            "RECALL_OVERDUE",
        }


def test_old_scheduled_visit_is_not_inferred_to_be_missed():
    row = candidates_from_payload(candidates())[1].model_copy(
        update={"scheduled_at": utcnow() - timedelta(days=1)}
    )
    assert trigger_for(row, utcnow()) is None


def test_recall_with_future_booking_is_suppressed():
    row = candidates_from_payload(candidates())[0].model_copy(update={"has_future_booking": True})
    assert trigger_for(row, utcnow()) is None


@pytest.mark.parametrize("status", ["cancelled", "completed"])
def test_closed_source_records_are_suppressed(status):
    row = candidates_from_payload(candidates())[0].model_copy(update={"source_status": status})
    assert trigger_for(row, utcnow()) is None


def test_worker_reclaims_expired_lease_without_duplicate_event(store):
    factory = store[1]
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates())[:1])
    original = claim_job(factory)
    with factory.begin() as db:
        db.get(Job, original[0]).lease_until = utcnow() - timedelta(seconds=1)
    replacement = claim_job(factory)
    assert original[1] != replacement[1]
    assert not finish_job(factory, *original)
    assert finish_job(factory, *replacement)
    assert not finish_job(factory, *replacement)
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "FOUNDATION_CASE_READY")
            )
            == 1
        )


def test_tenant_filter_applies_to_lists_and_direct_case_access(signed_client, store):
    factory = store[1]
    other_clinic = uid()
    with factory.begin() as db:
        db.add(Clinic(id=other_clinic, name="Other synthetic clinic"))
    row = candidates_from_payload(candidates())[0].model_copy(update={"patient_id": UUID(uid())})
    detect(factory, other_clinic, [row])
    with factory() as db:
        other_case = db.scalar(select(FollowupCase.id))
    assert signed_client.get("/api/cases").json() == []
    assert signed_client.get(f"/api/cases/{other_case}/events").status_code == 404


def test_database_rejects_cross_clinic_patient_reference(store):
    factory = store[1]
    patient_id, other_clinic = uid(), uid()
    with factory.begin() as db:
        db.add(Clinic(id=other_clinic, name="Other synthetic clinic"))
        db.flush()
        db.add(Patient(id=patient_id, clinic_id=other_clinic, display_alias="Other demo patient"))
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(
            FollowupCase(
                clinic_id=DEMO_CLINIC_ID,
                patient_id=patient_id,
                source_episode_ref="bad-link",
                specialty="dental",
                trigger="UPCOMING",
            )
        )


def test_seed_is_idempotent_and_does_not_reset_password(store):
    factory = store[1]
    with factory() as db:
        before = db.scalar(select(Principal.password_hash))
    seed(factory, "staff@forget-lah.example", "another-test-only-password")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Principal)) == 1
        assert db.scalar(select(Principal.password_hash)) == before


def test_live_contract_binds_request_and_case_version():
    request_id = uid()
    proposal = json.dumps(
        {
            "step_type": "DELEGATE",
            "request_id": request_id,
            "reason_code": "FOLLOWUP_REVIEW_REQUIRED",
            "expected_case_version": 1,
            "target": "engagement",
            "goal": "Establish attendance intent",
        }
    )
    assert parse_decision(proposal, request_id, 1)
    with pytest.raises(ValueError):
        parse_decision(proposal, uid(), 1)
    with pytest.raises(ValueError):
        parse_decision(proposal, request_id, 2)


def test_model_cannot_add_permission_claim_or_unknown_reason():
    for payload in [
        {
            "step_type": "ESCALATE",
            "expected_case_version": 1,
            "reason_code": "CLINICAL_REVIEW_REQUIRED",
            "identity_verified": True,
        },
        {"step_type": "ESCALATE", "expected_case_version": 1, "reason_code": "INVENTED_REASON"},
    ]:
        with pytest.raises(ValidationError):
            request_id = uid()
            parse_decision(json.dumps({**payload, "request_id": request_id}), request_id, 1)


def test_model_status_and_outreach_are_honest(signed_client):
    status = signed_client.get("/api/system").json()
    assert status["model_mode"] == "mock"
    assert status["milestone"] == "M2a agent runtime"
    assert status["outreach_enabled"] is False


def test_event_timestamps_include_timezone(signed_client, store):
    detect(store[1], DEMO_CLINIC_ID, candidates_from_payload(candidates())[:1])
    case_id = signed_client.get("/api/cases").json()[0]["id"]
    events = signed_client.get(f"/api/cases/{case_id}/events").json()
    assert events[0]["created_at"].endswith("+00:00")
