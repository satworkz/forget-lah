"""Offline replay of the September 23 Priya selection-routing failure."""

import json

import pytest
from test_doctor_actions_dynamic import (
    SCAN_CONDITION,
    SCAN_CONSEQUENCE,
    SCAN_NOTE,
    SlotSearchDoctorActionModel,
    add_antenatal_slot,
    set_note,
)
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import ModelReply, prompt_for

REQUEST = "I need to reschedule my appointment. What other times are available?"
SELECTION = "Option 1 works for me. Please reschedule my appointment to that time."


class SelectionSearchReplay(SlotSearchDoctorActionModel):
    def __init__(self, choice=1, different=False):
        super().__init__(
            condition_quote=SCAN_CONDITION,
            question="Have you completed the mandatory scan?",
            if_not_met="RESCHEDULE",
            consequence_quote=SCAN_CONSEQUENCE,
        )
        self.choice = choice
        self.different = different

    def decide(self, obs, **kwargs):
        base = dict(
            request_id=obs["request_id"], expected_case_version=obs["expected_case_version"]
        )
        current = obs["latest_event"]
        if (
            obs["role"] == "coordinator"
            and current.get("kind") == "demo_reply"
            and not obs.get("needs_reviewed")
            and not obs["simulation"].get("instruction_check")
        ):
            return ModelReply(
                json.dumps(
                    dict(
                        **base,
                        step_type="REVIEW_NEEDS",
                        reason_code="PATIENT_NEEDS_REVIEWED",
                        reply_event_id=current["id"],
                        updates=[],
                        appointment_intent="CHANGE",
                        appointment_request_quote=current["content"],
                    )
                )
            )
        offer = obs["simulation"].get("selection_offer")
        if (
            obs["role"] == "coordinator"
            and current.get("content") == "10th oct works for me"
            and obs.get("needs_reviewed")
            and obs.get("barriers", {}).get("reply_event_id") == current.get("id")
            and "preparation" not in obs.get("returned_specialists", [])
        ):
            # Match the live order: Preparation ran before Engagement could
            # restore the answered checks from the saved offer's evidence.
            return ModelReply(
                json.dumps(
                    dict(
                        **base,
                        step_type="DELEGATE",
                        reason_code="PREPARATION_REVIEW_REQUIRED",
                        target="preparation",
                        goal="Review source instructions before selected appointment",
                    )
                )
            )
        if obs["role"] == "engagement" and offer:
            # The actual failure had CHANGE + SEARCH_SLOTS even for acceptance.
            assert obs["barriers"]["next_action"] == "SEARCH_SLOTS"
            prompt = prompt_for(obs, False)
            assert "Use INTERPRET_SELECTION" in prompt
            assert "SEARCH_SLOTS: Engagement reads and RETURNs" not in prompt
            if self.different:
                return ModelReply(
                    json.dumps(
                        dict(
                            **base,
                            step_type="RETURN",
                            reason_code="PATIENT_REQUESTED_ALTERNATIVE_DATE",
                            evidence_ids=obs["return_requirements"]["eligible_evidence_ids"],
                        )
                    )
                )
            return ModelReply(
                json.dumps(
                    dict(
                        **base,
                        step_type="INTERPRET_SELECTION",
                        reason_code="PATIENT_SELECTION_REVIEWED",
                        reply_event_id=offer["reply_event_id"],
                        offer_id=offer["offer_id"],
                        option_number=self.choice,
                    )
                )
            )
        return super().decide(obs, **kwargs)


@pytest.mark.parametrize(
    "reply,choice,different",
    [
        (SELECTION, 1, False),
        ("10th oct works for me", 1, False),
        ("Maybe the first one, but I am not sure", None, False),
        ("Please show different appointment options", None, True),
    ],
)
@pytest.mark.parametrize("whatsapp", [False, True])
def test_search_classification_keeps_offer_available_for_interpretation(
    simulated_runtime, reply, choice, different, whatsapp
):
    from test_channel import ingest_test_reply

    runtime, tools, source, source_engine = simulated_runtime

    def send(content):
        if whatsapp:
            ingest_test_reply(runtime, case, content)
        else:
            event(runtime[1], case, "demo_reply", content).raise_for_status()

    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    add_antenatal_slot(source)
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    model = SelectionSearchReplay(choice, different)
    send(REQUEST)
    drain(runtime, tools=tools, model=model)
    assert (
        view(runtime[1], case)["patient_simulator"]["messages"][-1]["kind"]
        == "doctor_instruction_check"
    )
    send("Yes, I have completed the mandatory scan.")
    drain(runtime, tools=tools, model=model)
    before = view(runtime[1], case)
    assert before["patient_simulator"]["messages"][-1]["kind"] == "options"
    assert source_count(source_engine) == 0

    send(reply)
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)
    assert result["run"]["status"] == ("completed" if choice else "waiting"), [
        (s["sequence"], s.get("decision"), s.get("error_code")) for s in result["steps"][-8:]
    ]
    assert source_count(source_engine) == (1 if choice else 0)
    messages = result["patient_simulator"]["messages"]
    assert sum(m["kind"] == "options" for m in messages) == (2 if different else 1)
    assert messages[-1]["kind"] == (
        "options" if different else "acknowledgement" if choice else "clarification"
    )
    assert sum(m["kind"] == "doctor_instruction_check" for m in messages) == 1
