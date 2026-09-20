import json
import re
from datetime import UTC, datetime, timedelta

from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body, new_slot
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import MockModel, ModelReply


class DoctorActionModel(MockModel):
    """Simulate live-model extraction; workflow execution remains production code."""

    def __init__(self, *, condition_quote, question, if_not_met, consequence_quote=None):
        self.condition_quote = condition_quote
        self.question = question
        self.if_not_met = if_not_met
        self.consequence_quote = consequence_quote

    def decide(self, obs, **kwargs):
        sim = obs.get("simulation", {})
        event = obs["latest_event"]
        if obs["role"] == "coordinator" and sim.get("instruction_check"):
            text = event.get("content", "")
            lower = text.lower()
            if (
                re.search(r"\bno\b", lower)
                or any(x in lower for x in ("not yet", "haven't", "have not", "do not have"))
            ):
                outcome = "NOT_MET"
            elif any(x in lower for x in ("yes", "done", "completed", "have it")):
                outcome = "MET"
            else:
                outcome = "UNCLEAR"
            return ModelReply(json.dumps({
                "request_id": obs["request_id"],
                "expected_case_version": obs["expected_case_version"],
                "step_type": "INTERPRET_INSTRUCTION_CHECK",
                "reason_code": "DOCTOR_INSTRUCTION_CHECK_REVIEWED",
                "reply_event_id": sim["instruction_check"]["reply_event_id"],
                "question_message_id": sim["instruction_check"]["question_message_id"],
                "outcome": outcome,
                "answer_quote": text,
            }))

        response = super().decide(obs, **kwargs)
        value = json.loads(response.text)
        if obs["role"] == "preparation" and value.get("step_type") == "RETURN":
            review = []
            for item in value["scheduling_review"]:
                # Preserve ordinary informational delivery and add an independent generic check.
                review.append(item)
                if self.condition_quote in item["quote"]:
                    review.append({
                        "instruction_id": item["instruction_id"],
                        "quote": item["quote"],
                        "effect": "PATIENT_CHECK",
                        "condition_quote": self.condition_quote,
                        "patient_question": self.question,
                        "if_not_met": self.if_not_met,
                        "consequence_quote": self.consequence_quote,
                    })
            value["scheduling_review"] = review
            return ModelReply(json.dumps(value))
        return response


SCAN_NOTE = (
    "Demo clinic note: bring your maternity appointment booklet if you have one. "
    "Also confirm with patient that she has done the mandatory scan before this appointment, "
    "if not reschedule."
)
SCAN_CONDITION = "confirm with patient that she has done the mandatory scan before this appointment"
SCAN_CONSEQUENCE = "if not reschedule"


def set_note(source, ref, note):
    body = episode_body(source, ref)
    body["doctor_note"] = note
    source.put(f"/internal/admin/episodes/{ref}", headers=ADMIN, json=body).raise_for_status()


def add_antenatal_slot(source):
    at = (datetime.now(UTC) + timedelta(days=5)).replace(hour=9, minute=0, second=0, microsecond=0)
    body = new_slot(
        specialty="antenatal",
        starts_at=at.isoformat(),
        ends_at=(at + timedelta(minutes=30)).isoformat(),
    )
    response = source.post("/internal/admin/slots", headers=ADMIN, json=body)
    response.raise_for_status()
    return response.json()["id"]


def scan_model():
    return DoctorActionModel(
        condition_quote=SCAN_CONDITION,
        question="Have you completed the mandatory scan advised before this appointment?",
        if_not_met="RESCHEDULE",
        consequence_quote=SCAN_CONSEQUENCE,
    )


def test_mandatory_scan_yes_blocks_then_confirms(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "I confirm my attendance").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    check = result["patient_simulator"]["messages"][-1]
    assert check["kind"] == "doctor_instruction_check"
    assert "mandatory scan" in check["body"].lower()
    assert source_count(source_engine) == 0

    event(runtime[1], case, "demo_reply", "Yes, the mandatory scan is done").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result
    assert result["handoff"] is None
    assert source_count(source_engine) == 1


def test_mandatory_scan_no_proposes_alternative_before_booking(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    alt = add_antenatal_slot(source)
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "I confirm my attendance").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    event(runtime[1], case, "demo_reply", "No, I have not done the scan yet").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    assert source_count(source_engine) == 0
    offer = result["patient_simulator"]["messages"][-1]
    assert offer["kind"] == "options"
    assert alt in [s["id"] for s in offer["evidence"]["slots"]]


def test_generic_referral_check_routes_to_clinic_review(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    note = (
        "Bring the referral letter. Confirm with the patient that the referral letter has been received; "
        "if it has not been received, clinic staff must review before confirmation."
    )
    condition = "Confirm with the patient that the referral letter has been received"
    set_note(source, "DEMO-ANTENATAL-VISIT-01", note)
    model = DoctorActionModel(
        condition_quote=condition,
        question="Have you received the referral letter?",
        if_not_met="CLINIC_REVIEW",
    )
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "I confirm my attendance").raise_for_status()
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)
    assert result["patient_simulator"]["messages"][-1]["kind"] == "doctor_instruction_check"
    event(runtime[1], case, "demo_reply", "No, I do not have it").raise_for_status()
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)
    assert result["run"]["status"] == "escalated", result
    assert result["handoff"]["risk"] == "AMBER"
    assert source_count(source_engine) == 0


