"""Lane A runtime integration tests: plan milestones 5-7.

Every test drives the real engine against a real migrated SQLite store and injects a fake System
One transport, so the assertions are hermetic. No test in this module performs live inference.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from forget_lah.db import uid
from forget_lah.detector import detect
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.contracts import parse_decision
from forget_lah.runtime.decider import KEV_BLOCKED, DeciderModel, criterion_for, derive_options
from forget_lah.runtime.engine import claim_run, prepare_step, process_run
from forget_lah.runtime.journey import _step_provider_label
from forget_lah.runtime.models import AgentRun, AgentStep
from forget_lah.runtime.provider import ModelReply, base_model_for
from forget_lah.seed import seed_automation
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.worker import claim_job, finish_job
from services.mock_clinic.fixtures import candidates, followup_context


def tools():
    """The same mock clinic transport the other runtime suites use."""
    return ClinicTools(
        "http://clinic",
        httpx.MockTransport(
            lambda r: httpx.Response(200, json=followup_context(r.url.path.rsplit("/", 1)[-1]))
        ),
    )


def systemone_body(choice, keys, confidence=0.9, probability=None):
    chosen = confidence if probability is None else probability
    others = [key for key in keys if key != choice]
    rest = (1.0 - chosen) / len(others) if others else 0.0
    return {
        "model": "typesafe/jev",
        "answers": {
            "decision": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {key: (chosen if key == choice else rest) for key in keys},
            }
        },
        "usage": {"input_tokens": 21, "output_tokens": 3},
    }


def handler_for(body, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, json=body)

    return handler


class StubInner:
    """Deterministic inner provider; never performs I/O."""

    def __init__(self):
        self.calls = []

    def decide(self, observation, *, repair=False):
        self.calls.append((observation, repair))
        document = {
            "request_id": observation["request_id"],
            "expected_case_version": observation["expected_case_version"],
            "step_type": "ESCALATE",
            "reason_code": "AMBIGUOUS_REPLY",
        }
        return ModelReply(json.dumps(document), 3, 4, 1)


@pytest.fixture
def pending_coordinator(store):
    """Advance the real runtime to its first pending Coordinator phase.

    The initial read is an application rule, which is why the walk itself consults no model.
    """
    factory = store[1]
    seed_automation(factory)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    settings = Settings(agent_min_interval_seconds=0, agent_model_mode="mock", _env_file=None)
    while claim := claim_job(factory):
        assert finish_job(factory, *claim, settings=settings)
    for _ in range(80):
        claim = claim_run(factory)
        if claim is None:
            break
        work = prepare_step(factory, settings, *claim)
        if work is None:
            continue
        if work["phase"] == "pending" and work["observation"].get("role") == "coordinator":
            with factory() as db:
                step = db.get(AgentStep, work["step_id"])
            # Discovery already reserved one attempt; each test measures the delta it causes.
            return factory, settings, claim, work["observation"], step.attempts if step else 0
        process_run(factory, settings, *claim, tools=tools())
    pytest.fail("the runtime never reached a pending Coordinator phase")


def decider_for(settings, body, records, requests=None, inner=None):
    """A decider wired to an injected fake transport; never reaches the network."""
    return DeciderModel(
        settings.model_copy(update={"agent_decider_enabled": True}),
        inner if inner is not None else base_model_for(settings, "mock"),
        inner_name="mock" if inner is None else "stub",
        transport=httpx.MockTransport(handler_for(body, requests)),
        event_kind="live-model",
        record_hook=records.append,
    )


def test_runtime_acceptance(pending_coordinator):
    """A live decider leg is persisted as live, and rule steps stay rule steps."""
    factory, settings, claim, observation, before = pending_coordinator
    options = derive_options(observation)
    assert options.eligible, options.bypass_reason
    assert len(options.candidates) >= 5
    # Offer only non-authored candidates so this runtime test needs no delegation typing.
    pick = next(c for c in options.candidates if c.spec["step_type"] != "DELEGATE")
    keys = [candidate.key for candidate in options.candidates] + [KEV_BLOCKED]
    requests, records = [], []
    decider = decider_for(settings, systemone_body(pick.key, keys), records, requests)

    assert process_run(factory, settings, *claim, model=decider, tools=tools())
    assert len(requests) == 1
    assert records[0]["decision_provider"] == "systemone-decider"
    assert records[0]["fell_back"] is False
    assert records[0]["gate"]["mode"] == "confidence"

    with factory() as db:
        steps = list(
            db.scalars(
                select(AgentStep).where(AgentStep.run_id == claim[0]).order_by(AgentStep.sequence)
            )
        )
        # The initial read is an application rule; the decider is never consulted for it.
        assert steps[0].origin == "rule"
        acted = steps[-1]
        assert acted.origin == "model"
        assert acted.observation["decider"]["decision_provider"] == "systemone-decider"
        assert acted.observation["decider"]["origin"] == "model"
        assert acted.observation["decider"]["confidence"] == 0.9
        assert (acted.policy or {}).get("decision") == "ALLOW"
        assert acted.status == "completed"
        # Exactly one further attempt: the decider consumed no extra retry budget.
        assert acted.attempts == before + 1, (before, acted.attempts)


def test_quote_exclusion_acceptance(pending_coordinator):
    """A phase exposing a quote-bearing action is excluded, and repair never reaches the decider."""
    _factory, settings, _claim, observation, _before = pending_coordinator
    quote_bearing = json.loads(json.dumps(observation))
    quote_bearing["simulation"] = {**observation.get("simulation", {}), "enabled": True}
    quote_bearing["clarification_count"] = 0
    quote_bearing["returned_specialists"] = []
    quote_bearing["latest_event"] = {
        "id": observation.get("latest_event", {}).get("id") or uid(),
        "kind": "demo_reply",
        "content": "The pain is still there after the extraction.",
    }
    derived = derive_options(quote_bearing)
    assert derived.eligible is False
    assert derived.bypass_reason == "unsupported_phase"

    calls, records = [], []
    inner = StubInner()
    decider = DeciderModel(
        settings.model_copy(update={"agent_decider_enabled": True}),
        inner,
        inner_name="stub",
        transport=httpx.MockTransport(lambda request: calls.append(request)),
        event_kind="mock",
        record_hook=records.append,
    )
    reply = decider.decide(quote_bearing)
    assert calls == []
    assert records[0]["bypass_reason"] == "unsupported_phase"
    assert records[0]["fell_back"] is False
    assert records[0]["decision_provider"] == "stub"
    assert (
        parse_decision(
            reply.text, observation["request_id"], observation["expected_case_version"]
        ).step_type
        == "ESCALATE"
    )

    # Repair short-circuits before derivation and keeps the inner observation and flag intact.
    decider.decide(observation, repair=True)
    assert calls == []
    assert records[1]["fallback_reason"] == "repair"
    assert [repair for _observation, repair in inner.calls] == [False, True]


def test_fixture_evidence_acceptance(pending_coordinator):
    """Print the real saved observation, the offered options and the parsed emitted decision.

    Run with ``-s`` to read the evidence line; the assertions hold with or without capture.
    """
    _factory, settings, _claim, observation, _before = pending_coordinator
    options = derive_options(observation)
    assert options.eligible, options.bypass_reason
    pick = next(c for c in options.candidates if c.spec["step_type"] != "DELEGATE")
    keys = [candidate.key for candidate in options.candidates] + [KEV_BLOCKED]
    records = []
    decider = decider_for(settings, systemone_body(pick.key, keys), records)

    reply = decider.decide(observation)
    acted = parse_decision(
        reply.text, observation["request_id"], observation["expected_case_version"]
    )
    evidence = {
        "observation": observation,
        "options": [
            {
                "key": candidate.key,
                "criterion": criterion_for(candidate.spec),
                "binding": candidate.spec,
                "typing_target": candidate.typing_target,
            }
            for candidate in options.candidates
        ],
        "emitted": json.loads(reply.text),
        "step_type": acted.step_type,
        "decision_provider": records[0]["decision_provider"],
    }
    assert set(evidence) == {"observation", "options", "emitted", "step_type", "decision_provider"}
    assert evidence["observation"]["role"] == "coordinator"
    assert len(evidence["options"]) >= 5
    assert evidence["step_type"] == pick.spec["step_type"]
    assert evidence["emitted"]["request_id"] == observation["request_id"]
    print("LANE_A_FIXTURE_EVIDENCE=" + json.dumps(evidence, default=str, ensure_ascii=False))


def test_provenance_surface_acceptance(pending_coordinator, signed_client):
    """Saved provenance reaches the journey label and the agent view; /api/system stays config-only."""
    factory, settings, claim, observation, _before = pending_coordinator
    options = derive_options(observation)
    pick = next(c for c in options.candidates if c.spec["step_type"] != "DELEGATE")
    keys = [candidate.key for candidate in options.candidates] + [KEV_BLOCKED]
    records = []
    decider = decider_for(settings, systemone_body(pick.key, keys), records)
    assert process_run(factory, settings, *claim, model=decider, tools=tools())

    with factory() as db:
        case_id = db.get(AgentRun, claim[0]).case_id

    history = signed_client.get(f"/api/cases/{case_id}/journey").json()
    rendered = json.dumps(history)
    # The live decider leg is named, not the historical unconditional "Claude adapter" label.
    assert "systemone-decider" in rendered
    assert "Claude adapter" not in rendered

    view = signed_client.get(f"/api/cases/{case_id}/agent").json()
    acted = view["steps"][-1]
    assert acted["provider"] == "systemone-decider"
    assert acted["decider"]["origin"] == "model"

    system = signed_client.get("/api/system").json()
    assert system["model_mode"] == "mock"
    assert set(system["decider"]) == {"enabled", "shadow", "model", "gate", "recording"}
    assert system["decider"]["enabled"] is False
    assert system["decider"]["gate"]["mode"] == "confidence"


def test_provider_label_fallback():
    """Observations written before provenance keep their historical label."""

    class Row:
        origin = "model"
        observation: dict = {}

    assert _step_provider_label(Row()) == "Claude adapter"
    Row.observation = {"decider": {"decision_provider": "systemone-decider"}}
    assert _step_provider_label(Row()) == "systemone-decider"

    class MockRow:
        origin = "mock"
        observation: dict = {}

    assert _step_provider_label(MockRow()) == "Simulation"

    class RuleRow:
        origin = "rule"
        observation: dict = {}

    assert _step_provider_label(RuleRow()) == "Application rule"
