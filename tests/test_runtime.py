import json
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from forget_lah.db import Clinic, FollowupCase, Membership, uid, utcnow
from forget_lah.detector import detect
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.contracts import parse_decision
from forget_lah.runtime.engine import (
    claim_run,
    execute_pending_tool,
    prepare_step,
    process_run,
    store_proposal,
)
from forget_lah.runtime.models import AgentEvent, AgentRun, AgentStep, ModelBudget
from forget_lah.runtime.provider import MockModel, ModelError, ModelReply, OrganiserModel
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates, followup_context


@pytest.fixture
def runtime(store, signed_client):
    factory = store[1]
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    return factory, signed_client, Settings(agent_min_interval_seconds=0, _env_file=None)


def source_tools():
    return ClinicTools(
        "http://clinic",
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=followup_context(request.url.path.rsplit("/", 1)[-1])
            )
        ),
    )


def view(client, case_id):
    response = client.get(f"/api/cases/{case_id}/agent")
    assert response.status_code == 200, response.text
    return response.json()


def headers(client, key=None):
    return {
        "Origin": "http://localhost:8080",
        "X-CSRF-Token": client.cookies.get("forget_lah_csrf"),
        "Idempotency-Key": key or uid(),
    }


def start(runtime, specialty="dental"):
    _, client, _ = runtime
    case = next(c for c in client.get("/api/cases").json() if c["specialty"] == specialty)
    response = client.post(
        f"/api/cases/{case['id']}/agent/runs",
        headers=headers(client),
        json={"expected_case_version": case["case_version"]},
    )
    assert response.status_code == 202, response.text
    return case["id"], response.json()["run_id"]


def event(client, case_id, kind, content="", key=None):
    snapshot = view(client, case_id)
    return client.post(
        f"/api/cases/{case_id}/agent/events",
        headers=headers(client, key),
        json={
            "expected_case_version": snapshot["case_version"],
            "run_id": snapshot["run"]["id"],
            "kind": kind,
            "content": content,
        },
    )


def drain(runtime, *, model=None, tools=None):
    factory, _, settings = runtime
    for _ in range(45):
        claim = claim_run(factory)
        if claim is None:
            return
        process_run(factory, settings, *claim, model=model, tools=tools or source_tools())
    pytest.fail("Worker failed to reach a durable checkpoint within the step budget")


@pytest.mark.parametrize("specialty", ["dental", "myopia", "antenatal"])
def test_mixed_reply_delegates_both_specialists_and_requires_owned_handoff(runtime, specialty):
    factory, client, _ = runtime
    case_id, _ = start(runtime, specialty)
    drain(runtime)
    waiting = view(client, case_id)
    assert waiting["run"]["status"] == "waiting"
    assert {s["origin"] for s in waiting["steps"]} == {"mock", "rule"}
    assert all(s["policy"]["decision"] == "ALLOW" for s in waiting["steps"])
    assert claim_run(factory) is None  # WAIT consumes no background model calls.
    assert (
        event(client, case_id, "demo_reply", "Next Friday please. What should I bring?").status_code
        == 202
    )
    drain(runtime)
    handoff = view(client, case_id)
    assert handoff["run"]["status"] == "escalated", handoff
    assert {d["target"] for d in handoff["delegations"] if d["status"] == "returned"} == {
        "engagement",
        "preparation",
    }
    assert not handoff["handoff"]["accepted"]
    assert handoff["handoff"]["owner"] is None
    assert all(
        s["tool_result"]["source_version"] == "synthetic-v1"
        for s in handoff["steps"]
        if s["tool_result"]
    )
    assert event(client, case_id, "accept_handoff").status_code == 202
    drain(runtime)
    done = view(client, case_id)
    assert done["run"]["status"] == "completed"
    assert done["run"]["outcome"] == "OWNED_STAFF_HANDOFF"
    assert done["handoff"]["owner"] == "staff@forget-lah.example"
    assert done["handoff"]["staff_task_status"] == "open"
    with factory() as db:
        assert db.get(FollowupCase, case_id).state == "NEW"  # No booking/clinical completion claim.


