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
from forget_lah.runtime.provider import prompt_for
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
    return question_response(run, SimpleNamespace(id="reply"))


def guidance(*, quote, relation, issue, dependency="OTHER", actions):
    return {
        "question_index": 0,
        "outcome": "GUIDANCE",
        "instruction_id": "note1",
        "quote": quote,
        "relation": relation,
        "practical_issue": issue,
        "dependency": dependency,
        "actions": actions,
    }


def test_location_navigation_conflict_produces_actionable_grounded_response():
    plan = "I am not sure about the location, it's okay I can get help from google maps"
    quote = "Patient should refrain from screen lights 3 hours before this appointment"
    body = rendered(
        plan,
        guidance(
            quote=quote,
            relation="CONFLICTS",
            issue="LOCATION_OR_DIRECTIONS",
            dependency="SCREEN_USE",
            actions=[
                "FOLLOW_CLINIC_INSTRUCTION",
                "ARRANGE_ASSISTANCE",
                "CONTACT_CLINIC",
            ],
        ),
    )
    assert plan in body
    assert quote in body
    assert "looking at a screen" in body
    assert "conflicts with that clinic instruction" in body
    assert "avoid screen use" in body
    assert "location or directions" in body
    assert "accompany or assist" in body
    assert "contact the clinic" in body
    assert "diagnos" not in body.lower()


@pytest.mark.parametrize(
    "plan,quote,relation,issue,dependency,actions,expected",
    [
        (
            "I will eat breakfast before coming",
            "Do not eat for 8 hours before the appointment",
            "CONFLICTS",
            "PREPARATION_ROUTINE",
            "FOOD_OR_DRINK",
            ["FOLLOW_CLINIC_INSTRUCTION"],
            "eating or drinking plan you mentioned conflicts",
        ),
        (
            "I will bring my contact lenses instead",
            "Bring your existing spectacles if you have them",
            "POSSIBLE_SUBSTITUTION",
            "ITEM_OR_DOCUMENT",
            "ITEM_OR_DOCUMENT",
            ["CONTACT_CLINIC"],
            "cannot assume that the alternative",
        ),
        (
            "I will walk home alone",
            "Eyes will be blurry after the appointment",
            "MAY_CONFLICT",
            "TRANSPORT_OR_ACCOMPANIMENT",
            "TRAVEL_OR_NAVIGATION",
            ["ARRANGE_ASSISTANCE"],
            "may affect the plan",
        ),
        (
            "I will go straight to work afterwards",
            "Eyes will be blurry after the appointment",
            "MAY_CONFLICT",
            "WORK_OR_SOCIAL_COMMITMENT",
            "TIMING",
            ["OFFER_RESCHEDULE"],
            "alternative appointment dates",
        ),
    ],
)
def test_generic_relations_render_without_inventing_clinical_facts(
    plan, quote, relation, issue, dependency, actions, expected
):
    body = rendered(
        plan,
        guidance(
            quote=quote,
            relation=relation,
            issue=issue,
            dependency=dependency,
            actions=actions,
        ),
    )
    assert quote in body
    assert plan in body
    assert expected in body


def test_irrelevant_plan_is_silent_not_filler_or_note_dump():
    body = rendered(
        "I had noodles for lunch",
        {
            "question_index": 0,
            "outcome": "NOT_REQUIRED",
            "instruction_id": None,
            "quote": None,
            "relation": None,
            "practical_issue": None,
            "actions": [],
        },
    )
    assert body == ""


def test_guidance_contract_enforces_conflict_and_substitution_safety():
    with pytest.raises(ValidationError, match="conflict must preserve"):
        QuestionAnswer(
            question_index=0,
            outcome="GUIDANCE",
            instruction_id="n1",
            quote="Avoid screens",
            relation="CONFLICTS",
            practical_issue="LOCATION_OR_DIRECTIONS",
            dependency="SCREEN_USE",
            actions=["CONTACT_CLINIC"],
        )
    with pytest.raises(ValidationError, match="source-preserving"):
        QuestionAnswer(
            question_index=0,
            outcome="GUIDANCE",
            instruction_id="n1",
            quote="Bring spectacles",
            relation="POSSIBLE_SUBSTITUTION",
            practical_issue="ITEM_OR_DOCUMENT",
            dependency="ITEM_OR_DOCUMENT",
            actions=["ARRANGE_ASSISTANCE"],
        )


