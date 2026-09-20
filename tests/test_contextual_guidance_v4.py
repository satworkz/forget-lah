from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_patient_questions import QuestionModel
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.runtime.contracts import QuestionAnswer, SchedulingInstruction
from forget_lah.runtime.questions import question_response, validate_answers


def rendered(plan, answer, intent="CONFIRM"):
    run = SimpleNamespace(
        checkpoint={
            "patient_questions": [plan],
            "patient_task_types": ["PLAN"],
            "question_answers": [answer],
            "appointment_intent": intent,
        }
    )
    reply = SimpleNamespace(id="reply")
    return question_response(run, reply)


@pytest.mark.parametrize(
    "plan,quote",
    [
        (
            "clinic is nearby I can come by walk alone",
            "Eyes will be blurry after the appointment",
        ),
        (
            "I have a movie ticket booked at 12:00pm",
            "Eyes will be blurry after the appointment",
        ),
        (
            "I plan to drive myself home",
            "You may feel drowsy after the procedure",
        ),
    ],
)
def test_practical_guidance_links_source_to_plan_without_inventing_safety_advice(plan, quote):
    body = rendered(
        plan,
        {
            "question_index": 0,
            "outcome": "GUIDANCE",
            "instruction_id": "note1",
            "quote": quote,
            "guidance_relation": "PRACTICAL_RELEVANCE",
        },
    )
    assert plan in body
    assert quote in body
    assert "may be relevant to the practical plan" in body
    assert "alternative appointment dates" in body
    lowered = body.lower()
    assert "you should change" not in lowered
    assert "must not walk" not in lowered
    assert "do not drive" not in lowered


@pytest.mark.parametrize(
    "plan,quote",
    [
        ("My MRI CD is at my office", "Bring your previous MRI images to the appointment."),
        ("I will bring my contact lenses", "Bring your existing spectacles if you have them."),
    ],
)
def test_possible_substitution_never_claims_equivalence(plan, quote):
    body = rendered(
        plan,
        {
            "question_index": 0,
            "outcome": "GUIDANCE",
            "instruction_id": "note1",
            "quote": quote,
            "guidance_relation": "POSSIBLE_SUBSTITUTION",
        },
    )
    assert plan in body
    assert quote in body
    assert "can't confirm" in body
    assert "replaces or satisfies" in body
    lowered = body.lower()
    assert "is acceptable" not in lowered
    assert "is equivalent" not in lowered


def test_irrelevant_plan_does_not_surface_unrelated_doctor_note():
    body = rendered(
        "I had noodles for lunch",
        {
            "question_index": 0,
            "outcome": "NOT_REQUIRED",
            "instruction_id": None,
            "quote": None,
            "guidance_relation": None,
        },
    )
    assert body == "Thanks for letting us know your plans."
    assert "blurry" not in body.lower()


def test_guidance_contract_requires_bounded_relation():
    with pytest.raises(ValidationError, match="bounded guidance relation"):
        QuestionAnswer(
            question_index=0,
            outcome="GUIDANCE",
            instruction_id="note1",
            quote="Eyes will be blurry after the appointment",
        )


def test_guidance_must_be_covered_by_information_review():
    note = "Confirm the scan is completed before the appointment; if not reschedule."
    source_step = SimpleNamespace(
        run_id="run",
        clinic_id="clinic",
        tool_result={
            "status": "succeeded",
            "tool_name": "get_approved_instructions",
            "data": {"instructions": [{"instruction_id": "n1", "approved_text": note}]},
        },
    )

    class FakeDb:
        def get(self, _model, key):
            return source_step if key == "source" else None

    run = SimpleNamespace(
        id="run",
        clinic_id="clinic",
        checkpoint={
            "patient_questions": ["I will take the bus"],
            "patient_task_types": ["PLAN"],
        },
    )
    answer = QuestionAnswer(
        question_index=0,
        outcome="GUIDANCE",
        instruction_id="n1",
        quote="Confirm the scan is completed before the appointment",
        guidance_relation="GENERAL_RELEVANCE",
    )
    patient_check = SchedulingInstruction(
        instruction_id="n1",
        quote=note,
        effect="PATIENT_CHECK",
        condition_quote="Confirm the scan is completed before the appointment",
        patient_question="Have you completed the scan?",
        if_not_met="RESCHEDULE",
        consequence_quote="if not reschedule",
    )
    decision = SimpleNamespace(
        question_answers=[answer],
        evidence_ids=["source"],
        scheduling_review=[patient_check],
    )
    assert validate_answers(FakeDb(), run, decision) == "GUIDANCE_REQUIRES_INFORMATION_REVIEW"

    decision.scheduling_review = [
        SchedulingInstruction(instruction_id="n1", quote=note, effect="INFORMATION")
    ]
    assert validate_answers(FakeDb(), run, decision) is None


def test_real_walking_scenario_gets_contextual_source_grounded_response(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    note = (
        "Demo clinic note: bring your existing spectacles if you have them. "
        "Eyes will be blurry after the appointment"
    )
    guidance = "Eyes will be blurry after the appointment"
    plan = "clinic is nearby I can come by walk alone"
    body = episode_body(source)
    body["doctor_note"] = note
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()

    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Yes, " + plan).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QuestionModel(
            "GUIDANCE",
            guidance,
            task=plan,
            plan=True,
            guidance_relation="PRACTICAL_RELEVANCE",
        ),
    )
    result = view(runtime[1], case)

    assert result["run"]["status"] == "completed", result
    assert result["handoff"] is None
    assert source_count(engine) == 1
    response = result["patient_simulator"]["messages"][-1]["body"]
    assert plan in response
    assert guidance in response
    assert "may be relevant to the practical plan" in response
    assert "alternative appointment dates" in response
    assert "must not walk" not in response.lower()
