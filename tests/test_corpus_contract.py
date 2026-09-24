"""Contract tests for the M1 corpus schema.

Every check is grounded in `corpus/schema/corpus.schema.json` and the semantics recorded in
`docs/corpus/m1/runtime_semantics_map.md`. `x-cross-field-rules` are prose, so they are enforced here
in Python. Rule ids `R<n>` match the rule order in the schema.

Three rules are **not machine-enforceable** from a single item and are therefore documented rather
than asserted:

- **R10** (`UNSUPPORTED` only for a non-clinical operational fact) needs a clinical/operational
  classification of the question, which is an oracle judgment, not an item field.
- **R27** (an *unexpected* escalation is a failure) is a property of a run's observed outcome against
  the authored terminal, not of the authored item.
- **R34** (failure classification of translation results) constrains the execution-result contract,
  which this item schema does not carry.

They are covered by review (`oracle_rubric.md`) and will be enforceable once the result contract and
grading harness exist.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from forget_lah.corpus.comparison_projection import LANGUAGE_DEPENDENT_PATHS, project

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "corpus" / "schema" / "corpus.schema.json").read_text())
FIXTURES = ROOT / "tests" / "fixtures" / "corpus_m1"
DEMO_CLINIC_ID = "10000000-0000-4000-8000-000000000001"
SGT = timezone(timedelta(hours=8))
ANTHROPIC_MARKERS = ("anthropic", "claude")

_VALIDATOR = Draft202012Validator(SCHEMA)
Draft202012Validator.check_schema(SCHEMA)

POSITIVE_FIXTURES = [
    "positive_confirmation_handoff_en.json",
    "positive_questions_escalated_en.json",
    "positive_questions_escalated_zh.json",
    "positive_wrong_number_unscored_en.json",
]


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def schema_errors(item: dict[str, Any]) -> list[str]:
    return [f"schema: {error.message}" for error in _VALIDATOR.iter_errors(item)]


def _is_anthropic(family: Any) -> bool:
    return isinstance(family, str) and any(marker in family.lower() for marker in ANTHROPIC_MARKERS)


def _approved_texts(item: dict[str, Any]) -> dict[str, str]:
    instructions = item["environment"]["fixtures"].get("approved_instructions", [])
    return {entry["instruction_id"]: entry["approved_text"] for entry in instructions}


def _staff_acceptance(item: dict[str, Any]) -> list[dict[str, Any]]:
    return item["environment"]["fixtures"].get("staff_acceptance", []) or []


def rule_errors(item: dict[str, Any]) -> list[str]:
    """Return `R<n>`-prefixed violations of the schema's cross-field rules."""
    errors: list[str] = []
    terminal = item.get("terminal_oracle") or {}
    environment = item.get("environment") or {}
    profile = environment.get("translation_profile") or {}
    identity = item.get("identity") or {}
    approved = _approved_texts(item)

    for checkpoint in item.get("checkpoint_oracle") or []:
        intent = checkpoint.get("appointment_intent")
        tasks = checkpoint.get("tasks") or []
        indexes = [task.get("index") for task in tasks]
        if indexes != list(range(len(tasks))):
            errors.append(f"R1: task indexes {indexes} are not exactly 0..{len(tasks) - 1}")

        task_types = [task.get("task_type") for task in tasks]
        if task_types != sorted(task_types, key=lambda value: 0 if value == "QUESTION" else 1):
            errors.append(f"R2: tasks are not ordered all QUESTIONs then all PLANs: {task_types}")

        for task in tasks:
            outcome = task.get("outcome")
            task_type = task.get("task_type")
            if task_type == "PLAN" and outcome not in {"GUIDANCE", "NOT_REQUIRED"}:
                errors.append(f"R3: PLAN task carries outcome {outcome!r}")
            if outcome in {"GUIDANCE", "NOT_REQUIRED"} and task_type != "PLAN":
                errors.append(f"R3: outcome {outcome!r} requires task_type PLAN, got {task_type!r}")

            if outcome in {"ANSWERED", "GUIDANCE"}:
                instruction_id = task.get("instruction_id")
                quote = task.get("quote")
                if not instruction_id or not quote:
                    errors.append(f"R4: {outcome} task lacks instruction_id/quote")
                elif quote not in approved.get(instruction_id, ""):
                    errors.append(
                        f"R4: quote not a substring of approved_text for {instruction_id!r}"
                    )
            else:
                carried = [key for key in _EVIDENCE_FIELDS if task.get(key) is not None]
                if task.get("actions"):
                    carried.append("actions")
                if carried:
                    errors.append(f"R5: outcome {outcome!r} carries evidence fields {carried}")

            if outcome == "GUIDANCE" and not (
                task.get("practical_issue") and task.get("dependency")
            ):
                errors.append("R6: GUIDANCE requires practical_issue and dependency")

            actions = task.get("actions") or []
            if task.get("relation") == "CONFLICTS" and "FOLLOW_CLINIC_INSTRUCTION" not in actions:
                errors.append("R7: relation CONFLICTS requires FOLLOW_CLINIC_INSTRUCTION")
            if task.get("relation") == "POSSIBLE_SUBSTITUTION" and not (
                {"CONTACT_CLINIC", "FOLLOW_CLINIC_INSTRUCTION"} & set(actions)
            ):
                errors.append(
                    "R8: POSSIBLE_SUBSTITUTION requires CONTACT_CLINIC/FOLLOW_CLINIC_INSTRUCTION"
                )
            if "OFFER_RESCHEDULE" in actions and intent not in {"CONFIRM", "CHANGE"}:
                errors.append(
                    f"R9: OFFER_RESCHEDULE requires intent CONFIRM/CHANGE, got {intent!r}"
                )

        if intent not in (None, "UNSPECIFIED") and not checkpoint.get("appointment_request_quote"):
            errors.append(f"R11: intent {intent!r} requires appointment_request_quote")
        if checkpoint.get("attendance_qualification") is not None and intent != "CONFIRM":
            errors.append("R12: attendance_qualification is valid only when intent is CONFIRM")

        memory = checkpoint.get("memory") or []
        keys = [entry.get("key") for entry in memory]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            errors.append(f"R13: more than one memory entry per key: {duplicates}")
        for entry in memory:
            if entry.get("key") == "contact_permission" and entry.get("operation") == "remove":
                errors.append("R14: contact_permission cannot be removed")
            if entry.get("operation") == "remove" and entry.get("expected_status") != "retracted":
                errors.append("R15: memory remove must have expected_status retracted")
            if entry.get("operation") == "set" and entry.get("expected_status") == "retracted":
                errors.append("R15: memory set must not have expected_status retracted")

        wait_reason = checkpoint.get("wait_reason")
        if wait_reason and terminal.get("run_status") != "waiting":
            errors.append(f"R16: checkpoint wait_reason {wait_reason!r} without a waiting terminal")
        if terminal.get("run_status") == "completed" and wait_reason:
            errors.append("R16: a completed run must not set wait_reason")

        if any(task.get("outcome") == "CLINIC_REVIEW" for task in tasks) and not (
            checkpoint.get("callback_requested") or terminal.get("kind") == "escalated"
        ):
            errors.append(
                "R17: CLINIC_REVIEW requires callback_requested true or an escalated terminal"
            )

    stratum = identity.get("primary_stratum")
    scoring = item.get("scoring") or {}
    quarantined = {
        "wrong_number": "wrong_number_path_absent",
        "third_party_reply": "third_party_path_absent",
    }
    if stratum in quarantined:
        expected_reason = quarantined[stratum]
        if scoring.get("scored") is not False or scoring.get("unscored_reason") != expected_reason:
            errors.append(
                f"R18: {stratum} requires scored false with unscored_reason {expected_reason!r}"
            )

    if scoring.get("scored") is False and scoring.get("unscored_reason") is None:
        errors.append("R35: an unscored item must state its unscored_reason")

    clock = item.get("clock") or {}
    if clock.get("reference_datetime") and clock.get("frozen_date"):
        local_date = (
            datetime.fromisoformat(clock["reference_datetime"]).astimezone(SGT).date().isoformat()
        )
        if local_date != clock["frozen_date"]:
            errors.append(
                f"R19: frozen_date {clock['frozen_date']!r} is not the SGT date {local_date!r}"
            )

    if (
        environment.get("is_demo_clinic") is not True
        or environment.get("clinic_id") != DEMO_CLINIC_ID
    ):
        errors.append(
            "R20: is_demo_clinic must be true and clinic_id must be the runtime DEMO_CLINIC_ID"
        )

    governance = item.get("governance") or {}
    authorship_family = (governance.get("authorship") or {}).get("drafter_family")
    back_family = (governance.get("back_translation") or {}).get("model_family")
    if back_family == authorship_family:
        errors.append("R21: back-translation family must differ from the drafter family")
    if _is_anthropic(authorship_family) or _is_anthropic(back_family):
        errors.append("R21: neither the drafter nor the back-translator may be an Anthropic family")
    for declaration in governance.get("ai_declarations") or []:
        if _is_anthropic(declaration.get("model_family")):
            errors.append("R22: an Anthropic family may not appear in ai_declarations")

    if terminal.get("kind") == "completed_handoff":
        accepted = {entry.get("handoff_id"): entry for entry in _staff_acceptance(item)}.get(
            terminal.get("handoff_id")
        )
        if not accepted or not accepted.get("accepted_by") or not accepted.get("accepted_at"):
            errors.append(
                "R23: completed_handoff requires a matching accepted staff_acceptance record"
            )
    if terminal.get("kind") == "waiting" and terminal.get("intended") is not True:
        errors.append("R24: a waiting terminal is valid only when intended is true")

    if terminal.get("kind") == "escalated":
        evidence = terminal.get("handoff_evidence") or {}
        if terminal.get("run_status") != "escalated" or terminal.get("outcome") is not None:
            errors.append("R25: escalated requires run_status escalated and outcome null")
        if (
            terminal.get("handoff_accepted") is not False
            or terminal.get("callback_requested") is not True
        ):
            errors.append(
                "R25: escalated requires handoff_accepted false and callback_requested true"
            )
        for field in ("handoff_id", "clinic_id", "case_id", "run_id"):
            if not evidence.get(field):
                errors.append(f"R25: escalated handoff_evidence requires {field}")
        if evidence.get("accepted_by") is not None or evidence.get("accepted_at") is not None:
            errors.append("R25: unaccepted handoff requires null accepted_by/accepted_at")
        reviews = [
            task.get("outcome")
            for checkpoint in item.get("checkpoint_oracle") or []
            for task in checkpoint.get("tasks") or []
        ]
        if "CLINIC_REVIEW" not in reviews:
            errors.append("R26: escalated requires at least one CLINIC_REVIEW task")
        if evidence.get("handoff_id") in {
            entry.get("handoff_id") for entry in _staff_acceptance(item)
        }:
            errors.append("R26: an escalated handoff must not have a staff_acceptance record")

    if terminal.get("kind") == "failure" and terminal.get("failure_code") in {
        "STEP_BUDGET_EXHAUSTED",
        "ROLE_BUDGET_EXHAUSTED",
    }:
        errors.append("R29: step/role budget exhaustion is always a failure and is never authored")

    if profile:
        if profile.get("sample_count") != 60 or profile.get("required_passes") != 60:
            errors.append(
                "R30: every scored variant requires sample_count 60 and required_passes 60"
            )
        derived = bool(
            profile.get("multilingual_enabled")
            and profile.get("agent_model_mode") == "anthropic"
            and profile.get("model_configured")
        )
        if profile.get("translation_configured") is not derived:
            errors.append(
                "R31: translation_profile.translation_configured is not the derived value"
            )
        if profile.get("translation_configured") != environment.get("translation_configured"):
            errors.append(
                "R31: translation_profile and environment translation_configured disagree"
            )
        if profile.get("temperature") != 0 or profile.get("provider_seed") is not None:
            errors.append("R32: temperature must be 0 and provider_seed must be null")
        if profile.get("seed_supported") is not False:
            errors.append("R32: seed_supported must be false for the current translator")
        retry = profile.get("retry_policy") or {}
        if retry.get("infrastructure_max_replacements") != 2:
            errors.append("R33: infrastructure replacements are capped at 2")
        if "TRANSLATION_VALIDATION_FAILED" not in (retry.get("never_replace_on") or []):
            errors.append("R33: TRANSLATION_VALIDATION_FAILED must never be replaced")
        if profile.get("execution_origin") not in {"live", "replay"}:
            errors.append("R36: execution_origin must distinguish live from replay")

    return errors


