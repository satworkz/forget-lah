import json

import pytest
from test_patient_memory import NeedsModel
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import ModelReply


class QuestionModel(NeedsModel):
    def __init__(
        self,
        outcome,
        quote=None,
        intent="CONFIRM",
        task="Do I need someone to accompany me?",
        plan=False,
        relation="RELEVANT",
        practical_issue="OTHER",
        dependency="OTHER",
        actions=None,
    ):
        super().__init__([], intent=intent)
        self.outcome, self.quote, self.task, self.plan = outcome, quote, task, plan
        self.relation = relation
        self.practical_issue = practical_issue
        self.dependency = dependency
        self.actions = actions or []

    def decide(self, obs, **kwargs):
        value = json.loads(super().decide(obs, **kwargs).text)
        if value["step_type"] == "REVIEW_NEEDS":
            value["patient_questions"] = [] if self.plan else [self.task]
            value["preparation_plans"] = [self.task] if self.plan else []
        if (
            obs.get("patient_questions")
            and self.intent == "UNSPECIFIED"
            and value["step_type"] == "DELEGATE"
        ):
            value.update(target="preparation", reason_code="PREPARATION_REVIEW_REQUIRED")
        if value["step_type"] == "RETURN" and obs["role"] == "preparation":
            notes = [
                t for t in obs["tools"] if t["result"]["tool_name"] == "get_approved_instructions"
            ]
            note = notes[-1]["result"]["data"]["instructions"][0]
            answer = dict(
                question_index=0,
                outcome=self.outcome,
                instruction_id=note["instruction_id"] if self.quote else None,
                quote=self.quote,
            )
            if self.outcome == "GUIDANCE":
                answer.update(
                    relation=self.relation,
                    practical_issue=self.practical_issue,
                    dependency=self.dependency,
                    actions=self.actions,
                )
            value["question_answers"] = [answer]
        return ModelReply(json.dumps(value))


@pytest.mark.parametrize("outcome", ["ANSWERED", "CLINIC_REVIEW", "UNSUPPORTED"])
def test_confirmation_and_question_are_independent(simulated_runtime, outcome):
    runtime, tools, source, engine = simulated_runtime
    quote = "Please arrange for an adult to accompany you home."
    body = episode_body(source)
    body["doctor_note"] = quote
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(
        runtime[1], case, "demo_reply", "Yes I confirm, Do I need someone to accompany me?"
    ).raise_for_status()
    drain(
        runtime, tools=tools, model=QuestionModel(outcome, quote if outcome == "ANSWERED" else None)
    )
    result = view(runtime[1], case)
    assert source_count(engine) == 1
    assert len(result["patient_simulator"]["messages"]) == 2
    body = result["patient_simulator"]["messages"][-1]["body"]
    if outcome == "CLINIC_REVIEW":
        assert result["handoff"]["reason_code"] == "PATIENT_QUESTION_CALLBACK"
        assert "requested a callback" in body
    else:
        assert result["run"]["status"] == "completed", result["run"]
        assert (quote if outcome == "ANSWERED" else "can't check that here") in body


def test_question_alone_does_not_confirm(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Do I need someone to accompany me?").raise_for_status()
    drain(runtime, tools=tools, model=QuestionModel("CLINIC_REVIEW", intent="UNSPECIFIED"))
    result = view(runtime[1], case)
    assert source_count(engine) == 0
    assert result["handoff"]["reason_code"] == "PATIENT_QUESTION_CALLBACK"
    assert len(result["patient_simulator"]["messages"]) == 2


@pytest.mark.parametrize(
    "answers,expected",
    [
        ([], "QUESTION_COVERAGE_INCOMPLETE"),
        ([dict(question_index=0, outcome="CLINIC_REVIEW")] * 2, "QUESTION_COVERAGE_INCOMPLETE"),
        (
            [
                dict(
                    question_index=0,
                    outcome="ANSWERED",
                    instruction_id="note1",
                    quote="You can drive safely.",
                )
            ],
            "QUESTION_ANSWER_NOT_IN_APPROVED_SOURCE",
        ),
        (
            [
                dict(
                    question_index=0,
                    outcome="ANSWERED",
                    instruction_id="wrong",
                    quote="Bring glasses.",
                )
            ],
            "QUESTION_ANSWER_NOT_IN_APPROVED_SOURCE",
        ),
        (
            [
                dict(
                    question_index=0,
                    outcome="ANSWERED",
                    instruction_id="note1",
                    quote="Bring glasses.",
                )
            ],
            None,
        ),
    ],
)
def test_answer_requires_complete_coverage_and_source_quote(answers, expected):
    from types import SimpleNamespace

    from forget_lah.runtime.contracts import QuestionAnswer
    from forget_lah.runtime.questions import validate_answers

    run = SimpleNamespace(
        id="run", clinic_id="clinic", checkpoint={"patient_questions": ["What should I bring?"]}
    )
    step = SimpleNamespace(
        run_id="run",
        clinic_id="clinic",
        tool_result={
            "status": "succeeded",
            "tool_name": "get_approved_instructions",
            "data": {
                "instructions": [{"instruction_id": "note1", "approved_text": "Bring glasses."}]
            },
        },
    )
    db = SimpleNamespace(get=lambda *args: step)
    decision = SimpleNamespace(
        question_answers=[QuestionAnswer(**a) for a in answers], evidence_ids=["source"]
    )
    assert validate_answers(db, run, decision) == expected


@pytest.mark.parametrize(
    "plan,note",
    [
        (
            "I will drive on that day to clinic",
            "Eyes will be blurry after the appointment, please bring someone to accompany you",
        ),
        (
            "I plan to eat breakfast before arriving",
            "Please follow the fasting instructions provided by your clinic.",
        ),
        ("I am coming alone", "Please arrange for an adult to accompany you home."),
        (
            "clinic is near by I can come by walk",
            "Eyes will be blurry after the appointment, please bring someone to accompany you",
        ),
        (
            "my daughter can walk back with me",
            "Please bring someone to accompany you after the appointment.",
        ),
    ],
)
def test_confirmation_and_preparation_plan_use_approved_notes(simulated_runtime, plan, note):
    runtime, tools, source, engine = simulated_runtime
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
            note,
            task=plan,
            plan=True,
            relation="RELEVANT",
            practical_issue="OTHER",
        ),
    )
    result = view(runtime[1], case)
    assert source_count(engine) == 1
    messages = result["patient_simulator"]["messages"]
    assert len(messages) == 2
    assert messages[-1]["body"].count(note) == 1
    assert messages[0]["body"].startswith("Hello Alex,")
    assert messages[-1]["body"].startswith("Thank you, Alex.")
    assert not result["handoff"]
    assert "What would help" not in messages[-1]["body"]
    assert result["run"]["status"] == "completed"


