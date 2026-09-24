import copy
import json

from forget_lah.corpus.comparison_projection import (
    LANGUAGE_DEPENDENT_PATHS,
    PROJECTION_VERSION,
    project,
)


def _item() -> dict:
    """A schema-shaped item carrying prose, ids and timestamps that must not survive projection."""
    return {
        "corpus_version": "1",
        "identity": {
            "family_id": "fam-1",
            "variant_id": "var-zh",
            "scenario_id": "sc-1",
            "language": "zh",
            "primary_stratum": "questions",
            "tags": ["beta", "alpha"],
            "register_markers": ["singlish"],
        },
        "split": "evaluation",
        "clock": {
            "reference_datetime": "2026-09-24T09:00:00+08:00",
            "frozen_date": "2026-09-24",
            "per_turn_offset_minutes": [0, 5],
        },
        "environment": {
            "clinic_id": "demo",
            "is_demo_clinic": True,
            "patient_simulator_enabled": True,
            "translation_configured": True,
            "delivery_evidence_source": "displayed_in_simulator",
            "fixtures": {
                "source_api": [{"call": "x", "result": {}}],
                "approved_instructions": [
                    {"instruction_id": "i1", "approved_text": "APPROVED PROSE"}
                ],
            },
        },
        "runtime_bounds": {
            "agent_max_steps": 40,
            "role_limit_coordinator": 8,
            "role_limit_specialist": 6,
        },
        "initial_state": {
            "contact_permission": "allowed",
            "memory": [
                {"key": "preferred_language", "value": "zh", "scope": "future", "status": "active"}
            ],
        },
        "conversation": [
            {
                "turn_id": "t1",
                "origin": "history",
                "speaker": "patient",
                "body": "PATIENT PROSE",
                "language_tag": "zh",
            },
            {
                "turn_id": "t2",
                "origin": "replay",
                "speaker": "clinic",
                "clinic_turn_kind": "options",
                "body": "CLINIC PROSE",
                "language_tag": "zh",
            },
        ],
        "meaning_contract": {
            "intended_meaning_by_turn": [{"turn_id": "t1", "intended_meaning": "MEANING PROSE"}],
            "must_not_infer": ["MUST NOT PROSE"],
        },
        "checkpoint_oracle": [
            {
                "after_turn_id": "t2",
                "appointment_intent": "CONFIRM",
                "appointment_request_quote": "REQUEST QUOTE PROSE",
                "attendance_qualification": {"status": "COMPATIBLE", "quote": "AQ PROSE"},
                "tasks": [
                    {
                        "index": 0,
                        "task_type": "QUESTION",
                        "outcome": "ANSWERED",
                        "instruction_id": "i1",
                        "quote": "TASK QUOTE PROSE",
                        "relation": "RELEVANT",
                        "actions": ["OFFER_RESCHEDULE", "CONTACT_CLINIC"],
                    }
                ],
                "instruction_checks": [
                    {"question_message_id": "m1", "outcome": "MET", "answer_quote": "ANS PROSE"}
                ],
                "memory": [
                    {
                        "key": "preferred_language",
                        "operation": "set",
                        "scope": "future",
                        "value": "zh",
                        "expected_status": "active",
                    },
                    {
                        "key": "excluded_weekdays",
                        "operation": "set",
                        "scope": "visit",
                        "value": "MONDAY PROSE",
                        "expected_status": "active",
                    },
                ],
                "callback_requested": False,
                "wait_reason": None,
                "delivery": {
                    "expected_block": None,
                    "effective_language": "zh",
                    "expected_message_delivery": [
                        {"turn_id": "t2", "delivery_status": "displayed_in_simulator"}
                    ],
                },
            },
            {
                "after_turn_id": "t1",
                "appointment_intent": "UNSPECIFIED",
                "tasks": [],
                "memory": [],
                "delivery": {"expected_block": None},
            },
        ],
        "terminal_oracle": {
            "kind": "escalated",
            "run_status": "escalated",
            "outcome": None,
            "handoff_reason": "unresolved clinical question",
            "handoff_reason_code": "CLINIC_REVIEW",
            "handoff_accepted": False,
            "callback_requested": True,
            "handoff_evidence": {
                "handoff_id": "h1",
                "clinic_id": "demo",
                "case_id": "c1",
                "run_id": "r1",
                "accepted_by": None,
                "accepted_at": None,
            },
        },
        "scoring": {"scored": True, "unscored_reason": None},
        "governance": {
            "synthetic": True,
            "pii_free": True,
            "authorship": {"drafter": "D", "drafter_family": "F", "licence": "original_synthetic"},
            "review": {
                "reviewer_of_record": "HUMAN NAME",
                "reviewed_at": "2026-09-24T00:00:00+08:00",
            },
            "back_translation": {
                "model": "M",
                "model_family": "F2",
                "differs_from_drafter": True,
                "spot_check": {"by": "HUMAN NAME", "blind": True},
            },
            "ai_declarations": [{"step": "drafting", "model": "M", "model_family": "F"}],
        },
        "integrity": {"generation_seed": 1, "replay_seed": 2, "content_hash": "a" * 64},
    }


