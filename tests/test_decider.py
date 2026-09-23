"""Lane A acceptance tests for the System One decider seam.

Hermetic by construction: every test injects an explicit fake transport and marks the event
kind ``mock``. No test in this module performs live inference.
"""

import json

import httpx
import pytest

from forget_lah.db import uid
from forget_lah.runtime.contracts import parse_decision
from forget_lah.runtime.decider import (
    KEV_BLOCKED,
    DeciderGate,
    DeciderModel,
    DeciderModelReply,
    _valid_choice,
    derive_options,
)
from forget_lah.runtime.provider import (
    AnthropicModel,
    MockModel,
    ModelError,
    ModelReply,
    OrganiserModel,
    base_model_for,
    model_for,
)
from forget_lah.settings import Settings

DECIDER_KEY = "private-decider-test-key-not-a-live-credential"


def settings(**kwargs):
    values = {
        "database_url": "sqlite://",
        "agent_model_mode": "mock",
        "agent_decider_enabled": True,
        "agent_decider_url": "https://decider.example",
        "agent_decider_model": "typesafe/jev",
        "agent_decider_timeout": 5,
    }
    values.update(kwargs)
    return Settings(**values, _env_file=None)


def coordinator_observation(**changes):
    observation = {
        "role": "coordinator",
        "request_id": uid(),
        "expected_case_version": 1,
        "goal": "Advance the follow-up goal for the latest event.",
        "latest_event": {"id": uid(), "kind": "started", "content": ""},
        "tools": [],
        "returned_specialists": [],
        "specialist_reports": [],
        "handoff": None,
    }
    observation.update(changes)
    return observation


def tool_document(observation):
    return {
        "request_id": observation["request_id"],
        "expected_case_version": observation["expected_case_version"],
        "step_type": "TOOL",
        "reason_code": "READ_SOURCE",
        "tool_name": "read_followup_context",
    }


def escalate_document(observation):
    return {
        "request_id": observation["request_id"],
        "expected_case_version": observation["expected_case_version"],
        "step_type": "ESCALATE",
        "reason_code": "AMBIGUOUS_REPLY",
    }


class StubInner:
    """Deterministic inner provider; never performs I/O."""

    def __init__(self, build=None, error=None):
        self.calls = []
        self._build = build or (lambda observation: tool_document(observation))
        self._error = error

    def decide(self, observation, *, repair=False):
        self.calls.append((observation, repair))
        if self._error is not None:
            raise self._error
        return ModelReply(json.dumps(self._build(observation)), 3, 4, 1)


class PerTargetInner(StubInner):
    """Types a delegation goal for whichever target the runtime is binding."""

    def __init__(self, goal="Review the case and report back."):
        self.goal = goal
        super().__init__(self._build)

    def _build(self, observation):
        candidate = observation.get("_decider_candidate")
        if not candidate:
            return tool_document(observation)
        return {
            "request_id": observation["request_id"],
            "expected_case_version": observation["expected_case_version"],
            "step_type": "DELEGATE",
            "reason_code": candidate["reason_code"],
            "target": candidate["target"],
            "goal": self.goal,
        }


class EscalatingPerTargetInner(PerTargetInner):
    """An inner provider that escalates on its own and still types delegation goals."""

    def _build(self, observation):
        if not observation.get("_decider_candidate"):
            return escalate_document(observation)
        return super()._build(observation)


class FixedTargetInner(StubInner):
    """Mirrors the deterministic mock: authors one fixed target whatever binding is requested."""

    def __init__(self, target="engagement"):
        self.target = target
        super().__init__(self._build)

    def _build(self, observation):
        candidate = observation.get("_decider_candidate")
        if not candidate:
            return tool_document(observation)
        return {
            "request_id": observation["request_id"],
            "expected_case_version": observation["expected_case_version"],
            "step_type": "DELEGATE",
            "reason_code": "FOLLOWUP_REVIEW_REQUIRED",
            "target": self.target,
            "goal": "Review the follow-up request using current source evidence.",
        }


def answer_body(choice, keys, confidence=0.9, probability=None):
    """The reported confidence and the chosen option's probability are separate signals.

    Live baseline evidence: answers reported confidence 0.31-0.39 while the chosen option held
    0.44-0.50. ``probability`` defaults to ``confidence`` so the simple cases stay simple.
    """
    chosen = confidence if probability is None else probability
    others = [key for key in keys if key != choice]
    rest = (1.0 - chosen) / len(others) if others else 0.0
    return envelope(
        {
            "type": "choice",
            "choice": choice,
            "confidence": confidence,
            "probabilities": {key: (chosen if key == choice else rest) for key in keys},
        }
    )


