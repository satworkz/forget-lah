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
from services.mock_clinic.app import candidates, followup_context


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
    assert {s["origin"] for s in waiting["steps"]} == {"mock"}
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
    assert result["steps"][0]["attempts"] == 2
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
    assert not any(s["decision"] for s in result["steps"])


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
            "evidence_ids": [t["id"] for t in obs["tools"] if t["role"] == "engagement"],
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