def test_guidance_must_be_information_not_patient_check():
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

    class Db:
        def get(self, _model, key):
            return source_step if key == "source" else None

    run = SimpleNamespace(
        id="run",
        clinic_id="clinic",
        checkpoint={
            "patient_questions": ["I will take the bus"],
            "patient_task_types": ["PLAN"],
            "appointment_intent": "CONFIRM",
        },
    )
    answer = QuestionAnswer(
        question_index=0,
        outcome="GUIDANCE",
        instruction_id="n1",
        quote="Confirm the scan is completed before the appointment",
        relation="RELEVANT",
        practical_issue="OTHER",
        dependency="OTHER",
        actions=[],
    )
    check = SchedulingInstruction(
        instruction_id="n1",
        quote=note,
        effect="PATIENT_CHECK",
        condition_quote="Confirm the scan is completed before the appointment",
        patient_question="Have you completed the scan?",
        if_not_met="RESCHEDULE",
        consequence_quote="if not reschedule",
    )
    decision = SimpleNamespace(
        question_answers=[answer], evidence_ids=["source"], scheduling_review=[check]
    )
    assert validate_answers(Db(), run, decision) == "GUIDANCE_REQUIRES_INFORMATION_REVIEW"


def test_preparation_prompt_requires_compatibility_not_keyword_matching():
    obs = {
        "role": "preparation",
        "request_id": "10000000-0000-4000-8000-000000000001",
        "expected_case_version": 1,
        "latest_event": {
            "id": "20000000-0000-4000-8000-000000000001",
            "kind": "demo_reply",
            "content": "Yes, I have a practical plan",
        },
        "patient_questions": ["I have a practical plan"],
        "patient_task_types": ["PLAN"],
        "simulation": {"enabled": True},
        "tools": [],
        "returned_specialists": [],
        "barriers": {},
    }
    prompt = prompt_for(obs, repair=False)
    assert "source-bound compatibility assessment" in prompt
    assert "CONFLICTS" in prompt
    assert "ordinary operational common sense" in prompt
    assert "NEVER infer a diagnosis" in prompt


def test_google_maps_real_turn_does_not_dump_unrelated_spectacles_note(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    note = (
        "Demo clinic note: bring your existing spectacles if you have them. "
        "Patient should refrain from screen lights 3 hours before this appointment."
    )
    relevant = "Patient should refrain from screen lights 3 hours before this appointment"
    plan = "I am not sure about the location, it's okay I can get help from google maps"
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
            relevant,
            task=plan,
            plan=True,
            relation="CONFLICTS",
            practical_issue="LOCATION_OR_DIRECTIONS",
            dependency="SCREEN_USE",
            actions=[
                "FOLLOW_CLINIC_INSTRUCTION",
                "ARRANGE_ASSISTANCE",
                "CONTACT_CLINIC",
            ],
        ),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result
    assert source_count(engine) == 1
    response = result["patient_simulator"]["messages"][-1]["body"]
    assert relevant in response
    assert "conflicts with that clinic instruction" in response
    assert "location or directions" in response
    assert "existing spectacles" not in response
    assert "Thanks for letting us know your plans" not in response


def test_unrelated_real_plan_does_not_dump_any_doctor_note(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    note = "Eyes will be blurry after the appointment"
    plan = "I had noodles for lunch"
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
        model=QuestionModel("NOT_REQUIRED", task=plan, plan=True),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result
    assert source_count(engine) == 1
    response = result["patient_simulator"]["messages"][-1]["body"]
    assert "blurry" not in response.lower()
    assert "Thanks for letting us know your plans" not in response