def envelope(decision, usage=True):
    body = {"model": "typesafe/jev", "answers": {"decision": decision}}
    if usage:
        body["usage"] = {"input_tokens": 11, "output_tokens": 2}
    return body


def handler_for(body, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, json=body)

    return handler


def decider(body, inner=None, **kwargs):
    return DeciderModel(
        settings(**kwargs.pop("settings_kwargs", {})),
        inner or StubInner(),
        inner_name=kwargs.pop("inner_name", "stub"),
        transport=httpx.MockTransport(handler_for(body, kwargs.pop("requests", None))),
        event_kind=kwargs.pop("event_kind", "mock"),
        **kwargs,
    )


# -- 1. registration ---------------------------------------------------------------------


def test_registration_acceptance(tmp_path):
    off = settings(agent_decider_enabled=False)
    assert isinstance(model_for(off, "mock"), MockModel)
    assert isinstance(model_for(off, "organiser"), OrganiserModel)
    assert isinstance(model_for(off, "anthropic"), AnthropicModel)
    assert isinstance(base_model_for(off, "anthropic"), AnthropicModel)
    with pytest.raises(ModelError):
        model_for(off, "missing-mode")

    # Disabled construction stays on the concrete provider: nothing to wrap, nothing to write.
    record_path = tmp_path / "disabled.jsonl"
    disabled = model_for(
        settings(agent_decider_enabled=False, agent_decider_record=str(record_path)), "mock"
    )
    assert not isinstance(disabled, DeciderModel)
    assert not record_path.exists()

    enabled = settings(agent_decider_enabled=True)
    assert isinstance(model_for(enabled, "mock"), DeciderModel)
    # The diagnostic keeps verifying the underlying provider, not the wrapper.
    assert isinstance(base_model_for(enabled, "anthropic"), AnthropicModel)

    monkeypatch_key = DECIDER_KEY
    import os

    os.environ["AGENT_DECIDER_API_KEY"] = monkeypatch_key
    try:
        configured = settings()
        assert configured.agent_decider_api_key.get_secret_value() == monkeypatch_key
        assert monkeypatch_key not in json.dumps(configured.model_dump(), default=str)
    finally:
        os.environ.pop("AGENT_DECIDER_API_KEY", None)


# -- 2. derivation -----------------------------------------------------------------------


def test_derivation_acceptance():
    observation = coordinator_observation()
    options = derive_options(observation)
    assert options.eligible and options.bypass_reason is None
    assert [candidate.key for candidate in options.candidates] == ["1", "2", "3", "4", "5", "6"]
    assert options.truncation == {"shown": 6, "total": 6, "omitted_keys": []}

    assert options.candidates[0].document["tool_name"] == "read_followup_context"
    assert options.candidates[0].document["reason_code"] == "READ_SOURCE"
    assert [candidate.typing_target for candidate in options.candidates[1:3]] == [
        "engagement",
        "preparation",
    ]
    assert [candidate.reason_code for candidate in options.candidates[1:3]] == [
        "FOLLOWUP_REVIEW_REQUIRED",
        "PREPARATION_REVIEW_REQUIRED",
    ]
    wait = options.candidates[3].document
    assert (wait["reason_code"], wait["wake_after_seconds"]) == ("AWAITING_PATIENT_REPLY", 0)
    assert [candidate.document["reason_code"] for candidate in options.candidates[4:]] == [
        "AMBIGUOUS_REPLY",
        "CAPABILITY_UNAVAILABLE",
    ]
    for candidate in options.candidates:
        if candidate.document is not None:
            parse_decision(json.dumps(candidate.document), observation["request_id"], 1)

    # A failed retryable read adds exactly one representative source-retry wait.
    retryable = coordinator_observation(
        tools=[
            {
                "result": {
                    "tool_name": "read_followup_context",
                    "status": "failed",
                    "retryable": True,
                }
            }
        ]
    )
    waits = [
        candidate.document
        for candidate in derive_options(retryable).candidates
        if candidate.document and candidate.document["step_type"] == "WAIT"
    ]
    assert [wait["reason_code"] for wait in waits] == [
        "AWAITING_PATIENT_REPLY",
        "SOURCE_TEMPORARILY_UNAVAILABLE",
    ]
    assert waits[1]["wake_after_seconds"] == 30

    accepted = coordinator_observation(handoff={"accepted": True, "id": uid()})
    completes = [
        candidate.document
        for candidate in derive_options(accepted).candidates
        if candidate.document and candidate.document["step_type"] == "COMPLETE"
    ]
    assert completes and completes[0]["handoff_id"] == accepted["handoff"]["id"]

    # No fabricated completion without a named acceptance.
    unaccepted = coordinator_observation(handoff={"accepted": False, "id": uid()})
    assert not any(
        candidate.document and candidate.document["step_type"] == "COMPLETE"
        for candidate in derive_options(unaccepted).candidates
    )

    # Quote-exact authoring phases are excluded whole, never trimmed to the handled actions.
    quote_phase = coordinator_observation(
        simulation={"enabled": True},
        latest_event={"id": uid(), "kind": "demo_reply", "content": "yes"},
    )
    excluded = derive_options(quote_phase)
    assert not excluded.eligible and excluded.bypass_reason == "unsupported_phase"
    wrong_role = derive_options(coordinator_observation(role="engagement"))
    assert not wrong_role.eligible and wrong_role.bypass_reason == "role"


