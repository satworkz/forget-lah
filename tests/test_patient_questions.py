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
    def __init__(self, outcome, quote=None, intent="CONFIRM"):
        super().__init__([], intent=intent)
        self.outcome, self.quote = outcome, quote

    def decide(self, obs, **kwargs):
        value = json.loads(super().decide(obs, **kwargs).text)
        if value["step_type"] == "REVIEW_NEEDS":
            value["patient_questions"] = ["Do I need someone to accompany me?"]
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
            value["question_answers"] = [
                dict(
                    question_index=0,
                    outcome=self.outcome,
                    instruction_id=note["instruction_id"] if self.quote else None,
                    quote=self.quote,
                )
            ]
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