@pytest.mark.parametrize("specialty", ["dental", "myopia", "antenatal"])
@pytest.mark.parametrize(
    "reply", ["I confirm my attendance", "I confirm my attendance, what should I bring?"]
)
def test_confirmation_is_an_administrative_handoff_in_read_only_demo(runtime, specialty, reply):
    case_id, _ = start(runtime, specialty)
    drain(runtime)
    assert event(runtime[1], case_id, "demo_reply", reply).status_code == 202
    drain(runtime)
    result = view(runtime[1], case_id)
    assert result["handoff"]["reason_code"] == "CAPABILITY_UNAVAILABLE"
    assert result["handoff"]["risk"] == "AMBER"
    assert not result["handoff"]["accepted"]
    assert result["run"]["status"] == "escalated"
    assert any(
        s["decision"].get("reason_code") == "PATIENT_CONFIRMED_ATTENDANCE" for s in result["steps"]
    )


def test_gateway_blocks_unsupported_clinical_proposal_even_if_model_ignores_schema(runtime):
    class IncorrectClinicalModel(MockModel):
        def decide(self, observation, repair=False):
            response = super().decide(observation, repair=repair)
            decision = json.loads(response.text)
            if decision["step_type"] == "ESCALATE":
                decision["reason_code"] = "CLINICAL_REVIEW_REQUIRED"
                return ModelReply(json.dumps(decision))
            return response

    case_id, _ = start(runtime, "myopia")
    drain(runtime)
    assert (
        event(
            runtime[1], case_id, "demo_reply", "I confirm my attendance, what should I bring?"
        ).status_code
        == 202
    )
    drain(runtime, model=IncorrectClinicalModel())
    result = view(runtime[1], case_id)
    last = result["steps"][-1]
    assert (
        last["decision"]["reason_code"] == "CLINICAL_REVIEW_REQUIRED"
    )  # Preserve actual proposal.
    assert last["policy"]["decision"] == "DENY"
    assert last["policy"]["risk"] != "RED"
    assert last["policy"]["reason_codes"] == ["CLINICAL_ESCALATION_REQUIRES_STAFF_FLAG"]
    assert result["run"]["status"] == "paused" and result["handoff"] is None


def test_clinical_concern_is_a_rule_and_never_waits_for_model(runtime):
    _, client, _ = runtime
    case_id, _ = start(runtime, "antenatal")
    drain(runtime)
    assert event(client, case_id, "clinical_concern").status_code == 202

    class UnavailableModel:
        def decide(self, *_args, **_kwargs):
            pytest.fail("A staff clinical flag must not need a model call")

    drain(runtime, model=UnavailableModel())
    result = view(client, case_id)
    assert result["handoff"]["risk"] == "RED"
    assert result["steps"][-1]["origin"] == "rule"
    assert event(client, case_id, "accept_handoff").status_code == 202
    drain(runtime)
    assert view(client, case_id)["steps"][-1]["policy"]["risk"] == "RED"


@pytest.mark.parametrize("mode", ["mock", "anthropic", "organiser"])
def test_initial_demo_wait_skips_model_budget_and_resumes_with_model(runtime, mode):
    factory, client, settings = runtime
    case_id, run_id = start(runtime)
    settings = settings.model_copy(update={"agent_model_mode": mode, "agent_daily_call_limit": 1})
    with factory.begin() as db:
        db.get(AgentRun, run_id).mode = mode

    class RecordingModel(MockModel):
        observations = None

        def __init__(self):
            self.observations = []

        def decide(self, observation, **kwargs):
            self.observations.append(observation)
            return super().decide(observation, **kwargs)

    model = RecordingModel()
    configured = factory, client, settings
    drain(configured, model=model)
    waiting = view(client, case_id)
    assert waiting["run"]["status"] == "waiting"
    assert (
        len(model.observations) == 1
    )  # Source load and initial WAIT are rules; delegation uses the model.
    assert model.observations[0]["tools"][0]["result"]["status"] == "succeeded"
    step = waiting["steps"][-1]
    assert step["origin"] == "rule" and step["attempts"] == 0
    assert step["decision"]["step_type"] == "WAIT"
    assert step["policy"]["decision"] == "ALLOW"
    with factory() as db:
        run = db.get(AgentRun, run_id)
        assert run.active_role == "engagement" and run.available_at is None
        assert run.lease_token is None
        assert db.get(ModelBudget, "organiser").calls == (0 if mode == "mock" else 1)
    assert claim_run(factory) is None
    recorded = next(e for e in journey(client, case_id)["entries"] if e["id"] == step["id"])
    assert "No Claude call" in recorded["summary"]
    context = recorded["stages"][0]
    assert context["output"]["application_rule"]["source_step_id"] == waiting["steps"][0]["id"]
    assert "no model request" in context["basis"]

    # A fresh reply still receives contextual model review and an owned handoff.
    settings.agent_daily_call_limit = 50
    assert (
        event(client, case_id, "demo_reply", "Next Friday, what should I bring?").status_code == 202
    )
    drain(configured, model=model)
    assert any(
        o["role"] == "engagement" and o["latest_event"]["kind"] == "demo_reply"
        for o in model.observations
    )
    assert view(client, case_id)["run"]["status"] == "escalated"