_EVIDENCE_FIELDS = ("instruction_id", "quote", "relation", "practical_issue", "dependency")


def violations(item: dict[str, Any]) -> list[str]:
    return schema_errors(item) + rule_errors(item)


# --- cross-item rules -------------------------------------------------------------------------

_IGNORED_FOR_ALIGNMENT = LANGUAGE_DEPENDENT_PATHS | {"identity.variant_id"}


def _drop_path(node: dict[str, Any], path: str) -> None:
    """Remove a dotted projection path, expanding `[]` array segments."""
    head, _, tail = path.partition(".")
    if head.endswith("[]"):
        children = node.get(head[:-2]) or []
        if tail:
            for child in children:
                if isinstance(child, dict):
                    _drop_path(child, tail)
    elif tail:
        child = node.get(head)
        if isinstance(child, dict):
            _drop_path(child, tail)
    else:
        node.pop(head, None)


def family_alignment_errors(items: list[dict[str, Any]]) -> list[str]:
    """R37: aligned members share family_id, meaning and fixtures; differ only by language/wording."""
    errors: list[str] = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_family.setdefault(item["identity"]["family_id"], []).append(item)
    for family_id, members in by_family.items():
        if len(members) < 2:
            continue
        normalized = []
        for member in members:
            data = copy.deepcopy(project(member))
            for path in _IGNORED_FOR_ALIGNMENT:
                _drop_path(data, path)
            normalized.append(data)
        for other in normalized[1:]:
            if other != normalized[0]:
                errors.append(f"R37: family {family_id} members differ beyond language and wording")
                break
        languages = {member["identity"]["language"] for member in members}
        if len(languages) != len(members):
            errors.append(f"R37: family {family_id} repeats a language: {sorted(languages)}")
    return errors


