import json
from pathlib import Path

from forget_lah.corpus.replay import grade
from forget_lah.corpus.runtime_mapping import (
    OBSERVATION_VERSION,
    build_delivery,
    build_memory,
    build_tasks,
    observation_from_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "development" / "pilot"


def _variant(name: str) -> dict:
    return json.loads((PILOT / name).read_text())


def test_build_tasks_joins_questions_types_and_answers() -> None:
    checkpoint = {
        "patient_questions": ["what should I bring?", "can I bring my son?"],
        "patient_task_types": ["QUESTION", "PLAN"],
        "question_answers": [
            {
                "question_index": 0,
                "outcome": "ANSWERED",
                "instruction_id": "instr-prep",
                "quote": "bring your medication list",
                "actions": [],
            },
            {"question_index": 1, "outcome": "NOT_REQUIRED", "actions": []},
        ],
    }
    tasks = build_tasks(checkpoint)
    assert [task["task_type"] for task in tasks] == ["QUESTION", "PLAN"]
    assert tasks[0]["outcome"] == "ANSWERED"
    assert tasks[0]["instruction_id"] == "instr-prep"
    assert tasks[1]["outcome"] == "NOT_REQUIRED"
    assert tasks[1]["instruction_id"] is None
    assert [task["index"] for task in tasks] == [0, 1]


def test_build_tasks_leaves_absent_answers_none() -> None:
    checkpoint = {
        "patient_questions": ["a question with no answer"],
        "patient_task_types": ["QUESTION"],
        "question_answers": [],
    }
    tasks = build_tasks(checkpoint)
    assert tasks[0]["outcome"] is None
    assert tasks[0]["actions"] == []


def test_build_memory_derives_expected_status() -> None:
    entries = build_memory(
        [
            {"key": "preferred_language", "operation": "set", "scope": "future", "value": "en"},
            {
                "key": "excluded_weekdays",
                "operation": "remove",
                "scope": "visit",
                "value": "SATURDAY",
            },
            {"key": "other_concern", "operation": "set", "scope": "visit", "value": "noise"},
            {"key": "arrival_support", "operation": "set", "scope": "future", "value": "und"},
        ]
    )
    assert [entry["expected_status"] for entry in entries] == [
        "active",
        "retracted",
        "pending",
        "pending",
    ]
    assert entries[0]["value"] == "en"


def test_build_delivery_maps_observed_statuses_in_order() -> None:
    steps = [
        {"tool_result": {"data": {"delivery_status": "displayed_in_simulator"}}},
        {"tool_result": {"data": {}}},
        {"tool_result": {"data": {"delivery_status": "displayed_in_simulator"}}},
    ]
    assert build_delivery(steps, ["t2"]) == [
        {"turn_id": "t2", "delivery_status": "displayed_in_simulator"}
    ]
    assert build_delivery([], ["t2"]) == []


def test_observation_from_runtime_grades_a_matching_run_as_pass() -> None:
    variant = _variant("confirmation-01-en.json")
    observation = observation_from_runtime(
        variant,
        checkpoint={
            "appointment_intent": "CONFIRM",
            "attendance_qualification": {"status": "COMPATIBLE"},
            "patient_questions": ["when should I come for the preparation?"],
            "patient_task_types": ["QUESTION"],
            "question_answers": [
                {
                    "question_index": 0,
                    "outcome": "ANSWERED",
                    "instruction_id": "instr-prep",
                    "quote": "arrive ten minutes early",
                    "actions": [],
                }
            ],
            "callback_requested": False,
            "wait_reason": None,
        },
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
        },
        memory_updates=[
            {
                "key": "preferred_language",
                "operation": "set",
                "scope": "future",
                "expected_status": "active",
                "value": "en",
            }
        ],
        instruction_checks=[],
        delivery={
            "expected_block": None,
            "effective_language": "en",
            "expected_message_delivery": [
                {"turn_id": "t2", "delivery_status": "displayed_in_simulator"}
            ],
        },
    )
    assert observation["observation_version"] == OBSERVATION_VERSION
    result = grade(variant, observation)
    assert result["grade"] == "PASS", result["differences"]


def test_observation_missing_an_answer_fails_grading() -> None:
    variant = _variant("confirmation-01-en.json")
    observation = observation_from_runtime(
        variant,
        checkpoint={
            "appointment_intent": "CONFIRM",
            "attendance_qualification": {"status": "COMPATIBLE"},
            "patient_questions": ["when should I come for the preparation?"],
            "patient_task_types": ["QUESTION"],
            "question_answers": [],
            "callback_requested": False,
        },
        terminal={
            "kind": "completed_handoff",
            "run_status": "completed",
            "outcome": "OWNED_STAFF_HANDOFF",
        },
        memory_updates=[],
        delivery={
            "expected_block": None,
            "effective_language": "en",
            "expected_message_delivery": [
                {"turn_id": "t2", "delivery_status": "displayed_in_simulator"}
            ],
        },
    )
    result = grade(variant, observation)
    assert result["grade"] == "FAILED"
    assert result["differences"]


def test_observation_mapping_is_deterministic() -> None:
    variant = _variant("questions-01-zh.json")
    kwargs = {
        "checkpoint": {
            "appointment_intent": "UNSPECIFIED",
            "patient_questions": ["clinical medication question"],
            "patient_task_types": ["QUESTION"],
            "question_answers": [{"question_index": 0, "outcome": "CLINIC_REVIEW", "actions": []}],
            "callback_requested": True,
        },
        "terminal": {
            "kind": "escalated",
            "run_status": "escalated",
            "outcome": None,
            "handoff_reason": "unresolved clinical medication question",
            "handoff_reason_code": "CLINIC_REVIEW",
            "handoff_accepted": False,
            "callback_requested": True,
            "handoff_evidence": {
                "handoff_id": "hoff-questions-01",
                "clinic_id": "10000000-0000-4000-8000-000000000001",
                "case_id": "case-questions-01",
                "run_id": "run-questions-01",
                "accepted_by": None,
                "accepted_at": None,
            },
        },
        "delivery": {
            "expected_block": None,
            "effective_language": "zh",
            "expected_message_delivery": [
                {"turn_id": "t2", "delivery_status": "displayed_in_simulator"}
            ],
        },
    }
    first = observation_from_runtime(variant, **kwargs)
    second = observation_from_runtime(variant, **kwargs)
    assert first == second