@pytest.mark.parametrize(
    "condition",
    ["failed_source", "contact_enabled", "missing_capability", "older_event", "revoked"],
)
def test_initial_wait_does_not_bypass_source_or_authority_checks(runtime, condition):
    factory, client, settings = runtime
    _, run_id = start(runtime)
    for _ in range(2):
        process_run(factory, settings, *claim_run(factory), tools=source_tools())
    with factory.begin() as db:
        source = db.scalar(
            select(AgentStep).where(AgentStep.run_id == run_id, AgentStep.sequence == 1)
        )
        if condition == "failed_source":
            source.tool_result = {**source.tool_result, "status": "failed"}
        elif condition in {"contact_enabled", "missing_capability"}:
            data = {**source.tool_result["data"]}
            if condition == "contact_enabled":
                data["can_contact_patient"] = True
            else:
                data.pop("can_contact_patient")
            source.tool_result = {**source.tool_result, "data": data}
        elif condition == "older_event":
            source.observation = {
                **source.observation,
                "latest_event": {"id": uid(), "kind": "started"},
            }
    claim = claim_run(factory)
    if condition == "revoked":
        with factory.begin() as db:
            db.scalar(
                select(Membership).where(Membership.clinic_id == DEMO_CLINIC_ID)
            ).active = False
        assert prepare_step(factory, settings, *claim) is None
        with factory() as db:
            assert db.get(AgentRun, run_id).status == "paused"
    else:
        assert prepare_step(factory, settings, *claim)["phase"] == "pending"
    with factory() as db:
        assert not db.scalar(
            select(AgentStep).where(
                AgentStep.run_id == run_id,
                AgentStep.origin == "rule",
                AgentStep.role == "engagement",
            )
        )