def questions_escalation_quota_errors(items: list[dict[str, Any]]) -> list[str]:
    """R28: per language, at least two of six evaluation questions families are escalated."""
    errors: list[str] = []
    families: dict[tuple[str, str], str] = {}
    for item in items:
        identity = item["identity"]
        if item.get("split") != "evaluation" or identity["primary_stratum"] != "questions":
            continue
        key = (identity["language"], identity["family_id"])
        families[key] = (item.get("terminal_oracle") or {}).get("kind")
    for language in {language for language, _ in families}:
        in_language = {key: kind for key, kind in families.items() if key[0] == language}
        if len(in_language) != 6:
            errors.append(
                f"R28: language {language} has {len(in_language)} evaluation questions families, need 6"
            )
        escalated = sum(1 for kind in in_language.values() if kind == "escalated")
        if escalated < 2:
            errors.append(
                f"R28: language {language} has {escalated} escalated evaluation families, need 2"
            )
    return errors


# --- positive fixtures ------------------------------------------------------------------------


@pytest.mark.parametrize("name", POSITIVE_FIXTURES)
def test_positive_fixture_passes_schema_and_rules(name: str) -> None:
    assert violations(load_fixture(name)) == []


def test_aligned_questions_family_is_consistent() -> None:
    family = [
        load_fixture("positive_questions_escalated_en.json"),
        load_fixture("positive_questions_escalated_zh.json"),
    ]
    assert family_alignment_errors(family) == []