@pytest.mark.parametrize(
    "outcome,expected_status", [("NOT_REQUIRED", "completed"), ("CLINIC_REVIEW", "escalated")]
)
def test_plan_coverage_distinguishes_neutral_plan_from_unmet_requirement(
    simulated_runtime, outcome, expected_status
):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    plan = (
        "I am taking the bus"
        if outcome == "NOT_REQUIRED"
        else "I cannot find anyone to accompany me"
    )
    event(runtime[1], case, "demo_reply", "Yes I will attend. " + plan).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QuestionModel(outcome, task=plan, plan=(outcome == "NOT_REQUIRED")),
    )
    result = view(runtime[1], case)
    assert source_count(engine) == 1
    assert result["run"]["status"] == expected_status
    assert ("requested a callback" in result["patient_simulator"]["messages"][-1]["body"]) == (
        outcome == "CLINIC_REVIEW"
    )


def test_plan_only_outcome_cannot_silence_a_question():
    from types import SimpleNamespace

    from forget_lah.runtime.contracts import QuestionAnswer
    from forget_lah.runtime.questions import validate_answers

    run = SimpleNamespace(
        id="run",
        clinic_id="clinic",
        checkpoint={
            "patient_questions": ["Can I skip my medication?"],
            "patient_task_types": ["QUESTION"],
        },
    )
    decision = SimpleNamespace(
        evidence_ids=[], question_answers=[QuestionAnswer(question_index=0, outcome="NOT_REQUIRED")]
    )
    assert validate_answers(None, run, decision) == "PLAN_OUTCOME_REQUIRES_PLAN"


def test_neutral_plan_cannot_also_be_saved_as_arrival_support():
    from pydantic import ValidationError

    from forget_lah.runtime.contracts import NeedsDecision

    with pytest.raises(ValidationError, match="neutral preparation plan"):
        NeedsDecision(
            request_id="10000000-0000-4000-8000-000000000001",
            expected_case_version=1,
            reason_code="PATIENT_NEEDS_REVIEWED",
            step_type="REVIEW_NEEDS",
            reply_event_id="10000000-0000-4000-8000-000000000002",
            preparation_plans=["I will walk"],
            updates=[
                {
                    "key": "arrival_support",
                    "value": "needs_clarification",
                    "scope": "visit",
                    "quote": "Yes, I will walk",
                }
            ],
        )


def test_language_change_with_question_answers_new_task(simulated_runtime):
    from pydantic import SecretStr
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentRun, SimulatedMessage

    runtime, tools, source, _ = simulated_runtime
    note = "Please arrange for an adult to accompany you home."
    body = episode_body(source)
    body["doctor_note"] = note
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    runtime[2].multilingual_enabled = True
    runtime[2].agent_model_mode = "anthropic"
    runtime[2].anthropic_api_key = SecretStr("test-key")
    with runtime[0].begin() as db:
        db.scalar(select(AgentRun).where(AgentRun.case_id == case)).mode = "anthropic"
    event(
        runtime[1], case, "demo_reply", "Please use Tamil. Do I need someone to accompany me?"
    ).raise_for_status()

    class MixedModel(QuestionModel):
        def decide(self, obs, **kwargs):
            value = json.loads(super().decide(obs, **kwargs).text)
            if value["step_type"] == "REVIEW_NEEDS":
                value["updates"] = [
                    {
                        "key": "preferred_language",
                        "value": "ta",
                        "scope": "future",
                        "quote": "Please use Tamil",
                    }
                ]
                value["question"] = "Which language do you prefer?"
            return ModelReply(json.dumps(value))

    drain(runtime, tools=tools, model=MixedModel("ANSWERED", note, intent="UNSPECIFIED"))
    result = view(runtime[1], case)
    assert not result["handoff"]
    with runtime[0]() as db:
        row = db.scalar(select(SimulatedMessage).where(SimulatedMessage.kind == "question_answer"))
        assert note in row.body
        assert "Which language" not in row.body
        assert row.translation == {"language": "ta", "status": "pending"}
