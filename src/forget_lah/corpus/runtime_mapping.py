"""Map runtime run evidence into the corpus observation shape.

The runtime does not store the schema's `tasks` array. It stores parallel lists — `patient_questions`
(strings) and `patient_task_types` (`QUESTION`/`PLAN`) — plus `question_answers`, a list of
`QuestionAnswer.model_dump()` records keyed by `question_index` (`contracts.py:86`, written at
`engine.py:1604`). This module performs that join, and packages a run's checkpoint, terminal and
delivery evidence into the item-shaped mapping that `forget_lah.corpus.replay.grade` consumes.

It is deliberately pure and explicit: callers supply the terminal expectation (built from the run
status and any staff handoff), the memory updates (which live on the decision, not the checkpoint),
instruction-check resolutions and per-message delivery evidence. Nothing is invented when a runtime
field is absent — the value is `None` so grading reports the difference.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

OBSERVATION_VERSION = "1"


def _callback_requested(checkpoint: Mapping[str, Any]) -> bool | None:
    """The runtime records a callback under `callback` (`engine.py:2153`); accept both spellings."""
    if "callback_requested" in checkpoint:
        return checkpoint.get("callback_requested")
    if "callback" in checkpoint:
        return bool(checkpoint.get("callback"))
    return None


def build_memory(updates: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Map `MemoryChange` records to schema memory entries, deriving `expected_status`.

    The status rule mirrors the runtime's own persistence (`memory.py:87-91`): `remove` retracts;
    `arrival_support`/`other_concern` or value `"und"` is pending; otherwise active.
    """
    entries: list[dict[str, Any]] = []
    for update in updates or []:
        key = update.get("key")
        operation = update.get("operation", "set")
        value = update.get("value")
        if operation == "remove":
            status = "retracted"
        elif key in {"arrival_support", "other_concern"} or value == "und":
            status = "pending"
        else:
            status = "active"
        entries.append(
            {
                "key": key,
                "operation": operation,
                "scope": update.get("scope"),
                "expected_status": status,
                "value": value,
            }
        )
    return entries


def build_delivery(
    step_payloads: Sequence[Mapping[str, Any]] | None,
    turn_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Map observed `displayed_in_simulator` deliveries onto the corpus replay turns, in order."""
    observed = []
    for step in step_payloads or []:
        result = step.get("tool_result") or {}
        data = result.get("data") or {}
        status = data.get("delivery_status")
        if status:
            observed.append(status)
    return [
        {"turn_id": turn_id, "delivery_status": status}
        for turn_id, status in zip(turn_ids, observed, strict=False)
    ]


def build_tasks(checkpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Join `patient_questions`/`patient_task_types` with `question_answers` into task rows."""
    questions = list(checkpoint.get("patient_questions") or [])
    task_types = list(checkpoint.get("patient_task_types") or [])
    answers = {
        answer.get("question_index"): answer
        for answer in (checkpoint.get("question_answers") or [])
        if isinstance(answer, Mapping)
    }
    total = max(len(questions), len(task_types))
    tasks: list[dict[str, Any]] = []
    for index in range(total):
        answer = answers.get(index) or {}
        tasks.append(
            {
                "index": index,
                "task_type": task_types[index] if index < len(task_types) else "QUESTION",
                "outcome": answer.get("outcome"),
                "instruction_id": answer.get("instruction_id"),
                "quote": answer.get("quote"),
                "relation": answer.get("relation"),
                "practical_issue": answer.get("practical_issue"),
                "dependency": answer.get("dependency"),
                "actions": list(answer.get("actions") or []),
            }
        )
    return tasks


def observation_from_runtime(
    variant: Mapping[str, Any],
    *,
    checkpoint: Mapping[str, Any],
    terminal: Mapping[str, Any],
    after_turn_id: str = "t2",
    memory_updates: Sequence[Mapping[str, Any]] | None = None,
    instruction_checks: Sequence[Mapping[str, Any]] | None = None,
    delivery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an item-shaped observation from one run's evidence."""
    identity = variant.get("identity") or {}
    environment = variant.get("environment") or {}
    language = identity.get("language")
    resolved_delivery = dict(delivery or {})
    resolved_delivery.setdefault("expected_block", checkpoint.get("delivery_block"))
    resolved_delivery.setdefault("effective_language", language)
    resolved_delivery.setdefault("expected_message_delivery", [])

    return {
        "observation_version": OBSERVATION_VERSION,
        "identity": {
            "family_id": identity.get("family_id"),
            "variant_id": identity.get("variant_id"),
            "scenario_id": identity.get("scenario_id"),
            "language": language,
            "primary_stratum": identity.get("primary_stratum"),
            "tags": list(identity.get("tags") or []),
        },
        "environment": {
            "translation_configured": environment.get("translation_configured"),
            "delivery_evidence_source": environment.get("delivery_evidence_source"),
        },
        "checkpoint_oracle": [
            {
                "after_turn_id": after_turn_id,
                "appointment_intent": checkpoint.get("appointment_intent") or "UNSPECIFIED",
                "attendance_qualification": (
                    {"status": checkpoint["attendance_qualification"]}
                    if isinstance(checkpoint.get("attendance_qualification"), str)
                    else checkpoint.get("attendance_qualification")
                ),
                "tasks": build_tasks(checkpoint),
                "instruction_checks": [dict(entry) for entry in (instruction_checks or [])],
                "memory": [dict(entry) for entry in (memory_updates or [])],
                "callback_requested": _callback_requested(checkpoint),
                "wait_reason": checkpoint.get("wait_reason"),
                "delivery": resolved_delivery,
            }
        ],
        "terminal_oracle": dict(terminal),
        "scoring": dict(variant.get("scoring") or {}),
    }