# --- schema negatives -------------------------------------------------------------------------


def test_schema_rejects_a_second_terminal_expectation() -> None:
    item = load_fixture("positive_questions_escalated_en.json")
    item["terminal_oracle"]["alternatives"] = [{"kind": "waiting"}]
    assert any(error.startswith("schema:") for error in schema_errors(item))


def test_schema_rejects_a_missing_required_field() -> None:
    item = load_fixture("positive_questions_escalated_en.json")
    del item["environment"]["translation_profile"]["sample_count"]
    assert any(error.startswith("schema:") for error in schema_errors(item))


def test_schema_rejects_an_unknown_enum() -> None:
    item = load_fixture("positive_questions_escalated_en.json")
    item["checkpoint_oracle"][0]["tasks"][0]["outcome"] = "MAYBE"
    assert any(error.startswith("schema:") for error in schema_errors(item))


def test_r18_rejects_a_scored_quarantined_stratum() -> None:
    item = load_fixture("positive_wrong_number_unscored_en.json")
    item["scoring"] = {"scored": True, "unscored_reason": None}
    assert any(error.startswith("R18:") for error in violations(item))


# --- rule negatives ---------------------------------------------------------------------------


def _escalated() -> dict[str, Any]:
    return load_fixture("positive_questions_escalated_en.json")


