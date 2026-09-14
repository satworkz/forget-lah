from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from forget_lah.auth import authenticate, digest, hasher, session_principal
from forget_lah.db import (
    AuditEvent,
    AuthSession,
    Clinic,
    FollowupCase,
    Job,
    Membership,
    Principal,
    uid,
    utcnow,
)
from forget_lah.detector import detect
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.engine import claim_run, prepare_step, process_run
from forget_lah.runtime.models import AgentRun, AgentStep, ModelBudget
from forget_lah.runtime.startup import queue_ready_reviews
from forget_lah.seed import seed_automation
from forget_lah.service_identity import AUTOMATION_EMAIL, AUTOMATION_PRINCIPAL_ID
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.worker import claim_job, finish_job
from services.mock_clinic.fixtures import candidates, followup_context


@pytest.fixture
def automatic(store):
    factory = store[1]
    seed_automation(factory)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    return factory, Settings(agent_min_interval_seconds=0, _env_file=None)


def finish_all(factory, settings):
    while claim := claim_job(factory):
        assert finish_job(factory, *claim, settings=settings)


def tools():
    return ClinicTools(
        "http://clinic",
        httpx.MockTransport(
            lambda r: httpx.Response(200, json=followup_context(r.url.path.rsplit("/", 1)[-1]))
        ),
    )


def test_ready_cases_start_without_browser_and_first_read_has_no_model(automatic, signed_client):
    factory, settings = automatic
    assert queue_ready_reviews(factory, settings) == 0  # Still foundation jobs pending.
    finish_all(factory, settings)
    assert queue_ready_reviews(factory, settings) == 0  # Already queued atomically.
    with factory() as db:
        runs = list(db.scalars(select(AgentRun)))
        assert len(runs) == 3
        assert all(r.started_by == AUTOMATION_PRINCIPAL_ID for r in runs)
        ids = {r.case_id for r in runs}
        assert all(db.get(FollowupCase, c).case_version == 2 for c in ids)
    claim = claim_run(factory)

    class NeverCallModel:
        def decide(self, *_args, **_kwargs):
            pytest.fail("The initial read must not invoke any model")

    assert process_run(factory, settings, *claim, model=NeverCallModel(), tools=tools())
    with factory() as db:
        step = db.scalar(select(AgentStep).where(AgentStep.run_id == claim[0]))
        assert step.origin == "rule" and step.attempts == 0
        assert step.policy["decision"] == "ALLOW"
        assert "SERVICE_AUTHORITY_RECHECKED" in step.policy["reason_codes"]
        assert step.tool_result["status"] == "succeeded"
        case_id = step.case_id
        assert db.get(ModelBudget, "organiser").calls == 0
    history = signed_client.get(f"/api/cases/{case_id}/journey").json()
    created = next(e for e in history["entries"] if e["id"] == claim[0])
    assert "automatically" in created["title"]
    assert created["stages"][0]["component"] == "Worker → PostgreSQL"
    # Same runtime reaches durable waiting with no start requests.
    for _ in range(20):
        claim = claim_run(factory)
        if claim is None:
            break
        process_run(factory, settings, *claim, tools=tools())
    with factory() as db:
        assert {r.status for r in db.scalars(select(AgentRun))} == {"waiting"}
    assert queue_ready_reviews(factory, settings) == 0


def test_automatic_read_recovers_expired_lease_without_repeating_model(automatic):
    factory, settings = automatic
    finish_all(factory, settings)
    claim = claim_run(factory)
    work = prepare_step(factory, settings, *claim)
    with factory.begin() as db:
        # Make the same review first in the claim order.
        for run in db.scalars(select(AgentRun)):
            if run.id != claim[0]:
                run.status = "paused"
        db.get(AgentRun, claim[0]).lease_until = utcnow() - timedelta(seconds=1)
    recovered = claim_run(factory)
    assert recovered[0] == claim[0] and recovered[1] != claim[1]
    resumed = prepare_step(factory, settings, *recovered)
    assert resumed["step_id"] == work["step_id"] and resumed["phase"] == "tool_pending"
    process_run(factory, settings, *recovered, tools=tools())
    with factory() as db:
        step = db.get(AgentStep, work["step_id"])
        assert step.attempts == 0 and step.status == "completed"


