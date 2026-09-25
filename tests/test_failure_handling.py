import json

import pytest
from sqlalchemy import select
from test_runtime import drain, event, start, view
from test_runtime import runtime as runtime_fixture

from forget_lah.runtime.engine import claim_run, process_run
from forget_lah.runtime.failures import escalate_failure, recover_paused_failures
from forget_lah.runtime.models import AgentRun, SimulatedMessage, StaffHandoff
from forget_lah.runtime.provider import MockModel, ModelReply


@pytest.fixture
def runtime(store, signed_client):
    return runtime_fixture.__wrapped__(store, signed_client)


def paused_reply(runtime, code="POLICY_DENIED"):
    factory, client, settings = runtime
    case_id, run_id = start(runtime)
    drain(runtime)
    assert (
        event(client, case_id, "demo_reply", "Please help change my appointment").status_code == 202
    )
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        run.status = "paused"
        run.lease_token = run.lease_until = None
        run.checkpoint = {**run.checkpoint, "pause_reason": code}
    return case_id, run_id, settings.model_copy(update={"patient_simulator_enabled": True})


@pytest.mark.parametrize(
    "code",
    [
        "POLICY_DENIED",
        "MODEL_ACCESS_DENIED",
        "SOURCE_ATTEMPTS_EXHAUSTED",
        "MODEL_SCHEMA_INVALID",
        "UNEXPECTED_WORKFLOW_ERROR",
    ],
)
def test_failures_create_one_handoff_and_static_notice(runtime, monkeypatch, code):
    factory, _, _ = runtime
    _, run_id, settings = paused_reply(runtime, code)
    monkeypatch.setattr(
        "forget_lah.runtime.failures.effective_memory", lambda *a: {"preferred_language": "ms"}
    )
    assert escalate_failure(factory, settings, run_id)
    assert not escalate_failure(factory, settings, run_id)
    with factory() as db:
        run = db.get(AgentRun, run_id)
        assert run.status == "escalated" and run.checkpoint["pause_reason"] == code
        assert len(list(db.scalars(select(StaffHandoff).where(StaffHandoff.run_id == run_id)))) == 1
        messages = list(
            db.scalars(
                select(SimulatedMessage).where(
                    SimulatedMessage.run_id == run_id,
                    SimulatedMessage.kind == "failure_acknowledgement",
                )
            )
        )
        assert len(messages) == 1
        assert messages[0].translation["provider"] == "static"
        assert messages[0].translation["language"] == "ms"
        assert code not in messages[0].body
        assert "appointment has been changed" not in messages[0].body


def test_sweeper_recovers_persisted_failure_but_not_manual_pause(runtime):
    factory, _, _ = runtime
    _, run_id, settings = paused_reply(runtime, "STAFF_PAUSED")
    assert recover_paused_failures(factory, settings) == 0
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        run.checkpoint = {**run.checkpoint, "pause_reason": "POLICY_DENIED"}
    assert recover_paused_failures(factory, settings) == 1
    assert recover_paused_failures(factory, settings) == 0


def test_contact_stop_creates_staff_task_without_message(runtime, monkeypatch):
    factory, _, _ = runtime
    _, run_id, settings = paused_reply(runtime)
    monkeypatch.setattr(
        "forget_lah.runtime.failures.effective_memory", lambda *a: {"contact_permission": "stopped"}
    )
    assert escalate_failure(factory, settings, run_id)
    with factory() as db:
        assert not db.scalar(
            select(SimulatedMessage.id).where(
                SimulatedMessage.run_id == run_id,
                SimulatedMessage.kind == "failure_acknowledgement",
            )
        )
        assert db.scalar(select(StaffHandoff.id).where(StaffHandoff.run_id == run_id))


def test_unexpected_exception_is_recovered_without_leaking_text(runtime, monkeypatch):
    factory, _, _ = runtime
    _, run_id, settings = paused_reply(runtime)
    from forget_lah.db import utcnow

    with factory.begin() as db:
        r = db.get(AgentRun, run_id)
        r.status = "queued"
        r.available_at = utcnow()
    claimed = claim_run(factory)

    def fail(*a, **kw):
        raise RuntimeError("PRIVATE FAILURE DETAILS")

    monkeypatch.setattr("forget_lah.runtime.engine._process_run", fail)
    process_run(factory, settings, *claimed)
    with factory() as db:
        r = db.get(AgentRun, run_id)
        assert r.status == "escalated"
        assert "PRIVATE FAILURE" not in json.dumps(r.checkpoint)