def _handoff() -> dict[str, Any]:
    return load_fixture("positive_confirmation_handoff_en.json")


def test_r1_rejects_task_index_gaps() -> None:
    item = _escalated()
    item["checkpoint_oracle"][0]["tasks"][0]["index"] = 1
    assert any(error.startswith("R1:") for error in rule_errors(item))


def test_r2_rejects_plan_before_question() -> None:
    item = _escalated()
    item["checkpoint_oracle"][0]["tasks"].insert(
        0, {"index": 0, "task_type": "PLAN", "outcome": "NOT_REQUIRED"}
    )
    item["checkpoint_oracle"][0]["tasks"][1]["index"] = 1
    assert any(error.startswith("R2:") for error in rule_errors(item))


def test_r4_rejects_missing_source_evidence() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0]["tasks"][0].pop("instruction_id")
    assert any(error.startswith("R4:") for error in rule_errors(item))


def test_r4_rejects_a_quote_not_in_the_approved_text() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0]["tasks"][0]["quote"] = "fabricated source text"
    assert any(error.startswith("R4:") for error in rule_errors(item))


def test_r5_rejects_a_clinic_review_carrying_a_source_quote() -> None:
    item = _escalated()
    item["checkpoint_oracle"][0]["tasks"][0]["quote"] = "some quote"
    assert any(error.startswith("R5:") for error in rule_errors(item))


def test_r11_rejects_intent_without_a_request_quote() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0].pop("appointment_request_quote")
    assert any(error.startswith("R11:") for error in rule_errors(item))


def test_r12_rejects_attendance_qualification_without_confirm() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0]["appointment_intent"] = "CHANGE"
    item["checkpoint_oracle"][0]["appointment_request_quote"] = "move it"
    assert any(error.startswith("R12:") for error in rule_errors(item))


def test_r13_rejects_duplicate_memory_keys() -> None:
    item = _handoff()
    entry = item["checkpoint_oracle"][0]["memory"][0]
    item["checkpoint_oracle"][0]["memory"].append(copy.deepcopy(entry))
    assert any(error.startswith("R13:") for error in rule_errors(item))


def test_r14_rejects_contact_permission_removal() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0]["memory"] = [
        {
            "key": "contact_permission",
            "operation": "remove",
            "scope": "future",
            "expected_status": "retracted",
        }
    ]
    assert any(error.startswith("R14:") for error in rule_errors(item))