def test_ready_catchup_does_not_restart_existing_or_other_clinic_cases(automatic):
    factory, settings = automatic
    disabled = settings.model_copy(update={"agent_auto_start_enabled": False})
    finish_all(factory, disabled)
    assert queue_ready_reviews(factory, disabled) == 0
    assert queue_ready_reviews(factory, settings) == 3
    with factory.begin() as db:
        for run, status in zip(
            db.scalars(select(AgentRun)), ["paused", "completed", "waiting"], strict=True
        ):
            run.status = status
    assert queue_ready_reviews(factory, settings) == 0
    other = uid()
    with factory.begin() as db:
        db.add(Clinic(id=other, name="Other clinic"))
        db.flush()
        db.add(Membership(principal_id=AUTOMATION_PRINCIPAL_ID, clinic_id=other))
    candidate = candidates_from_payload(candidates())[0].model_copy(
        update={"patient_id": UUID(uid())}
    )
    detect(factory, other, [candidate])
    finish_all(factory, settings)
    assert queue_ready_reviews(factory, settings) == 0
    with factory() as db:
        assert not db.scalar(select(AgentRun).where(AgentRun.clinic_id == other))


@pytest.mark.parametrize("target", ["principal", "membership"])
def test_revoked_service_access_is_not_restored_by_bootstrap(automatic, target):
    factory, settings = automatic
    finish_all(factory, settings)
    with factory.begin() as db:
        if target == "principal":
            db.get(Principal, AUTOMATION_PRINCIPAL_ID).active = False
        else:
            db.scalar(
                select(Membership).where(Membership.principal_id == AUTOMATION_PRINCIPAL_ID)
            ).active = False
    seed_automation(factory)
    assert queue_ready_reviews(factory, settings) == 0
    assert claim_run(factory) is None
    with factory() as db:
        paused = db.scalar(select(AgentRun).where(AgentRun.status == "paused"))
        assert paused.checkpoint["pause_reason"] == "SERVICE_AUTHORITY_REVOKED"


def test_service_cannot_login_or_use_even_a_fabricated_session(automatic):
    factory, _ = automatic
    password = "known-unit-test-password"
    with factory.begin() as db:
        db.get(Principal, AUTOMATION_PRINCIPAL_ID).password_hash = hasher.hash(password)
        db.add(
            AuthSession(
                token_hash=digest("test-token"),
                csrf_hash=digest("csrf"),
                principal_id=AUTOMATION_PRINCIPAL_ID,
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
    assert authenticate(factory, AUTOMATION_EMAIL, password, 1) is None
    with factory() as db:
        assert session_principal(db, "test-token") is None


def test_missing_model_configuration_is_visible_and_not_requeued(automatic, signed_client):
    factory, settings = automatic
    settings = settings.model_copy(
        update={"agent_model_mode": "anthropic", "anthropic_api_key": None}
    )
    finish_all(factory, settings)
    assert claim_run(factory) is None
    assert queue_ready_reviews(factory, settings) == 0
    with factory() as db:
        runs = list(db.scalars(select(AgentRun)))
        assert all(
            r.status == "paused" and r.checkpoint["pause_reason"] == "MODEL_NOT_CONFIGURED"
            for r in runs
        )
    response = signed_client.get(f"/api/cases/{runs[0].case_id}/agent").json()
    assert response["run"]["pause_reason"] == "MODEL_NOT_CONFIGURED"


def test_job_completion_and_automatic_run_are_one_transaction(automatic, monkeypatch):
    factory, settings = automatic
    claim = claim_job(factory)

    def fail(*_):
        raise ValueError("injected failure before queue commit")

    monkeypatch.setattr("forget_lah.worker.queue_case_review", fail)
    with pytest.raises(ValueError):
        finish_job(factory, *claim, settings=settings)
    with factory() as db:
        assert db.get(Job, claim[0]).status == "running"
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert not db.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "FOUNDATION_CASE_READY")
        )
