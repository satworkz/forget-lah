import json

import httpx
import pytest

from forget_lah.db import uid
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.contracts import CompleteSimulationDecision
from forget_lah.runtime.provider import (
    AnthropicModel,
    ModelError,
    OrganiserModel,
    decision_formats_for,
    model_for,
    response_schema_for,
)
from forget_lah.settings import Settings
from services.mock_clinic.fixtures import followup_context


def settings(**kwargs):
    return Settings(
        database_url="sqlite://",
        llm_gateway_url="https://gateway.example/team",
        llm_gateway_api_key="private-test-key",
        anthropic_api_key="private-anthropic-test-key",
        **kwargs,
        _env_file=None,
    )


def observation():
    return {"role": "coordinator", "request_id": uid(), "expected_case_version": 1}


def anthropic_envelope(**changes):
    return {
        "type": "message",
        "role": "assistant",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": '{"decision":{}}'}],
        "usage": {"input_tokens": 80, "output_tokens": 7},
        **changes,
    }


def test_simulated_completion_schema_preserves_strict_local_evidence_validation():
    obs = {
        **observation(),
        "simulation": {"enabled": True, "complete_evidence_ids": [uid(), uid()]},
    }

    def handler(request):
        schema = json.loads(request.content)["output_config"]["format"]["schema"]
        branches = schema["properties"]["decision"]["anyOf"]
        completion = next(
            b
            for b in branches
            if b["properties"]["step_type"]["const"] == "COMPLETE_SIMULATED_CONFIRMATION"
        )
        evidence = completion["properties"]["evidence_ids"]
        assert evidence["minItems"] == 1 and "maxItems" not in evidence
        return httpx.Response(200, json=anthropic_envelope())

    AnthropicModel(settings(), httpx.MockTransport(handler)).decide(obs)
    decision = {
        "request_id": obs["request_id"],
        "expected_case_version": 1,
        "step_type": "COMPLETE_SIMULATED_CONFIRMATION",
        "reason_code": "SIMULATED_CONFIRMATION_ACKNOWLEDGED",
        "evidence_ids": obs["simulation"]["complete_evidence_ids"],
    }
    CompleteSimulationDecision.model_validate(decision)
    for evidence in (decision["evidence_ids"][:1], decision["evidence_ids"] + [uid()]):
        with pytest.raises(ValueError):
            CompleteSimulationDecision.model_validate({**decision, "evidence_ids": evidence})


def test_anthropic_wire_contract_is_distinct_but_returns_shared_reply():
    def handler(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "private-anthropic-test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["anthropic-workspace-id"] == "workspace-test"
        body = json.loads(request.content)
        assert body["model"] == "claude-sonnet-4-5-20250929"
        assert body["max_tokens"] == 512 and body["stream"] is False
        assert "tools" not in body and "options" not in body
        assert "private" not in body["messages"][0]["content"]
        assert "Correct the decision once, including field limits" in body["system"]
        assert "DELEGATE.goal" in body["system"]
        assert "at most 200 characters" in body["system"]
        assert body["temperature"] == 0
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["messages"][0]["content"].startswith("CONTEXT=")
        assert "request_id" in json.loads(body["messages"][0]["content"].removeprefix("CONTEXT="))
        return httpx.Response(200, json=anthropic_envelope())

    reply = AnthropicModel(
        settings(anthropic_workspace_id="workspace-test"), httpx.MockTransport(handler)
    ).decide(
        observation()
        | {
            "validation_errors": [
                {
                    "field": "DELEGATE.goal",
                    "code": "string_too_long",
                    "message": "String should have at most 200 characters",
                }
            ]
        },
        repair=True,
    )
    assert (reply.text, reply.input_tokens, reply.output_tokens) == ("{}", 80, 7)
    assert isinstance(model_for(settings(), "anthropic"), AnthropicModel)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"role": "user"}, "MODEL_ENVELOPE_INVALID"),
        ({"type": "error"}, "MODEL_ENVELOPE_INVALID"),
        ({"stop_reason": "max_tokens"}, "MODEL_OUTPUT_TRUNCATED"),
        ({"stop_reason": "refusal"}, "MODEL_REFUSED"),
        ({"stop_reason": "tool_use"}, "MODEL_ENVELOPE_INVALID"),
        ({"content": [{"type": "tool_use", "text": "{}"}]}, "MODEL_ENVELOPE_INVALID"),
        (
            {"content": [{"type": "thinking", "text": "private reasoning"}]},
            "MODEL_ENVELOPE_INVALID",
        ),
        ({"content": []}, "MODEL_ENVELOPE_INVALID"),
        ({"content": [None]}, "MODEL_ENVELOPE_INVALID"),
        ({"content": [{"type": "text", "text": ""}]}, "MODEL_ENVELOPE_INVALID"),
        ({"usage": None}, "MODEL_ENVELOPE_INVALID"),
    ],
)
def test_anthropic_rejects_incomplete_or_unexpected_output(changes, code):
    with pytest.raises(ModelError, match=code):
        AnthropicModel(
            settings(),
            httpx.MockTransport(lambda _: httpx.Response(200, json=anthropic_envelope(**changes))),
        ).decide(observation())