def test_http_idempotency_binds_actor_case_version_and_body(runtime):
    factory, client, _ = runtime
    case = client.get("/api/cases").json()[0]
    path = f"/api/cases/{case['id']}/agent/runs"
    request_headers = headers(client)
    body = {"expected_case_version": case["case_version"]}
    first = client.post(path, headers=request_headers, json=body)
    second = client.post(path, headers=request_headers, json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert (
        client.post(path, headers=request_headers, json={"expected_case_version": 99}).status_code
        == 409
    )
    drain(runtime)
    snapshot = view(client, case["id"])
    body = {
        "expected_case_version": snapshot["case_version"],
        "run_id": snapshot["run"]["id"],
        "kind": "demo_reply",
        "content": "Next Friday",
    }
    path = f"/api/cases/{case['id']}/agent/events"
    request_headers = headers(client)
    first = client.post(path, headers=request_headers, json=body)
    assert first.status_code == 202
    assert (
        client.post(path, headers=request_headers, json=body).json()["event_id"]
        == first.json()["event_id"]
    )
    assert (
        client.post(path, headers=request_headers, json={**body, "content": "Changed"}).status_code
        == 409
    )
    assert (
        client.post(
            path, headers=request_headers, json={**body, "expected_case_version": 99}
        ).status_code
        == 409
    )
    assert client.post(path, headers=headers(client), json=body).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 1
        assert db.scalar(select(func.count()).select_from(AgentEvent)) == 1


def test_agent_routes_require_csrf_and_clinic_membership(runtime):
    factory, client, _ = runtime
    case_id, _ = start(runtime)
    assert (
        client.post(
            f"/api/cases/{case_id}/agent/runs",
            headers={"Origin": "http://localhost:8080", "Idempotency-Key": uid()},
            json={"expected_case_version": 2},
        ).status_code
        == 403
    )
    other_id = uid()
    with factory.begin() as db:
        db.add(Clinic(id=other_id, name="Other demo clinic"))
    row = candidates_from_payload(candidates())[0].model_copy(update={"patient_id": UUID(uid())})
    detect(factory, other_id, [row])
    with factory() as db:
        other_case = db.scalar(select(FollowupCase.id).where(FollowupCase.clinic_id == other_id))
    assert client.get(f"/api/cases/{other_case}/agent").status_code == 404
    assert (
        client.post(
            f"/api/cases/{other_case}/agent/runs",
            headers=headers(client),
            json={"expected_case_version": 1},
        ).status_code
        == 404
    )


def test_expired_lease_rejects_late_model_and_resumes_saved_tool(runtime):
    factory, client, settings = runtime
    case_id, run_id = start(runtime)
    original = claim_run(factory)
    work = prepare_step(factory, settings, *original)
    # Preserve a pre-upgrade model-selected initial read; do not relabel history.
    with factory.begin() as db:
        historical = db.get(AgentStep, work["step_id"])
        historical.status, historical.origin, historical.attempts = "pending", "mock", 1
    reply = MockModel().decide(work["observation"])
    with factory.begin() as db:
        db.get(AgentRun, run_id).lease_until = utcnow() - timedelta(seconds=1)
    replacement = claim_run(factory)
    assert replacement[1] != original[1]
    assert store_proposal(factory, settings, *original, work["step_id"], reply) is None
    retry = prepare_step(factory, settings, *replacement)
    assert retry["step_id"] == work["step_id"]
    assert (
        store_proposal(factory, settings, *replacement, retry["step_id"], reply)
        == "read_followup_context"
    )
    with factory.begin() as db:
        db.get(AgentRun, run_id).lease_until = utcnow() - timedelta(seconds=1)
    replacement = claim_run(factory)

    class NeverCallModel:
        def decide(self, *_args, **_kwargs):
            pytest.fail("Persisted tool proposal must not require another model call")

    process_run(factory, settings, *replacement, model=NeverCallModel(), tools=source_tools())
    result = view(client, case_id)
    assert len(result["steps"]) == 1
    assert result["steps"][0]["tool_result"]["status"] == "succeeded"


@pytest.mark.parametrize("moment", ["before_dispatch", "after_dispatch"])
def test_staff_revocation_prevents_tool_dispatch_or_result_acceptance(runtime, moment):
    factory, client, settings = runtime
    case_id, _ = start(runtime)
    claim = claim_run(factory)
    work = prepare_step(factory, settings, *claim)
    store_proposal(
        factory, settings, *claim, work["step_id"], MockModel().decide(work["observation"])
    )

    def revoke():
        with factory.begin() as db:
            db.scalar(select(Membership)).active = False

    class RevokingTools:
        def execute(self, name, binding):
            if moment == "before_dispatch":
                pytest.fail("Revoked authority cannot dispatch a tool")
            result = source_tools().execute(name, binding)
            revoke()
            return result

    if moment == "before_dispatch":
        revoke()
    assert not execute_pending_tool(factory, settings, *claim, work["step_id"], RevokingTools())
    with factory() as db:
        step = db.get(AgentStep, work["step_id"])
        assert step.tool_result is None
        assert step.status == "rejected"
    assert client.get(f"/api/cases/{case_id}/agent").status_code == 403


def test_pause_revokes_inflight_result_and_retry_keeps_reply(runtime):
    factory, client, settings = runtime
    case_id, _ = start(runtime)
    drain(runtime)
    assert (
        event(client, case_id, "demo_reply", "Next Friday, what should I bring?").status_code == 202
    )
    claim = claim_run(factory)
    work = prepare_step(factory, settings, *claim)
    assert event(client, case_id, "pause").status_code == 202
    assert (
        store_proposal(
            factory, settings, *claim, work["step_id"], MockModel().decide(work["observation"])
        )
        is None
    )
    assert event(client, case_id, "retry").status_code == 202
    drain(runtime)
    result = view(client, case_id)
    assert result["run"]["status"] == "escalated"
    assert any(
        d["target"] == "preparation" and d["status"] == "returned" for d in result["delegations"]
    )


def test_invalid_model_output_repairs_once_then_pauses_without_raw_text(runtime):
    _, client, _ = runtime
    case_id, _ = start(runtime)

    class InvalidModel:
        calls = 0

        def decide(self, observation, *, repair=False):
            assert repair == (self.calls == 1)
            self.calls += 1
            return ModelReply("untrusted secret: not valid JSON")

    model = InvalidModel()
    drain(runtime, model=model)
    result = view(client, case_id)
    assert model.calls == 2
    assert result["run"]["status"] == "paused"
    assert result["steps"][-1]["attempts"] == 2
    assert "untrusted secret" not in json.dumps(result)


def test_model_failure_never_falls_back_to_mock(runtime):
    _, client, _ = runtime
    case_id, _ = start(runtime)

    class FailedModel:
        def decide(self, *_args, **_kwargs):
            raise ModelError("MODEL_ACCESS_DENIED")

    drain(runtime, model=FailedModel())
    result = view(client, case_id)
    assert result["run"]["pause_reason"] == "MODEL_ACCESS_DENIED"
    assert not any(s["decision"] for s in result["steps"] if s["origin"] != "rule")


def test_source_outage_waits_and_preserves_reply_on_timer(runtime):
    factory, client, _ = runtime
    case_id, run_id = start(runtime)
    drain(runtime)
    event(client, case_id, "demo_reply", "Next Friday, what should I bring?")
    failing = ClinicTools("http://clinic", httpx.MockTransport(lambda _: httpx.Response(503)))
    drain(runtime, tools=failing)
    assert view(client, case_id)["run"]["wait_reason"] == "SOURCE_TEMPORARILY_UNAVAILABLE"
    with factory.begin() as db:
        db.get(AgentRun, run_id).available_at = utcnow() - timedelta(seconds=1)
    drain(runtime)
    result = view(client, case_id)
    assert result["run"]["status"] == "escalated"
    assert any(
        d["target"] == "preparation" and d["status"] == "returned" for d in result["delegations"]
    )


@pytest.mark.parametrize(
    "proposal", ["delegate_as_specialist", "unknown_evidence", "unowned_complete", "early_intent"]
)
def test_gateway_rejects_unearned_authority_and_evidence(runtime, proposal):
    factory, client, settings = runtime
    case_id, run_id = start(runtime)
    if proposal == "unowned_complete":
        process_run(factory, settings, *claim_run(factory), tools=source_tools())
    if proposal in {"delegate_as_specialist", "unknown_evidence", "early_intent"}:
        drain(runtime)
        with factory.begin() as db:
            run = db.get(AgentRun, run_id)
            run.status, run.available_at = "queued", utcnow()
            if proposal == "unknown_evidence":
                run.checkpoint = {
                    **run.checkpoint,
                    "latest_event": {
                        **run.checkpoint["latest_event"],
                        "kind": "demo_reply",
                        "content": "Next Friday",
                    },
                }
    claim = claim_run(factory)
    work = prepare_step(factory, settings, *claim)
    obs = work["observation"]
    base = {"request_id": obs["request_id"], "expected_case_version": obs["expected_case_version"]}
    choice = {
        "delegate_as_specialist": {
            "step_type": "DELEGATE",
            "target": "preparation",
            "goal": "Try nested delegation",
            "reason_code": "PREPARATION_REVIEW_REQUIRED",
        },
        "unknown_evidence": {
            "step_type": "RETURN",
            "evidence_ids": [uid()],
            "reason_code": "PATIENT_REQUESTED_ALTERNATIVE_DATE",
        },
        "unowned_complete": {
            "step_type": "COMPLETE",
            "handoff_id": uid(),
            "reason_code": "STAFF_HANDOFF_ACCEPTED",
        },
        "early_intent": {
            "step_type": "RETURN",
            "evidence_ids": [t["id"] for t in obs["tools"]],
            "reason_code": "PATIENT_CONFIRMED_ATTENDANCE",
        },
    }[proposal]
    store_proposal(
        factory, settings, *claim, work["step_id"], ModelReply(json.dumps({**base, **choice}))
    )
    result = view(client, case_id)
    assert result["run"]["status"] == "paused"
    assert result["steps"][-1]["policy"]["decision"] == "DENY"
    assert result["steps"][-1]["policy"]["reason_codes"] == [
        {
            "delegate_as_specialist": "ONLY_COORDINATOR_CAN_DELEGATE",
            "unknown_evidence": "SPECIALIST_EVIDENCE_MISSING",
            "unowned_complete": "OWNED_HANDOFF_EVIDENCE_MISSING",
            "early_intent": "PATIENT_REPLY_REQUIRED",
        }[proposal]
    ]


def test_total_step_limit_cannot_be_reset_by_staff_retry(runtime):
    factory, client, settings = runtime
    case_id, run_id = start(runtime)
    with factory.begin() as db:
        db.get(AgentRun, run_id).step_count = settings.agent_max_steps
    drain(runtime)
    assert view(client, case_id)["run"]["pause_reason"] == "STEP_BUDGET_EXHAUSTED"
    event(client, case_id, "retry")
    drain(runtime)
    assert view(client, case_id)["run"]["pause_reason"] == "STEP_BUDGET_EXHAUSTED"


@pytest.mark.parametrize("mode", ["organiser", "anthropic"])
def test_shared_live_call_budget_and_pacing(runtime, mode):
    factory, _, settings = runtime
    _, run_id = start(runtime)
    settings.agent_model_mode = mode
    settings.agent_daily_call_limit = 1
    with factory.begin() as db:
        db.get(AgentRun, run_id).mode = mode
        budget = db.get(ModelBudget, "organiser")
        budget.day, budget.calls = utcnow().date().isoformat(), 1
    # Required source loading succeeds even with no model budget remaining.
    process_run(factory, settings, *claim_run(factory), tools=source_tools())
    with factory() as db:
        first = db.scalar(select(AgentStep).where(AgentStep.run_id == run_id))
        assert first.origin == "rule" and first.attempts == 0
        assert first.tool_result["status"] == "succeeded"
    claim = claim_run(factory)
    assert prepare_step(factory, settings, *claim) is None
    with factory() as db:
        assert db.get(AgentRun, run_id).checkpoint["pause_reason"] == "DAILY_MODEL_BUDGET_EXHAUSTED"
        assert db.get(ModelBudget, "organiser").calls == 1


def test_every_demo_observation_fits_gateway_request_and_has_no_identity(runtime):
    factory, client, settings = runtime
    case_id, run_id = start(runtime)
    drain(runtime)
    event(client, case_id, "demo_reply", "What should I bring? Next Friday.")
    drain(runtime)
    settings.llm_gateway_url = "https://gateway.example"
    settings.llm_gateway_api_key = "test-key-only"
    # Setting construction wraps secrets; assignment above is not validated by Settings.
    settings = Settings(
        **{**settings.model_dump(), "llm_gateway_api_key": "test-key-only"}, _env_file=None
    )
    calls = []

    def handler(request):
        calls.append(request)
        assert len(request.content) <= settings.agent_request_max_bytes
        assert "patient_id" not in request.content.decode()
        assert "display_alias" not in request.content.decode()
        return httpx.Response(
            200, json={"done": True, "message": {"role": "assistant", "content": "{}"}}
        )

    model = OrganiserModel(settings, httpx.MockTransport(handler))
    with factory() as db:
        for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run_id)):
            model.decide(step.observation)
    assert len(calls) > 5