def test_r15_rejects_remove_without_retracted_status() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0]["memory"][0] = {
        "key": "excluded_weekdays",
        "operation": "remove",
        "scope": "visit",
        "expected_status": "active",
    }
    assert any(error.startswith("R15:") for error in rule_errors(item))


def test_r16_rejects_a_completed_run_that_waits() -> None:
    item = _handoff()
    item["checkpoint_oracle"][0]["wait_reason"] = "AWAITING_PATIENT_REPLY"
    assert any(error.startswith("R16:") for error in rule_errors(item))


def test_r17_rejects_clinic_review_without_callback() -> None:
    item = _escalated()
    item["checkpoint_oracle"][0]["callback_requested"] = False
    item["terminal_oracle"] = {
        "kind": "waiting",
        "run_status": "waiting",
        "wait_reason": "AWAITING_PATIENT_REPLY",
        "intended": True,
    }
    assert any(error.startswith("R17:") for error in rule_errors(item))


def test_r19_rejects_a_frozen_date_that_is_not_the_sgt_date() -> None:
    item = _escalated()
    item["clock"]["frozen_date"] = "2026-09-25"
    assert any(error.startswith("R19:") for error in rule_errors(item))


def test_r20_rejects_a_non_demo_clinic() -> None:
    item = _escalated()
    item["environment"]["clinic_id"] = "00000000-0000-4000-8000-000000000999"
    assert any(error.startswith("R20:") for error in rule_errors(item))


def test_r21_rejects_a_shared_back_translation_family() -> None:
    item = _escalated()
    item["governance"]["back_translation"]["model_family"] = "family-a"
    assert any(error.startswith("R21:") for error in rule_errors(item))


def test_r22_rejects_an_anthropic_ai_declaration() -> None:
    item = _escalated()
    item["governance"]["ai_declarations"][0]["model_family"] = "anthropic-claude"
    assert any(error.startswith("R22:") for error in rule_errors(item))


def test_r23_rejects_a_handoff_without_named_acceptance() -> None:
    item = _handoff()
    item["environment"]["fixtures"]["staff_acceptance"][0]["accepted_by"] = ""
    assert any(error.startswith("R23:") for error in rule_errors(item))


def test_r24_rejects_an_unintended_wait() -> None:
    item = _escalated()
    item["terminal_oracle"] = {
        "kind": "waiting",
        "run_status": "waiting",
        "wait_reason": "AWAITING_PATIENT_REPLY",
        "intended": False,
    }
    assert any(error.startswith("R24:") for error in rule_errors(item))


def test_r25_rejects_accepted_escalation_evidence() -> None:
    item = _escalated()
    item["terminal_oracle"]["handoff_evidence"]["accepted_by"] = "staff-1"
    assert any(error.startswith("R25:") for error in rule_errors(item))


def test_r26_rejects_escalation_without_a_clinic_review_task() -> None:
    item = _escalated()
    item["checkpoint_oracle"][0]["tasks"] = []
    assert any(error.startswith("R26:") for error in rule_errors(item))


def test_r28_requires_two_escalated_evaluation_families_per_language() -> None:
    items = []
    for language in ("en",):
        for index in range(6):
            items.append(
                {
                    "split": "evaluation",
                    "identity": {
                        "language": language,
                        "primary_stratum": "questions",
                        "family_id": f"fam-{index}",
                    },
                    "terminal_oracle": {"kind": "escalated" if index < 2 else "waiting"},
                }
            )
    assert questions_escalation_quota_errors(items) == []
    items[1]["terminal_oracle"] = {"kind": "waiting"}
    assert any(error.startswith("R28:") for error in questions_escalation_quota_errors(items))


def test_r29_rejects_an_authored_budget_failure() -> None:
    item = _escalated()
    item["terminal_oracle"] = {
        "kind": "failure",
        "run_status": "paused",
        "failure_code": "STEP_BUDGET_EXHAUSTED",
    }
    assert any(error.startswith("R29:") for error in rule_errors(item))