def test_anthropic_missing_key_never_uses_organiser_credentials():
    config = Settings(
        database_url="sqlite://", agent_model_mode="anthropic", llm_gateway_api_key="organiser-only"
    )
    assert not config.model_configured
    with pytest.raises(ModelError, match="MODEL_NOT_CONFIGURED"):
        AnthropicModel(
            config, httpx.MockTransport(lambda _: pytest.fail("No key: no HTTP"))
        ).decide(observation())


def test_anthropic_timeout_is_bounded_and_redacted():
    def timeout(request):
        raise httpx.ReadTimeout("private diagnostic", request=request)

    with pytest.raises(ModelError) as error:
        AnthropicModel(settings(), httpx.MockTransport(timeout)).decide(observation())
    assert error.value.code == "MODEL_CONNECTION_FAILED" and error.value.retryable
    assert "private" not in str(error.value)


def test_organiser_wire_contract_and_safe_usage_metadata():
    def handler(request):
        assert str(request.url) == "https://gateway.example/team/api/chat"
        assert request.headers["X-API-Key"] == "private-test-key"
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["model"] == "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
        assert "tools" not in body
        assert "private-test-key" not in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {"role": "assistant", "content": "{}"},
                "prompt_eval_count": 80,
                "eval_count": 7,
            },
        )

    result = OrganiserModel(settings(), httpx.MockTransport(handler)).decide(observation())
    assert (result.input_tokens, result.output_tokens) == (80, 7)


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "MODEL_ACCESS_DENIED", False),
        (403, "MODEL_ACCESS_DENIED", False),
        (429, "MODEL_RATE_LIMITED", True),
        (503, "MODEL_UNAVAILABLE", True),
        (307, "MODEL_HTTP_ERROR", False),
        (400, "MODEL_HTTP_ERROR", False),
    ],
)
@pytest.mark.parametrize("provider", [OrganiserModel, AnthropicModel])
def test_provider_http_errors_do_not_leak_response_or_follow_redirects(
    status, code, retryable, provider
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="private upstream diagnostic",
            headers={"Location": "https://attacker.example", "Retry-After": "9999"},
        )

    with pytest.raises(ModelError) as error:
        provider(settings(), httpx.MockTransport(handler)).decide(observation())
    assert error.value.code == code
    assert error.value.retryable == retryable
    assert "private" not in str(error.value)
    assert error.value.retry_after <= 300
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"done": False},
        {"done": True, "message": None},
        {"done": True, "message": {"role": "user", "content": "{}"}},
        {"done": True, "message": {"role": "assistant", "content": ""}},
    ],
)
def test_provider_rejects_malformed_envelopes(body):
    with pytest.raises(ModelError, match="MODEL_ENVELOPE_INVALID"):
        OrganiserModel(
            settings(), httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        ).decide(observation())


@pytest.mark.parametrize("provider", [OrganiserModel, AnthropicModel])
def test_provider_enforces_body_size_before_network_and_response_size_after(provider):
    def should_not_call(_):
        pytest.fail("Oversized prompt should not leave the app")

    with pytest.raises(ModelError, match="MODEL_REQUEST_TOO_LARGE"):
        provider(
            settings(agent_request_max_bytes=2000), httpx.MockTransport(should_not_call)
        ).decide(observation())
    with pytest.raises(ModelError, match="MODEL_RESPONSE_TOO_LARGE"):
        provider(
            settings(), httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 64001))
        ).decide(observation())