def test_specialist_sees_missing_checks_and_only_own_evidence(runtime):
    factory, client, _ = runtime
    case_id, run_id = start(runtime)
    drain(runtime)
    event(client, case_id, "demo_reply", "What should I bring? Next Friday.")
    drain(runtime)
    with factory() as db:
        steps = list(
            db.scalars(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.sequence)
            )
        )
        preparation = [s for s in steps if s.role == "preparation"]
        assert preparation[0].observation["return_requirements"]["missing_tools"] == [
            "get_approved_instructions",
            "check_prerequisites",
        ]
        assert preparation[1].observation["return_requirements"]["missing_tools"] == [
            "check_prerequisites"
        ]
        ready = preparation[-1].observation["return_requirements"]
        assert ready["missing_tools"] == []
        assert set(ready["eligible_evidence_ids"]) == {preparation[0].id, preparation[1].id}
        # A Coordinator read cannot satisfy Engagement's own RETURN evidence.
        engagements = [
            s for s in steps if s.role == "engagement" and s.decision["step_type"] == "TOOL"
        ]
        assert all(
            s.observation["return_requirements"]["missing_tools"] == ["read_followup_context"]
            for s in engagements
        )
        assert all(
            s.observation["return_requirements"]["eligible_evidence_ids"] == [] for s in engagements
        )