# -- 3. transport and fallback -----------------------------------------------------------


def test_transport_acceptance():
    observation = coordinator_observation(returned_specialists=["engagement", "preparation"])
    keys = [candidate.key for candidate in derive_options(observation).candidates]
    assert keys == ["1", "2", "3", "4"]

    requests = []
    records = []
    reply = decider(
        answer_body("1", [*keys, KEV_BLOCKED]),
        requests=requests,
        record_hook=records.append,
    ).decide(observation)

    assert isinstance(reply, DeciderModelReply)
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://decider.example/v1/systemone"
    payload = json.loads(request.content)
    assert payload["model"] == "typesafe/jev"
    question = payload["questions"]["decision"]
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {*keys, KEV_BLOCKED}
    assert json.loads(payload["state"])["role"] == "coordinator"
    assert "Authorization" not in request.headers

    decision = parse_decision(reply.text, observation["request_id"], 1)
    assert decision.tool_name == "read_followup_context"
    record = records[0]
    assert record["mapped_decision"] == decision.model_dump(mode="json")
    assert record["fell_back"] is False
    assert record["options"][-1]["key"] == KEV_BLOCKED
    assert record["usage"] == {"input_tokens": 11, "output_tokens": 2, "incomplete": False}

    # Every decider-owned failure performs exactly one attempt and delegates the whole
    # decision: the inner text comes back unchanged.
    failures = {
        "choice_unknown": answer_body("9", [*keys, KEV_BLOCKED]),
        "probabilities_mismatch": envelope(
            {
                "type": "choice",
                "choice": "1",
                "confidence": 0.9,
                "probabilities": {"1": 0.9, "2": 0.1},
            }
        ),
        "not_argmax": envelope(
            {
                "type": "choice",
                "choice": "1",
                "confidence": 0.9,
                "probabilities": {"1": 0.2, "2": 0.3, "3": 0.3, "4": 0.1, KEV_BLOCKED: 0.1},
            }
        ),
        "probability_type": envelope(
            {
                "type": "choice",
                "choice": "1",
                "confidence": 0.9,
                "probabilities": {"1": True, "2": 0.1, "3": 0.0, "4": 0.0, KEV_BLOCKED: -0.1},
            }
        ),
        "probability_sum": envelope(
            {
                "type": "choice",
                "choice": "1",
                "confidence": 0.9,
                "probabilities": {"1": 0.5, "2": 0.5, "3": 0.5, "4": 0.5, KEV_BLOCKED: 0.5},
            }
        ),
        "low_confidence": answer_body("1", [*keys, KEV_BLOCKED], confidence=0.4),
        "blocked": answer_body(KEV_BLOCKED, [*keys, KEV_BLOCKED]),
        "answer_shape": envelope("1"),
    }
    for expected, body in failures.items():
        attempts = []
        reply = decider(body, requests=attempts).decide(observation)
        assert parse_decision(reply.text, observation["request_id"], 1).step_type == "TOOL", (
            expected
        )
        assert len(attempts) == 1, expected

    transport_failures = {
        "timeout": httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("stub"))
        ),
        "http_status": httpx.MockTransport(lambda request: httpx.Response(500, json={})),
        "envelope_invalid": httpx.MockTransport(lambda request: httpx.Response(200, content=b"{")),
    }
    for expected, transport in transport_failures.items():
        records = []
        model = DeciderModel(
            settings(),
            StubInner(),
            inner_name="stub",
            transport=transport,
            event_kind="mock",
            record_hook=records.append,
        )
        result = model.decide(observation)
        assert parse_decision(result.text, observation["request_id"], 1).step_type == "TOOL"
        assert records[0]["fallback_reason"] == expected
        assert records[0]["fell_back"] is True

    # A missing endpoint and a non-HTTPS endpoint carrying a key both bypass before HTTP.
    no_endpoint = DeciderModel(
        settings(agent_decider_url="", agent_decider_fallback_url=""),
        StubInner(),
        inner_name="stub",
        transport=httpx.MockTransport(lambda request: pytest.fail("no HTTP without endpoint")),
        event_kind="mock",
    )
    assert no_endpoint.decide(observation).text

    # The key is environment-only and rides the Authorization header on an https endpoint.
    key = "private-decider-test-key-not-a-live-credential"
    os_environ = __import__("os").environ
    os_environ["AGENT_DECIDER_API_KEY"] = key
    try:
        keyed_requests = []
        keyed = decider(answer_body("1", [*keys, KEV_BLOCKED]), requests=keyed_requests)
        assert parse_decision(keyed.decide(observation).text, observation["request_id"], 1)
    finally:
        os_environ.pop("AGENT_DECIDER_API_KEY", None)
    assert len(keyed_requests) == 1
    assert keyed_requests[0].headers["Authorization"] == f"Bearer {key}"

    # An http endpoint carrying a key is refused before any request is attempted.
    os_environ["AGENT_DECIDER_API_KEY"] = key
    try:
        insecure_requests = []
        insecure = decider(
            answer_body("1", [*keys, KEV_BLOCKED]),
            settings_kwargs={"agent_decider_url": "http://insecure.example"},
            requests=insecure_requests,
        )
        assert parse_decision(insecure.decide(observation).text, observation["request_id"], 1)
    finally:
        os_environ.pop("AGENT_DECIDER_API_KEY", None)
    assert insecure_requests == []