def test_provider_stops_on_truncation_and_recovers_network_error_as_bounded_retry():
    with pytest.raises(ModelError, match="MODEL_OUTPUT_TRUNCATED"):
        OrganiserModel(
            settings(),
            httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "done": True,
                        "done_reason": "length",
                        "message": {"role": "assistant", "content": "{"},
                    },
                )
            ),
        ).decide(observation())

    def timeout(request):
        raise httpx.ReadTimeout("private diagnostic", request=request)

    with pytest.raises(ModelError) as error:
        OrganiserModel(settings(), httpx.MockTransport(timeout)).decide(observation())
    assert error.value.code == "MODEL_CONNECTION_FAILED" and error.value.retryable


@pytest.mark.parametrize(
    "change",
    [
        {"patient_id": "wrong"},
        {"clinic_id": "wrong"},
        {"source_episode_ref": "wrong"},
        {"synthetic": False},
    ],
)
def test_source_binding_rejects_another_patient_or_clinic(change):
    original = followup_context("DEMO-DENTAL-RECALL-01")
    binding = {k: original[k] for k in ("clinic_id", "patient_id", "source_episode_ref")}
    source = {**original, **change}
    result = ClinicTools(
        "http://clinic", httpx.MockTransport(lambda _: httpx.Response(200, json=source))
    ).execute("read_followup_context", binding)
    assert (
        result.status == "failed" and result.error_code == "SOURCE_INVALID" and not result.retryable
    )


@pytest.mark.parametrize(
    "status,error,retryable", [(404, "SOURCE_NOT_FOUND", False), (503, "SOURCE_UNAVAILABLE", True)]
)
def test_source_errors_are_explicit_and_typed(status, error, retryable):
    result = ClinicTools(
        "http://clinic", httpx.MockTransport(lambda _: httpx.Response(status))
    ).execute("read_followup_context", {"source_episode_ref": "demo"})
    assert result.error_code == error and result.retryable == retryable and result.data == {}


def test_model_action_catalog_respects_phase_evidence_and_role():
    obs = {
        "role": "engagement",
        "latest_event": {"kind": "started"},
        "return_requirements": {"missing_tools": []},
    }
    initial = decision_formats_for(obs)
    assert "RETURN" not in initial and "WAIT" in initial
    assert initial["TOOL"]["tool_name"] == ["read_followup_context"]
    obs["latest_event"]["kind"] = "demo_reply"
    assert "RETURN" in decision_formats_for(obs)
    obs["return_requirements"]["missing_tools"] = ["read_followup_context"]
    assert "RETURN" not in decision_formats_for(obs)
    assert "COMPLETE" not in decision_formats_for({"role": "coordinator", "handoff": None})
    assert "COMPLETE" in decision_formats_for(
        {"role": "coordinator", "handoff": {"accepted": True}}
    )


def test_native_schema_uses_only_current_shapes_and_no_case_data():
    from forget_lah.runtime.contracts import parse_decision

    obs = observation() | {
        "role": "engagement",
        "latest_event": {"kind": "demo_reply"},
        "return_requirements": {"missing_tools": ["read_followup_context"]},
    }
    schema = response_schema_for(obs)
    choices = schema["properties"]["decision"]["anyOf"]
    assert {c["properties"]["step_type"]["const"] for c in choices} == {"TOOL", "WAIT", "ESCALATE"}
    assert all(c["additionalProperties"] is False for c in choices)
    wire = json.dumps(schema)
    assert obs["request_id"] not in wire
    assert not any(key in wire for key in ("minLength", "maximum", "discriminator", "oneOf"))
    # Provider constraints do not replace application validation or permit extra findings.
    with pytest.raises(ValueError):
        parse_decision(
            json.dumps(
                {
                    "request_id": obs["request_id"],
                    "expected_case_version": 1,
                    "step_type": "RETURN",
                    "reason_code": "PATIENT_REQUESTED_ALTERNATIVE_DATE",
                    "evidence_ids": ["tool-id"],
                    "intent_finding": "extra field",
                }
            ),
            obs["request_id"],
            1,
        )