@pytest.mark.parametrize(
    "change",
    [
        {"reason_code": "INVENTED"},
        {"identity_verified": True},
        {"tool_name": "delete_database"},
        {"expected_case_version": "1"},
        {"expected_case_version": True},
        {"request_id": "x" * 36},
    ],
)
def test_decision_parser_rejects_untrusted_shapes(change):
    request_id = uid()
    payload = {
        "request_id": request_id,
        "expected_case_version": 1,
        "step_type": "TOOL",
        "reason_code": "READ_SOURCE",
        "tool_name": "read_followup_context",
        **change,
    }
    with pytest.raises(ValueError):
        parse_decision(json.dumps(payload), request_id, 1)


@pytest.mark.parametrize(
    "text", ['{"step_type":"TOOL","step_type":"COMPLETE"}', '{"value":NaN}', "[]", "x" * 16001]
)
def test_decision_parser_rejects_ambiguous_json(text):
    with pytest.raises(ValueError):
        parse_decision(text, uid(), 1)


def journey(client, case_id, run_id=None):
    response = client.get(
        f"/api/cases/{case_id}/journey", params={"run_id": run_id} if run_id else {}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_case_journey_before_run_and_legacy_detection(runtime):
    from forget_lah.db import AuditEvent

    factory, client, _ = runtime
    case_id = client.get("/api/cases").json()[0]["id"]
    data = journey(client, case_id)
    assert data["selected_run_id"] is None and not data["runs"]
    assert data["current"]["steps_used"] == 0
    detected = data["entries"][0]
    assert (
        detected["stages"][0]["input"]["source_episode_ref"] == data["case"]["source_episode_ref"]
    )
    assert "source_candidate" in detected["stages"][0]["output"]["details"]
    with factory.begin() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.case_id == case_id))
        audit.details = {"trigger": "UPCOMING", "source_episode_ref": "legacy"}
    assert (
        "not retained"
        in journey(client, case_id)["entries"][0]["stages"][0]["input"]["capture_note"]
    )