# -- 4. delegation typing, shadow, records ------------------------------------------------


def test_recording_acceptance(tmp_path):
    observation = coordinator_observation()
    record_path = tmp_path / "decider.jsonl"
    inner = PerTargetInner()
    model = DeciderModel(
        settings(agent_decider_record=str(record_path)),
        inner,
        inner_name="stub",
        transport=httpx.MockTransport(
            handler_for(answer_body("1", [str(i) for i in range(1, 7)] + [KEV_BLOCKED]))
        ),
        event_kind="mock",
    )
    reply = model.decide(observation)
    assert (
        parse_decision(reply.text, observation["request_id"], 1).tool_name
        == "read_followup_context"
    )
    # Ordering B: a TOOL choice needs no authored text, so the inner provider is never called.
    assert inner.calls == []

    lines = record_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["schema_version"] == "forget-lah-decider-call-v1"
    assert [option["key"] for option in record["options"]] == [*map(str, range(1, 7)), KEV_BLOCKED]
    assert record["question_version"] == "forget-lah-coordinator-v1"
    assert record["confidence"] == 0.9
    assert record["truncated"] is False
    assert record["gate"] == {
        "mode": "confidence",
        "min_confidence": 0.5,
        "min_probability": 0.0,
        "min_margin": 0.0,
    }
    # Selection only: the chosen option needed no authoring, so there is no typing leg.
    assert [leg["purpose"] for leg in record["legs"]] == ["systemone"]

    # The private typing key never reaches the serialized request context.
    from forget_lah.runtime.provider import prompt_for

    prompt = prompt_for(
        {
            **observation,
            "_decider_candidate": {
                "target": "engagement",
                "reason_code": "FOLLOWUP_REVIEW_REQUIRED",
            },
        },
        False,
    )
    assert "_decider_candidate" not in prompt.split("\nCONTEXT=", 1)[1]
    assert "DELEGATE decision for target engagement" in prompt

    # Shadow acts on the inner decision and records both legs separately.
    shadow_records = []
    shadow = DeciderModel(
        settings(agent_decider_shadow=True),
        EscalatingPerTargetInner(),
        inner_name="stub",
        transport=httpx.MockTransport(
            handler_for(answer_body("1", [str(i) for i in range(1, 7)] + [KEV_BLOCKED]))
        ),
        event_kind="mock",
        record_hook=shadow_records.append,
    )
    shadow_reply = shadow.decide(observation)
    assert parse_decision(shadow_reply.text, observation["request_id"], 1).step_type == "ESCALATE"
    assert shadow_records[0]["mapped_decision"]["step_type"] == "TOOL"
    assert shadow_records[0]["inner_decision"]["step_type"] == "ESCALATE"
    assert shadow_records[0]["shadow"] is True

    # A record sink that cannot be opened must not change the selected decision.
    broken = DeciderModel(
        settings(agent_decider_record=str(tmp_path / "missing" / "decider.jsonl")),
        StubInner(),
        inner_name="stub",
        transport=httpx.MockTransport(
            handler_for(answer_body("1", [str(i) for i in range(1, 7)] + [KEV_BLOCKED]))
        ),
        event_kind="mock",
    )
    assert (
        parse_decision(broken.decide(observation).text, observation["request_id"], 1).step_type
        == "TOOL"
    )

    # Secret redaction: the configured key never appears in the JSONL sink.
    secret_path = tmp_path / "secret.jsonl"
    secret = "private-decider-test-key-not-a-live-credential"
    os_environ = __import__("os").environ
    os_environ["AGENT_DECIDER_API_KEY"] = secret
    try:
        guarded = DeciderModel(
            settings(agent_decider_record=str(secret_path)),
            StubInner(),
            inner_name="stub",
            transport=httpx.MockTransport(
                handler_for(answer_body("1", [str(i) for i in range(1, 7)] + [KEV_BLOCKED]))
            ),
            event_kind="mock",
        )
        guarded.decide(observation)
    finally:
        os_environ.pop("AGENT_DECIDER_API_KEY", None)
    assert secret not in secret_path.read_text()