def test_r30_rejects_a_short_sampling_plan() -> None:
    item = _escalated()
    item["environment"]["translation_profile"]["sample_count"] = 10
    assert any(error.startswith("R30:") for error in rule_errors(item))


def test_r31_rejects_an_independently_asserted_translation_gate() -> None:
    item = _escalated()
    item["environment"]["translation_profile"]["agent_model_mode"] = "mock"
    assert any(error.startswith("R31:") for error in rule_errors(item))


def test_r32_rejects_a_nonzero_temperature() -> None:
    item = _escalated()
    item["environment"]["translation_profile"]["temperature"] = 0.2
    assert any(error.startswith("R32:") for error in schema_errors(item) + rule_errors(item))


def test_r33_rejects_replacing_a_validation_failure() -> None:
    item = _escalated()
    retry = item["environment"]["translation_profile"]["retry_policy"]
    retry["never_replace_on"] = ["semantic_mismatch"]
    assert any(error.startswith("R33:") for error in rule_errors(item))


def test_r35_rejects_an_unscored_item_without_a_reason() -> None:
    item = _escalated()
    item["scoring"] = {"scored": False, "unscored_reason": None}
    assert any(error.startswith("R35:") for error in rule_errors(item))


def test_r37_rejects_a_family_that_differs_beyond_language() -> None:
    family = [
        load_fixture("positive_questions_escalated_en.json"),
        load_fixture("positive_questions_escalated_zh.json"),
    ]
    family[1]["checkpoint_oracle"][0]["tasks"][0]["outcome"] = "UNSUPPORTED"
    assert any(error.startswith("R37:") for error in family_alignment_errors(family))


# --- projection invariants --------------------------------------------------------------------


def test_projection_of_an_aligned_family_matches_after_declared_normalisation() -> None:
    family = [
        load_fixture("positive_questions_escalated_en.json"),
        load_fixture("positive_questions_escalated_zh.json"),
    ]
    projections = [project(member) for member in family]
    assert len(projections) == 2
    assert projections[0] != projections[1]  # language values genuinely differ
    for projection in projections:
        for path in _IGNORED_FOR_ALIGNMENT:
            _drop_path(projection, path)
    assert projections[0] == projections[1]


def test_projection_shape_is_versioned_and_serialisable() -> None:
    for name in POSITIVE_FIXTURES:
        rendered = json.dumps(project(load_fixture(name)))
        assert rendered


# --- M2 development pilot ---------------------------------------------------------------------

PILOT = ROOT / "corpus" / "development" / "pilot"
PILOT_LANGUAGES = {"en", "zh", "ms", "ta"}


def _pilot_items() -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text())
        for path in sorted(PILOT.glob("*.json"))
        if path.name != "manifest.json"
    ]


def test_development_pilot_items_pass_schema_and_all_rules() -> None:
    items = _pilot_items()
    assert items, "no pilot items found"
    for item in items:
        assert violations(item) == [], item["identity"]["variant_id"]


def test_development_pilot_families_are_aligned() -> None:
    assert family_alignment_errors(_pilot_items()) == []


def test_development_pilot_is_four_languages_per_family() -> None:
    families: dict[str, set[str]] = {}
    for item in _pilot_items():
        families.setdefault(item["identity"]["family_id"], set()).add(item["identity"]["language"])
    assert families, "no pilot families found"
    for family_id, languages in families.items():
        assert languages == PILOT_LANGUAGES, family_id


def test_development_pilot_manifest_matches_emitted_files() -> None:
    manifest = json.loads((PILOT / "manifest.json").read_text())
    items = _pilot_items()
    assert manifest["counts"]["variants"] == len(items)
    assert manifest["counts"]["families"] == len(manifest["families"])
    for family in manifest["families"].values():
        assert family["split"] == "development"
        for entry in family["variants"].values():
            text = (PILOT / entry["path"]).read_text()
            assert hashlib.sha256(text.encode()).hexdigest() == entry["sha256"]