def _reverse_keys(value):
    """Rebuild a nested structure with reversed dict key order, to prove order-independence."""
    if isinstance(value, dict):
        return {key: _reverse_keys(value[key]) for key in reversed(list(value.keys()))}
    if isinstance(value, list):
        return [_reverse_keys(entry) for entry in value]
    return value


def test_projection_is_deterministic_and_key_order_independent():
    item = _item()
    assert project(item) == project(copy.deepcopy(item))
    assert project(item) == project(_reverse_keys(item))


def test_version_and_language_dependent_paths_are_declared():
    assert isinstance(PROJECTION_VERSION, str) and PROJECTION_VERSION
    assert isinstance(LANGUAGE_DEPENDENT_PATHS, frozenset)
    assert "identity.language" in LANGUAGE_DEPENDENT_PATHS
    assert "checkpoints[].delivery.effective_language" in LANGUAGE_DEPENDENT_PATHS
    assert "checkpoints[].memory[].value" in LANGUAGE_DEPENDENT_PATHS


def test_incidental_ids_timestamps_and_prose_are_dropped():
    rendered = json.dumps(project(_item()), ensure_ascii=False)
    for leaked in (
        "2026-09-24",
        "PATIENT PROSE",
        "CLINIC PROSE",
        "MEANING PROSE",
        "MUST NOT PROSE",
        "APPROVED PROSE",
        "REQUEST QUOTE PROSE",
        "AQ PROSE",
        "TASK QUOTE PROSE",
        "ANS PROSE",
        "MONDAY PROSE",
        "HUMAN NAME",
        "h1",
        "c1",
        "r1",
        "generation_seed",
        "reviewer_of_record",
    ):
        assert leaked not in rendered, leaked


def test_language_expectations_are_retained():
    result = project(_item())
    assert result["identity"]["language"] == "zh"
    memory = result["checkpoints"][0]["memory"]
    by_key = {entry["key"]: entry for entry in memory}
    assert by_key["preferred_language"]["value"] == "zh"
    assert by_key["excluded_weekdays"]["value"] is None
    assert result["checkpoints"][0]["delivery"]["effective_language"] == "zh"


def test_order_preserved_and_set_fields_sorted():
    result = project(_item())
    assert result["identity"]["tags"] == ["alpha", "beta"]
    assert result["checkpoints"][0]["tasks"][0]["actions"] == ["CONTACT_CLINIC", "OFFER_RESCHEDULE"]
    assert [cp["after_turn_id"] for cp in result["checkpoints"]] == ["t2", "t1"]


def test_terminal_variants_normalise_without_identifier_values():
    escalated = project(_item())["terminal"]
    assert escalated["kind"] == "escalated"
    assert escalated["outcome"] is None
    assert escalated["handoff_accepted"] is False
    assert escalated["callback_requested"] is True
    assert escalated["handoff_evidence"] == [
        "accepted_at",
        "accepted_by",
        "case_id",
        "clinic_id",
        "handoff_id",
        "run_id",
    ]

    handoff = _item()
    handoff["terminal_oracle"] = {
        "kind": "completed_handoff",
        "run_status": "completed",
        "outcome": "OWNED_STAFF_HANDOFF",
        "handoff_id": "h9",
    }
    terminal = project(handoff)["terminal"]
    assert terminal == {
        "kind": "completed_handoff",
        "run_status": "completed",
        "outcome": "OWNED_STAFF_HANDOFF",
    }

    failure = _item()
    failure["terminal_oracle"] = {
        "kind": "failure",
        "run_status": "paused",
        "failure_code": "STALE_CHECKPOINT",
    }
    assert project(failure)["terminal"]["failure_code"] == "STALE_CHECKPOINT"

    waiting = _item()
    waiting["terminal_oracle"] = {
        "kind": "waiting",
        "run_status": "waiting",
        "wait_reason": "AWAITING_PATIENT_REPLY",
        "intended": True,
    }
    assert project(waiting)["terminal"]["wait_reason"] == "AWAITING_PATIENT_REPLY"


def test_projection_is_json_serialisable():
    json.dumps(project(_item()))