def test_unclear_instruction_answer_reasks_once_then_handoffs(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "I confirm my attendance").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())

    event(runtime[1], case, "demo_reply", "I am not sure about that").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    assert result["patient_simulator"]["messages"][-1]["kind"] == "doctor_instruction_check"
    assert source_count(source_engine) == 0

    event(runtime[1], case, "demo_reply", "Still not sure").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "escalated", result
    assert result["handoff"]["risk"] == "AMBER"
    assert source_count(source_engine) == 0


def test_changed_doctor_note_invalidates_previous_check_resolution():
    from forget_lah.runtime.scheduling import pending_patient_checks

    old = {
        "instruction_id": "doctor-note",
        "quote": "Confirm scan completed; if not reschedule.",
        "effect": "PATIENT_CHECK",
        "condition_quote": "Confirm scan completed",
        "patient_question": "Have you completed the scan?",
        "if_not_met": "RESCHEDULE",
        "consequence_quote": "if not reschedule",
    }
    resolution = {
        "instruction_id": old["instruction_id"],
        "quote": old["quote"],
        "condition_quote": old["condition_quote"],
        "if_not_met": old["if_not_met"],
        "resolution": "MET",
    }
    changed = {
        **old,
        "quote": "Confirm scan completed AND referral received; if not reschedule.",
        "condition_quote": "Confirm scan completed AND referral received",
        "patient_question": "Have you completed the scan and received the referral?",
    }
    assert pending_patient_checks([old], [resolution]) == []
    assert pending_patient_checks([changed], [resolution]) == [changed]


def test_patient_check_does_not_hide_explicit_date_deadline():
    from forget_lah.runtime.scheduling import normalize_review

    review = normalize_review(
        [
            {
                "instruction_id": "doctor-note",
                "quote": "Confirm the blood test is complete before the visit; if not reschedule. Appointment must be completed by October 2027.",
                "effect": "PATIENT_CHECK",
                "date_from": None,
                "date_to": None,
                "condition_quote": "Confirm the blood test is complete before the visit",
                "patient_question": "Have you completed the blood test?",
                "if_not_met": "RESCHEDULE",
                "consequence_quote": "if not reschedule",
            }
        ]
    )
    assert any(item["effect"] == "PATIENT_CHECK" for item in review)
    windows = [item for item in review if item["effect"] == "DATE_WINDOW"]
    assert windows and windows[0]["date_to"] == "2027-10-31"


def test_instruction_check_keeps_red_symptom_path_available():
    from forget_lah.db import uid
    from forget_lah.runtime.provider import decision_formats_for

    obs = {
        "role": "coordinator",
        "request_id": uid(),
        "expected_case_version": 1,
        "latest_event": {
            "id": uid(),
            "kind": "demo_reply",
            "content": "I am having chest pain now",
        },
        "simulation": {
            "enabled": True,
            "instruction_check": {
                "reply_event_id": uid(),
                "question_message_id": uid(),
            },
        },
        "returned_specialists": [],
        "barriers": {},
        "tools": [],
    }
    formats = decision_formats_for(obs)
    assert set(formats) == {"INTERPRET_INSTRUCTION_CHECK", "REPORT_SYMPTOMS"}


def test_patient_check_condition_and_reschedule_consequence_must_be_exact_source_text():
    from types import SimpleNamespace

    from forget_lah.runtime.contracts import SchedulingInstruction
    from forget_lah.runtime.scheduling import validate_review

    note = "Confirm the scan is complete before the appointment; if not reschedule."
    source_step = SimpleNamespace(
        run_id="run",
        clinic_id="clinic",
        tool_result={
            "tool_name": "get_approved_instructions",
            "data": {"instructions": [{"instruction_id": "n1", "approved_text": note}]},
        },
    )

    class FakeDb:
        def get(self, _model, key):
            return source_step if key == "source" else None

    run = SimpleNamespace(id="run", clinic_id="clinic")
    bad_condition = SimpleNamespace(
        evidence_ids=["source"],
        scheduling_review=[
            SchedulingInstruction(
                instruction_id="n1",
                quote=note,
                effect="PATIENT_CHECK",
                condition_quote="Confirm an invented blood test",
                patient_question="Have you completed the blood test?",
                if_not_met="CLINIC_REVIEW",
            )
        ],
    )
    assert validate_review(FakeDb(), run, bad_condition) == "PATIENT_CHECK_CONDITION_SOURCE_MISMATCH"

    bad_consequence = SimpleNamespace(
        evidence_ids=["source"],
        scheduling_review=[
            SchedulingInstruction(
                instruction_id="n1",
                quote=note,
                effect="PATIENT_CHECK",
                condition_quote="Confirm the scan is complete before the appointment",
                patient_question="Have you completed the scan?",
                if_not_met="RESCHEDULE",
                consequence_quote="if not cancel permanently",
            )
        ],
    )
    assert validate_review(FakeDb(), run, bad_consequence) == "PATIENT_CHECK_CONSEQUENCE_SOURCE_MISMATCH"
