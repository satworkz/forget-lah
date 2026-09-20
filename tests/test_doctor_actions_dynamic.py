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


class ContextualGuidanceModel(MockModel):
    """Exercise the live-model contract for a confirmation plus an independent plan/question."""

    def __init__(self, note, guidance_quote):
        self.note = note
        self.guidance_quote = guidance_quote
        self.omitted_review_once = False
        self.repair_seen = False

    def decide(self, obs, *, repair=False):
        event = obs["latest_event"]
        if (
            obs["role"] == "coordinator"
            and event["kind"] == "demo_reply"
            and not obs.get("needs_reviewed")
        ):
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "REVIEW_NEEDS",
                        "reason_code": "PATIENT_NEEDS_REVIEWED",
                        "reply_event_id": event.get("reply_event_id", event["id"]),
                        "updates": [],
                        "patient_questions": [
                            "hope the appointment will be finished by that time"
                        ],
                        "preparation_plans": ["I have movie ticket booked at 12:00pm"],
                        "appointment_intent": "CONFIRM",
                        "appointment_request_quote": "yes pls",
                        "question": None,
                        "comprehension_quote": None,
                        "concern_quote": None,
                    }
                )
            )
        if (
            obs["role"] == "coordinator"
            and obs.get("appointment_intent") == "CONFIRM"
            and "preparation" not in obs.get("returned_specialists", [])
        ):
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "DELEGATE",
                        "reason_code": "PREPARATION_REVIEW_REQUIRED",
                        "target": "preparation",
                        "goal": "Review approved instructions against the patient's question and plan",
                    }
                )
            )

        response = super().decide(obs, repair=repair)
        value = json.loads(response.text)
        if obs["role"] == "preparation" and value.get("step_type") == "RETURN":
            notes = [
                t
                for t in obs["tools"]
                if t["role"] == "preparation"
                and t["result"]["tool_name"] == "get_approved_instructions"
            ]
            note = notes[-1]["result"]["data"]["instructions"][0]
            if obs.get("patient_questions"):
                value["question_answers"] = [
                    {
                        "question_index": 0,
                        "outcome": "UNSUPPORTED",
                        "instruction_id": None,
                        "quote": None,
                    },
                    {
                        "question_index": 1,
                        "outcome": "GUIDANCE",
                        "instruction_id": note["instruction_id"],
                        "quote": self.guidance_quote,
                    },
                ]
            # Reproduce the real Alex incident once: the first otherwise-valid
            # Preparation RETURN omitted scheduling coverage. The runtime should
            # request one bounded repair instead of pausing.
            if not self.omitted_review_once and not repair:
                value["scheduling_review"] = None
                self.omitted_review_once = True
            else:
                if repair:
                    self.repair_seen = True
                value["scheduling_review"] = [
                    {
                        "instruction_id": note["instruction_id"],
                        "quote": note["approved_text"],
                        "effect": "INFORMATION",
                    }
                ]
            return ModelReply(json.dumps(value))
        return response


def test_reschedule_resolution_survives_option_selection_without_reasking(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    add_antenatal_slot(source)
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "I confirm my attendance").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    event(runtime[1], case, "demo_reply", "No, I have not done the scan yet").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    before = view(runtime[1], case)
    checks_before = [
        m
        for m in before["patient_simulator"]["messages"]
        if m["kind"] == "doctor_instruction_check"
    ]
    assert len(checks_before) == 1
    assert before["patient_simulator"]["messages"][-1]["kind"] == "options"

    event(runtime[1], case, "demo_reply", "option 1 is fine").raise_for_status()
    drain(runtime, tools=tools, model=scan_model())
    result = view(runtime[1], case)
    checks_after = [
        m
        for m in result["patient_simulator"]["messages"]
        if m["kind"] == "doctor_instruction_check"
    ]
    assert len(checks_after) == 1, result["patient_simulator"]["messages"]
    assert result["run"]["status"] == "completed", result
    assert source_count(source_engine) == 1


def test_information_note_guides_related_plan_and_bad_first_return_repairs(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    note = (
        "Demo clinic note: bring your existing spectacles if you have them. "
        "Eyes will be blurry after the appointment"
    )
    guidance = "Eyes will be blurry after the appointment"
    set_note(source, "DEMO-MYOPIA-VISIT-01", note)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(
        runtime[1],
        case,
        "demo_reply",
        "yes pls, I have movie ticket booked at 12:00pm, hope the appointment will be finished by that time.",
    ).raise_for_status()
    model = ContextualGuidanceModel(note, guidance)
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)

    assert model.repair_seen is True
    assert result["run"]["status"] == "completed", result
    assert result["handoff"] is None
    assert source_count(source_engine) == 1
    body = result["patient_simulator"]["messages"][-1]["body"]
    assert "can't check that here from the clinic information available" in body
    assert guidance in body
    assert "alternative appointment dates" in body
    assert "requested a callback" not in body


def test_condition_span_reuse_is_source_bound_and_unambiguous():
    from forget_lah.runtime.scheduling import pending_patient_checks

    note = "Confirm the mandatory scan is completed before the visit; if not reschedule."
    resolved = {
        "instruction_id": "n1",
        "quote": note,
        "condition_quote": "Confirm the mandatory scan is completed before the visit",
        "if_not_met": "RESCHEDULE",
        "resolution": "RESCHEDULE",
    }
    narrower = {
        "instruction_id": "n1",
        "quote": note,
        "effect": "PATIENT_CHECK",
        "condition_quote": "mandatory scan is completed before the visit",
        "patient_question": "Have you completed the mandatory scan?",
        "if_not_met": "RESCHEDULE",
        "consequence_quote": "if not reschedule",
    }
    assert pending_patient_checks([narrower], [resolved]) == []

    ambiguous = {
        **narrower,
        "condition_quote": "scan is completed before the visit",
        "patient_question": "Is the scan completed before the visit?",
    }
    assert pending_patient_checks([narrower, ambiguous], [resolved]) == [narrower, ambiguous]


def test_preparation_question_prompt_preserves_scheduling_contract():
    from forget_lah.db import uid
    from forget_lah.runtime.provider import prompt_for

    prompt = prompt_for(
        {
            "role": "preparation",
            "request_id": uid(),
            "expected_case_version": 1,
            "patient_questions": [
                "hope the appointment will be finished by that time",
                "I have a movie ticket booked at 12:00pm",
            ],
            "patient_task_types": ["QUESTION", "PLAN"],
            "simulation": {"enabled": True},
            "allowed_tools": ["get_approved_instructions", "check_prerequisites"],
        },
        False,
    )
    assert "Every RETURN MUST include scheduling_review" in prompt
    assert "still return the complete scheduling_review required above" in prompt
    assert "non-clinical administrative question" in prompt
    assert "after-appointment effect/restriction" in prompt