def test_delegation_schema_binds_target_to_reason():
    choices = response_schema_for(observation())["properties"]["decision"]["anyOf"]
    for choice in choices:
        if choice["properties"]["step_type"]["const"] == "DELEGATE":
            assert "chars<=200" in choice["properties"]["goal"]["description"]
    pairs = {
        (c["properties"]["target"]["const"], c["properties"]["reason_code"]["const"])
        for c in choices
        if c["properties"]["step_type"]["const"] == "DELEGATE"
    }
    assert pairs == {
        ("engagement", "FOLLOWUP_REVIEW_REQUIRED"),
        ("preparation", "PREPARATION_REVIEW_REQUIRED"),
    }


@pytest.mark.parametrize("role", ["coordinator", "engagement", "preparation"])
def test_model_cannot_select_staff_only_clinical_escalation(role):
    obs = observation() | {"role": role}
    assert decision_formats_for(obs)["ESCALATE"]["reason_code"] == [
        "AMBIGUOUS_REPLY",
        "CAPABILITY_UNAVAILABLE",
    ]
    choices = response_schema_for(obs)["properties"]["decision"]["anyOf"]
    escalation = next(c for c in choices if c["properties"]["step_type"]["const"] == "ESCALATE")
    assert escalation["properties"]["reason_code"]["enum"] == [
        "AMBIGUOUS_REPLY",
        "CAPABILITY_UNAVAILABLE",
    ]


def test_completed_specialist_is_not_redelegated_for_unchanged_event():
    obs = observation() | {"returned_specialists": ["engagement"]}
    assert decision_formats_for(obs)["DELEGATE"]["target"] == ["preparation"]
    choices = response_schema_for(obs)["properties"]["decision"]["anyOf"]
    assert {
        c["properties"]["target"]["const"]
        for c in choices
        if c["properties"]["step_type"]["const"] == "DELEGATE"
    } == {"preparation"}
    obs["returned_specialists"].append("preparation")
    assert "DELEGATE" not in decision_formats_for(obs)


@pytest.mark.parametrize(
    "text",
    [
        '{"decision": {}, "intent_finding": "unexpected"}',
        '{"decision": []}',
        '{"decision": {}, "decision": {}}',
    ],
)
def test_anthropic_rejects_invalid_structured_envelope(text):
    with pytest.raises(ModelError, match="MODEL_ENVELOPE_INVALID"):
        AnthropicModel(
            settings(),
            httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json=anthropic_envelope(content=[{"type": "text", "text": text}])
                )
            ),
        ).decide(observation())


def test_preparation_schema_distinguishes_neutral_plans_from_help_requests():
    obs = {
        **observation(),
        "role": "preparation",
        "patient_questions": ["I will walk", "I cannot find anyone to accompany me"],
        "patient_task_types": ["PLAN", "QUESTION"],
    }
    schema = response_schema_for(obs)
    branch = next(
        b
        for b in schema["properties"]["decision"]["anyOf"]
        if b["properties"]["step_type"].get("const") == "RETURN"
    )
    variants = branch["properties"]["question_answers"]["items"]["anyOf"]
    assert variants[0]["properties"]["outcome"]["enum"] == ["GUIDANCE", "NOT_REQUIRED"]
    assert "CLINIC_REVIEW" in variants[1]["properties"]["outcome"]["enum"]
    assert variants[1]["properties"]["question_index"]["const"] == 1


def test_retry_schema_binds_original_patient_reply_not_wake_event():
    original, retry = uid(), uid()
    obs = {
        **observation(),
        "simulation": {"enabled": True},
        "latest_event": {
            "id": retry,
            "reply_event_id": original,
            "kind": "demo_reply",
            "content": "ஆம்",
            "wake_reason": "retry",
        },
    }
    choices = response_schema_for(obs)["properties"]["decision"]["anyOf"]
    found = False
    for choice in choices:
        prop = choice["properties"].get("reply_event_id")
        if prop:
            found = True
            assert prop == {"type": "string", "const": original}
    assert found