@pytest.mark.parametrize("stale_version", [False, True])
def test_delegation_reason_is_corrected_then_full_policy_checked(runtime, stale_version):
    class WrongReason(MockModel):
        def decide(self, observation, **kwargs):
            reply = super().decide(observation, **kwargs)
            decision = json.loads(reply.text)
            if decision["step_type"] == "DELEGATE":
                decision["reason_code"] = (
                    "PREPARATION_REVIEW_REQUIRED"
                    if decision["target"] == "engagement"
                    else "FOLLOWUP_REVIEW_REQUIRED"
                )
            if stale_version and decision["step_type"] == "DELEGATE":
                decision["expected_case_version"] += 1
            return ModelReply(json.dumps(decision))

    case_id, _ = start(runtime)
    drain(runtime, model=WrongReason())
    result = view(runtime[1], case_id)
    if stale_version:
        assert result["run"]["status"] == "escalated"
        assert result["run"]["pause_reason"] == "MODEL_SCHEMA_INVALID"
        assert not any(
            s["decision"] and s["decision"]["step_type"] == "DELEGATE" for s in result["steps"]
        )
        return
    step = next(
        s for s in result["steps"] if s["decision"] and s["decision"]["step_type"] == "DELEGATE"
    )
    assert step["policy"]["decision"] == "ALLOW"
    assert step["decision"]["reason_code"] == "FOLLOWUP_REVIEW_REQUIRED"


@pytest.mark.parametrize("invalid", ["revoked", "wrong_clinic", "stale_lease"])
def test_recovery_cannot_bypass_authority_or_lease(runtime, invalid):
    from forget_lah.db import Clinic, Membership, Principal, uid

    factory, _, _ = runtime
    _, run_id, settings = paused_reply(runtime)
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        if invalid == "revoked":
            membership = db.scalar(
                select(Membership).where(
                    Membership.principal_id == run.authorised_by,
                    Membership.clinic_id == run.clinic_id,
                )
            )
            membership.active = False
        elif invalid == "wrong_clinic":
            other_clinic, other_user = uid(), uid()
            db.add(Clinic(id=other_clinic, name="Other clinic"))
            db.add(Principal(id=other_user, email="other@example.test", password_hash="unused"))
            db.flush()
            db.add(Membership(principal_id=other_user, clinic_id=other_clinic, role="staff"))
            run.authorised_by = other_user
    kwargs = {"unexpected_token": "stale-token"} if invalid == "stale_lease" else {}
    assert not escalate_failure(factory, settings, run_id, **kwargs)
    with factory() as db:
        assert not db.scalar(select(StaffHandoff.id).where(StaffHandoff.run_id == run_id))
        assert not db.scalar(
            select(SimulatedMessage.id).where(
                SimulatedMessage.run_id == run_id,
                SimulatedMessage.kind == "failure_acknowledgement",
            )
        )


def test_existing_business_handoff_gets_notice_without_duplicate_task(runtime):
    from forget_lah.runtime.engine import request_handoff

    factory, _, _ = runtime
    _, run_id, settings = paused_reply(runtime)
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        request_handoff(db, run, "NO_SUITABLE_SLOT", risk="RED")
    assert escalate_failure(factory, settings, run_id)
    assert not escalate_failure(factory, settings, run_id)
    with factory() as db:
        handoffs = list(db.scalars(select(StaffHandoff).where(StaffHandoff.run_id == run_id)))
        assert len(handoffs) == 1 and handoffs[0].risk == "RED"
        assert handoffs[0].reason_code == "NO_SUITABLE_SLOT"
        assert db.scalar(
            select(SimulatedMessage.id).where(
                SimulatedMessage.run_id == run_id,
                SimulatedMessage.kind == "failure_acknowledgement",
            )
        )


def test_unexpected_api_error_is_generic_and_not_reraised(client):
    @client.app.get("/test-unexpected")
    def fail():
        raise RuntimeError("PRIVATE FAILURE DETAILS")

    response = client.get("/test-unexpected")
    assert response.status_code == 500
    assert "PRIVATE" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_active_run_with_cleared_pause_reason_is_not_a_failure(runtime):
    factory, _, settings = runtime
    _, run_id = start(runtime)
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        run.checkpoint = {**run.checkpoint, "pause_reason": None}
    assert not escalate_failure(factory, settings, run_id)