def test_case_journey_chronology_inputs_results_and_old_reviews(runtime):
    factory, client, _ = runtime
    case_id, run_id = start(runtime)
    drain(runtime)
    reply = event(client, case_id, "demo_reply", "Next Friday please. What should I bring?")
    drain(runtime)
    acceptance = event(client, case_id, "accept_handoff")
    drain(runtime)
    data = journey(client, case_id)
    entries = data["entries"]
    ids = [e["id"] for e in entries]
    assert data["current"]["status"] == "completed"
    assert data["current"]["handoff"]["accepted"]
    assert data["current"]["handoff"]["staff_task_status"] == "open"
    handoff = next(e for e in entries if e["title"] == "Staff handoff created")
    assert handoff["stages"][0]["output"]["risk"] == "AMBER"
    assert ids.index(handoff["id"]) < ids.index(acceptance.json()["event_id"])
    assert (
        ids.index(run_id)
        < ids.index(reply.json()["event_id"])
        < ids.index(acceptance.json()["event_id"])
    )
    decisions = [e for e in entries if e["kind"] == "decision"]
    assert [e["sequence"] for e in decisions] == list(range(1, len(decisions) + 1))
    assert decisions[-1]["action"] == "COMPLETE"
    assert ids.index(acceptance.json()["event_id"]) < ids.index(decisions[-1]["id"])
    assert {e["origin"] for e in decisions} == {"mock", "rule"}
    first = decisions[0]["stages"]
    assert [x["title"] for x in first] == [
        "Saved context for this application rule",
        "Rule-selected action",
        "Permission check before execution",
        "Actual tool result",
        "Recorded step outcome",
    ]
    assert first[0]["output"]["request_id"] == decisions[0]["id"]
    assert first[1]["output"] == first[2]["input"]
    assert first[3]["output"]["status"] == "succeeded"
    _, new_run_id = start(runtime)
    assert journey(client, case_id)["selected_run_id"] == new_run_id
    historical = journey(client, case_id, run_id)
    assert (
        historical["selected_run_id"] == run_id and historical["current"]["status"] == "completed"
    )
    assert len(historical["runs"]) == 2
    with factory() as db:
        before = (
            db.scalar(select(func.count()).select_from(AgentStep)),
            db.get(ModelBudget, "organiser").calls,
        )
    for _ in range(3):
        journey(client, case_id, run_id)
    with factory() as db:
        assert before == (
            db.scalar(select(func.count()).select_from(AgentStep)),
            db.get(ModelBudget, "organiser").calls,
        )


