import json

import pytest
from test_patient_memory import NeedsModel, setup_reply
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_runtime import runtime as runtime
from test_simulator import simulator as simulator

from forget_lah.runtime.evidence_text import source_quote
from forget_lah.runtime.provider import ModelReply


@pytest.mark.parametrize(
    "quote,source,expected",
    [
        ("No I can't", "No I can’t", "No I can’t"),
        ('I said "no"', "I said “no”", "I said “no”"),
        ("நான் வர முடியாது", "நான்\nவர முடியாது", "நான்\nவர முடியாது"),
        ("I can attend", "I can't attend", "I can attend"),
        ("Yes I confirm", "No I can’t", "Yes I confirm"),
        ("I cannot attend", "No I can’t", "I cannot attend"),
    ],
)
def test_only_typography_can_be_restored(quote, source, expected):
    assert source_quote(quote, source) == expected


def test_curly_apostrophe_preserves_exact_evidence_and_refusal(simulated_runtime):
    class RefusalModel(NeedsModel):
        def decide(self, obs, **kwargs):
            response = super().decide(obs, **kwargs)
            value = json.loads(response.text)
            if value["step_type"] == "REVIEW_NEEDS":
                value["appointment_request_quote"] = "No I can't"
            elif (
                obs["role"] == "coordinator"
                and obs.get("needs_reviewed")
                and not obs.get("barriers")
            ):
                value = dict(
                    request_id=obs["request_id"],
                    expected_case_version=obs["expected_case_version"],
                    step_type="ASSESS_BARRIERS",
                    reason_code="PATIENT_BARRIERS_REVIEWED",
                    reply_event_id=obs["latest_event"]["id"],
                    evidence_quotes=["No I can't"],
                    next_action="CLARIFY_TIME",
                    clarification_question="Which dates and times would work for you?",
                )
            return ModelReply(json.dumps(value))

    case, result = setup_reply(simulated_runtime, "No I can’t", RefusalModel([], intent="CHANGE"))
    assert result["run"]["status"] == "waiting"
    needs = next(
        s for s in result["steps"] if (s.get("decision") or {}).get("step_type") == "REVIEW_NEEDS"
    )
    assert needs["decision"]["appointment_request_quote"] == "No I can’t"
    assert needs["attempts"] == 1 and not needs["validation_failures"]
    assert "dates and times" in result["patient_simulator"]["messages"][-1]["original_body"]
    assert source_count(simulated_runtime[3]) == 0


def test_cancellation_requests_staff_action_without_slot_search(simulated_runtime):
    case, result = setup_reply(
        simulated_runtime, "Can you cancel that appointment", NeedsModel([], intent="CANCEL")
    )
    assert result["run"]["status"] == "escalated"
    assert result["handoff"]["reason_code"] == "CANCELLATION_REQUESTED"
    assert "not been cancelled yet" in result["patient_simulator"]["messages"][-1]["original_body"]
    assert not any(
        (s.get("decision") or {}).get("step_type") == "ASSESS_BARRIERS" for s in result["steps"]
    )
    assert source_count(simulated_runtime[3]) == 0
    event(simulated_runtime[0][1], case, "accept_handoff").raise_for_status()
    result = view(simulated_runtime[0][1], case)
    assert result["run"]["status"] == "escalated"
    assert result["handoff"]["accepted"]
    assert result["handoff"]["staff_task_status"] != "resolved"


def test_named_acceptance_does_not_call_model_or_reescalate(runtime):
    case, _ = start(runtime)
    drain(runtime)
    event(runtime[1], case, "demo_reply", "Next Friday please").raise_for_status()
    drain(runtime)
    event(runtime[1], case, "accept_handoff").raise_for_status()

    class MustNotCall:
        def decide(self, *args, **kwargs):
            raise AssertionError("Staff acceptance is already verified")

    drain(runtime, model=MustNotCall())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed"
    assert result["handoff"]["staff_task_status"] == "open"
    assert result["steps"][-1]["origin"] == "rule"
    assert result["steps"][-1]["attempts"] == 0


def test_typography_restoration_keeps_strict_json_and_fenced_support():
    from forget_lah.db import uid
    from forget_lah.runtime.contracts import parse_decision

    ident = uid()
    value = dict(
        request_id=ident,
        expected_case_version=1,
        step_type="REVIEW_NEEDS",
        reason_code="PATIENT_NEEDS_REVIEWED",
        reply_event_id=uid(),
        updates=[],
        appointment_intent="CHANGE",
        appointment_request_quote="No I can't",
    )
    text = json.dumps(value)
    with pytest.raises(ValueError):
        parse_decision(json.dumps({**value, "updates": 42}), ident, 1, patient_source="No I can’t")
    repairs = []
    decision = parse_decision(
        "```json\n" + text + "\n```", ident, 1, patient_source="No I can’t", quote_repairs=repairs
    )
    assert decision.appointment_request_quote == "No I can’t" and repairs
    for bad in [
        text[:-1] + ', "appointment_intent":"CONFIRM"}',
        " " * 16001 + text,
        text.replace('"expected_case_version": 1', '"expected_case_version": NaN'),
    ]:
        with pytest.raises(ValueError):
            parse_decision(bad, ident, 1, patient_source="No I can’t")