# -- 5. delegation authoring (ordering B) -------------------------------------------------


def test_delegation_authoring_acceptance():
    """The decider is asked first; only the chosen delegation binding is authored, once."""
    observation = coordinator_observation()
    offered = [*map(str, range(1, 7)), KEV_BLOCKED]

    inner = PerTargetInner(goal="Review the follow-up request using current source evidence.")
    requests = []
    records = []
    model = DeciderModel(
        settings(),
        inner,
        inner_name="stub",
        transport=httpx.MockTransport(handler_for(answer_body("2", offered), requests)),
        event_kind="mock",
        record_hook=records.append,
    )
    decision = parse_decision(model.decide(observation).text, observation["request_id"], 1)
    assert (decision.step_type, decision.target, decision.reason_code) == (
        "DELEGATE",
        "engagement",
        "FOLLOWUP_REVIEW_REQUIRED",
    )
    assert decision.goal == "Review the follow-up request using current source evidence."
    authored = [call for call, _ in inner.calls if call.get("_decider_candidate")]
    assert [call["_decider_candidate"]["target"] for call in authored] == ["engagement"]
    # Exactly one selection and one authoring leg, in the order they happened.
    assert [leg["purpose"] for leg in records[0]["legs"]] == ["systemone", "delegate-typing"]
    assert len(requests) == 1

    # Offered delegation options carry target and reason only: no goal exists before selection.
    criteria = {option["key"]: option["criterion"] for option in records[0]["options"]}
    assert criteria["2"] == "DELEGATE target=engagement reason=FOLLOWUP_REVIEW_REQUIRED"
    assert "goal" not in criteria["3"]
    assert records[0]["options"][1]["typing_target"] == "engagement"
    assert records[0]["options"][1]["decision"] is None

    # An inner that authors a fixed target, as the deterministic mock does, fails binding
    # equality. The selection still happened first, so a live-model choice was made and the
    # whole decision falls back rather than acting on an unvalidated binding.
    fallback_records = []
    fixed = DeciderModel(
        settings(),
        FixedTargetInner(),
        inner_name="stub",
        transport=httpx.MockTransport(handler_for(answer_body("3", offered))),
        event_kind="mock",
        record_hook=fallback_records.append,
    )
    fallback = parse_decision(fixed.decide(observation).text, observation["request_id"], 1)
    assert (fallback.step_type, fallback.reason_code) == ("TOOL", "READ_SOURCE")
    record = fallback_records[0]
    assert record["fell_back"] is True
    assert record["fallback_reason"] == "typing_mismatch"
    assert record["confidence"] == 0.9
    assert record["mapped_decision"] is None
    assert record["acted_decision"]["step_type"] == "TOOL"


