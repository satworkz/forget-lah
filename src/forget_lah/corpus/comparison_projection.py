"""Deterministic, language-neutral projection of one corpus item.

Input: a single item conforming to ``corpus/schema/corpus.schema.json``. The projection keeps only
the graded comparison surface — intent, per-question meaning and disposition, task types,
instruction checks, memory effects, translation and delivery gates, and the single terminal
expectation — and discards incidental identifiers, timestamps and free prose. Observed runs must be
normalised into this same shape before cross-language comparison.

Memory semantics: a key absent from a checkpoint means *no change*; the runtime operation ``remove``
is the delete behind the programme PRD's loose word "clear". There is no runtime "unknown" write, so
an oracle-unknown is an annotation rather than a projected memory update. A mere language switch must
not be projected as a lasting preference unless the item authors such an update.

This module is pure (stdlib only, no I/O). Bump ``PROJECTION_VERSION`` whenever the output shape
changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PROJECTION_VERSION: str = "1"

#: Memory keys whose VALUE is a locale-specific expectation and must survive normalisation.
_LANGUAGE_MEMORY_KEYS = frozenset({"preferred_language", "excluded_languages"})

#: Projection paths that a harness may legitimately allow to differ across aligned language variants.
LANGUAGE_DEPENDENT_PATHS: frozenset[str] = frozenset(
    {
        "identity.language",
        "checkpoints[].delivery.effective_language",
        "checkpoints[].memory[].value",
    }
)

#: Scalar terminal fields carried through verbatim when the item authors them.
_TERMINAL_SCALARS = (
    "kind",
    "run_status",
    "outcome",
    "wait_reason",
    "failure_code",
    "intent",
    "intended",
    "handoff_reason",
    "handoff_reason_code",
    "handoff_accepted",
    "callback_requested",
)


def _project_attendance(qualification: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if qualification is None:
        return None
    return {"status": qualification.get("status")}


def _project_task(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "index": task.get("index"),
        "task_type": task.get("task_type"),
        "outcome": task.get("outcome"),
        "instruction_id": task.get("instruction_id"),
        "relation": task.get("relation"),
        "practical_issue": task.get("practical_issue"),
        "dependency": task.get("dependency"),
        "actions": sorted(task.get("actions") or []),
    }


def _project_instruction_check(check: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "question_message_id": check.get("question_message_id"),
        "outcome": check.get("outcome"),
    }


def _project_memory(entry: Mapping[str, Any]) -> dict[str, Any]:
    key = entry.get("key")
    return {
        "key": key,
        "operation": entry.get("operation"),
        "scope": entry.get("scope"),
        "expected_status": entry.get("expected_status"),
        "value": entry.get("value") if key in _LANGUAGE_MEMORY_KEYS else None,
    }


def _project_delivery(delivery: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "expected_block": delivery.get("expected_block"),
        "effective_language": delivery.get("effective_language"),
        "expected_message_delivery": [
            {"turn_id": item.get("turn_id"), "delivery_status": item.get("delivery_status")}
            for item in delivery.get("expected_message_delivery") or []
        ],
    }


def _project_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "after_turn_id": checkpoint.get("after_turn_id"),
        "appointment_intent": checkpoint.get("appointment_intent"),
        "attendance_qualification": _project_attendance(checkpoint.get("attendance_qualification")),
        "tasks": [_project_task(task) for task in checkpoint.get("tasks") or []],
        "instruction_checks": [
            _project_instruction_check(check)
            for check in checkpoint.get("instruction_checks") or []
        ],
        "memory": [_project_memory(entry) for entry in checkpoint.get("memory") or []],
        "callback_requested": checkpoint.get("callback_requested"),
        "wait_reason": checkpoint.get("wait_reason"),
        "delivery": _project_delivery(checkpoint.get("delivery") or {}),
    }


def _project_terminal(terminal: Mapping[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {key: terminal[key] for key in _TERMINAL_SCALARS if key in terminal}
    evidence = terminal.get("handoff_evidence")
    if isinstance(evidence, Mapping):
        # Keep only which evidence fields are asserted; the identifier VALUES are incidental.
        projected["handoff_evidence"] = sorted(evidence.keys())
    return projected


def project(item: Mapping[str, Any]) -> dict[str, Any]:
    """Project one schema-conformant corpus item into the canonical comparison view."""
    identity = item.get("identity") or {}
    environment = item.get("environment") or {}
    return {
        "projection_version": PROJECTION_VERSION,
        "identity": {
            "family_id": identity.get("family_id"),
            "variant_id": identity.get("variant_id"),
            "scenario_id": identity.get("scenario_id"),
            "language": identity.get("language"),
            "primary_stratum": identity.get("primary_stratum"),
            "tags": sorted(identity.get("tags") or []),
        },
        "checkpoints": [
            _project_checkpoint(checkpoint) for checkpoint in item.get("checkpoint_oracle") or []
        ],
        "terminal": _project_terminal(item.get("terminal_oracle") or {}),
        "translation": {
            "translation_configured": environment.get("translation_configured"),
            "delivery_evidence_source": environment.get("delivery_evidence_source"),
        },
    }