def test_case_journey_denial_does_not_claim_tool_executed(runtime):
    _, client, _ = runtime
    case_id, _ = start(runtime)

    class WrongTool:
        def decide(self, observation, **kwargs):
            return ModelReply(
                json.dumps(
                    {
                        "request_id": observation["request_id"],
                        "expected_case_version": observation["expected_case_version"],
                        "step_type": "TOOL",
                        "reason_code": "READ_SOURCE",
                        "tool_name": "check_prerequisites",
                    }
                )
            )

    drain(runtime, model=WrongTool())
    data = journey(client, case_id)
    assert data["current"]["status"] == "paused"
    step = next(e for e in data["entries"] if e["kind"] == "decision" and e["origin"] == "mock")
    assert "blocked" in step["summary"]
    assert not any(x["title"] == "Actual tool result" for x in step["stages"])
    assert step["stages"][-1]["output"]["error_code"] == "POLICY_DENIED"


def test_handoff_correction_preserves_original_evidence_and_selected_run(runtime):
    from copy import deepcopy

    from forget_lah.db import AuditEvent
    from forget_lah.runtime.models import StaffHandoff

    factory, client, _ = runtime
    case_id, run_id = start(runtime, "myopia")
    drain(runtime)
    reply = event(client, case_id, "demo_reply", "I confirm my attendance, what should I bring?")
    drain(runtime)
    with factory.begin() as db:
        last = db.scalar(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.sequence.desc())
        )
        # Reproduce the old saved proposal/verdict; a correction must not rewrite it.
        last.decision = {**last.decision, "reason_code": "CLINICAL_REVIEW_REQUIRED"}
        last.policy = {**last.policy, "risk": "RED", "policy_version": "m2a-read-only-v1"}
        original = deepcopy((last.decision, last.policy))
        original_step_id = last.id
        handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run_id))
        handoff_id = handoff.id
        db.add(
            AuditEvent(
                clinic_id=handoff.clinic_id,
                case_id=case_id,
                event_type="HANDOFF_CLASSIFICATION_CORRECTED",
                details={
                    "run_id": run_id,
                    "handoff_id": handoff.id,
                    "original_step_id": last.id,
                    "previous": {"reason_code": "CLINICAL_REVIEW_REQUIRED", "risk": "RED"},
                    "current": {"reason_code": "CAPABILITY_UNAVAILABLE", "risk": "AMBER"},
                    "evidence_ids": [reply.json()["event_id"]],
                    "note": "Explicit correction to an unsupported clinical classification.",
                },
            )
        )
    data = journey(client, case_id)
    assert data["current"]["handoff"]["risk"] == "AMBER"
    created = next(e for e in data["entries"] if e["id"] == handoff_id)
    assert created["stages"][0]["output"]["risk"] == "RED"
    correction = next(
        e for e in data["entries"] if e["title"] == "Staff handoff classification corrected"
    )
    assert correction["at"] >= created["at"]
    assert correction["stages"][0]["input"]["original_step_id"] == original_step_id
    assert correction["stages"][0]["output"]["current"]["risk"] == "AMBER"
    with factory() as db:
        saved = db.get(AgentStep, original_step_id)
        assert (saved.decision, saved.policy) == original
    assert event(client, case_id, "accept_handoff").status_code == 202
    drain(runtime)
    start(runtime, "myopia")
    assert not any(e["id"] == correction["id"] for e in journey(client, case_id)["entries"])
    assert any(e["id"] == correction["id"] for e in journey(client, case_id, run_id)["entries"])


def test_case_journey_clinic_run_and_session_boundaries(runtime):
    factory, client, _ = runtime
    case_id, run_id = start(runtime)
    other_case_id, other_run = start(runtime, "myopia")
    assert client.get(f"/api/cases/{case_id}/journey?run_id={other_run}").status_code == 404
    other_id = uid()
    with factory.begin() as db:
        db.add(Clinic(id=other_id, name="Other demo clinic"))
    row = candidates_from_payload(candidates())[0].model_copy(update={"patient_id": UUID(uid())})
    detect(factory, other_id, [row])
    with factory() as db:
        inaccessible = db.scalar(select(FollowupCase.id).where(FollowupCase.clinic_id == other_id))
    assert client.get(f"/api/cases/{inaccessible}/journey?run_id={run_id}").status_code == 404
    client.cookies.clear()
    assert client.get(f"/api/cases/{other_case_id}/journey").status_code == 401