# -- 6. gate policy (astra GATE: D, sweepable) ----------------------------------------------


def test_gate_acceptance():
    """The gate is explicit and sweepable, and BLOCKED competes for the margin."""
    offered = {*map(str, range(1, 4)), KEV_BLOCKED}
    # The measured baseline answer: p(choice)=0.44, runner-up 0.35, BLOCKED 0.18, confidence 0.31.
    answer = {
        "type": "choice",
        "choice": "1",
        "confidence": 0.31,
        "probabilities": {"1": 0.44, "2": 0.03, "3": 0.35, KEV_BLOCKED: 0.18},
    }

    def gate(mode, confidence=0.0, probability=0.0, margin=0.0):
        return DeciderGate(
            mode=mode,
            min_confidence=confidence,
            min_probability=probability,
            min_margin=margin,
        )

    # Provisional default: 0.31 does not clear 0.5, so the leg abstains on every baseline call.
    assert _valid_choice(answer, offered, gate("confidence", confidence=0.5)) == "low_confidence"
    assert _valid_choice(answer, offered, gate("confidence", confidence=0.3)) is None

    # Probability mode accepts the same answer and never rescales it.
    assert _valid_choice(answer, offered, gate("probability", probability=0.4)) is None
    assert (
        _valid_choice(answer, offered, gate("probability", probability=0.45)) == "low_probability"
    )

    # Joint mode: the margin over the strongest competitor (option 3, 0.35) is only 0.09.
    steep = gate("joint", confidence=0.3, probability=0.4, margin=0.25)
    assert _valid_choice(answer, offered, steep) == "low_margin"
    assert (
        _valid_choice(answer, offered, gate("joint", confidence=0.3, probability=0.4, margin=0.05))
        is None
    )

    # BLOCKED counts as a competitor: here it is the runner-up at 0.42, so it sets the margin.
    # Excluding it would have passed (0.48 - 0.05 = 0.43); including it does not.
    blocked_pressure = {
        "type": "choice",
        "choice": "1",
        "confidence": 0.6,
        "probabilities": {"1": 0.48, "2": 0.05, "3": 0.05, KEV_BLOCKED: 0.42},
    }
    assert _valid_choice(blocked_pressure, offered, steep) == "low_margin"

    # End to end: the signals diverge as they did live (confidence 0.31, p(choice) 0.45).
    observation = coordinator_observation()
    keys = [*map(str, range(1, 7)), KEV_BLOCKED]
    records = []
    model = DeciderModel(
        settings(agent_decider_gate_mode="probability", agent_decider_min_probability=0.4),
        StubInner(build=tool_document),
        inner_name="stub",
        transport=httpx.MockTransport(
            handler_for(answer_body("1", keys, confidence=0.31, probability=0.45))
        ),
        event_kind="mock",
        record_hook=records.append,
    )
    reply = model.decide(observation)
    assert parse_decision(reply.text, observation["request_id"], 1).step_type == "TOOL"
    assert records[0]["fell_back"] is False, records[0]["fallback_reason"]
    assert records[0]["confidence"] == 0.31
    assert records[0]["gate"] == {
        "mode": "probability",
        "min_confidence": 0.5,
        "min_probability": 0.4,
        "min_margin": 0.0,
    }

    # The identical answer abstains under the provisional confidence gate (0.31 < 0.5). That is
    # why the first baseline measured a property of the gate, not of the model.
    abstained = []
    provisional = DeciderModel(
        settings(),
        StubInner(build=tool_document),
        inner_name="stub",
        transport=httpx.MockTransport(
            handler_for(answer_body("1", keys, confidence=0.31, probability=0.45))
        ),
        event_kind="mock",
        record_hook=abstained.append,
    )
    assert parse_decision(provisional.decide(observation).text, observation["request_id"], 1)
    assert abstained[0]["fell_back"] is True
    assert abstained[0]["fallback_reason"] == "low_confidence"
