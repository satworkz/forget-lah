"""Lane C option-order probe tests.

Hermetic: the only endpoint is an `httpx.MockTransport`, and the flip definition is asserted
against hand-built answers.
"""

import json

import httpx
import pytest

from forget_lah.runtime import decider_bench as bench
from forget_lah.runtime import decider_order_probe as probe

LEG = bench.Leg(name="laya", url="http://127.0.0.1:8012", model="laya")

CHOICE = {
    "type": "choice",
    "instructions": "Which team should handle this?",
    "criteria": {"billing": "refunds", "technical": "bugs", "sales": "pricing"},
}


def row():
    return {
        "id": "case-1",
        "workflow": "customer_service",
        "state": {"a": 1},
        "questions": {"team": dict(CHOICE), "urgent": {"type": "noul", "instructions": "?"}},
        "gold": {"team": {"label": "billing"}},
    }


def test_reversed_question_reverses_keys_and_does_not_mutate():
    original = dict(CHOICE)
    flipped = probe.reversed_question(CHOICE)
    assert list(flipped["criteria"]) == ["sales", "technical", "billing"]
    assert original["criteria"] == CHOICE["criteria"]  # input untouched
    assert flipped["instructions"] == CHOICE["instructions"]
    assert set(flipped["criteria"]) == set(CHOICE["criteria"])


def test_reversed_question_rejects_ordered_or_non_choice_questions():
    with pytest.raises(ValueError):
        probe.reversed_question({"type": "score", "criteria": ["a", "b"]})
    with pytest.raises(ValueError):
        probe.reversed_question({"type": "choice", "instructions": "x"})


def test_choice_questions_selects_only_choice_rows():
    questions = probe.choice_questions(row())
    assert list(questions) == ["team"]
    assert questions["team"]["type"] == "choice"


def test_probe_question_sees_only_the_presentation_change():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        criteria = body["questions"]["team"]["criteria"]
        seen.append(list(criteria))
        choice = "billing" if list(criteria)[0] == "billing" else "sales"
        return httpx.Response(
            200,
            json={
                "answers": {
                    "team": {
                        "type": "choice",
                        "choice": choice,
                        "probabilities": {choice: 0.9},
                        "confidence": 0.9,
                    }
                }
            },
        )

    record = probe.probe_question(
        LEG, row(), "team", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert seen == [["billing", "technical", "sales"], ["sales", "technical", "billing"]]
    assert record["canonical_label"] == "billing"
    assert record["reversed_label"] == "sales"
    assert record["flip"] is True
    assert record["canonical_confidence"] == 0.9
    assert record["options"] == ["billing", "technical", "sales"]


def test_probe_question_records_stable_answer_as_no_flip():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answers": {
                    "team": {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"billing": 0.8},
                    }
                }
            },
        )

    record = probe.probe_question(
        LEG, row(), "team", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert record["flip"] is False


def test_probe_question_reports_transport_failure_as_unscored():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    record = probe.probe_question(
        LEG, row(), "team", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert record["flip"] is None
    assert record["canonical_error"] == "http_500"


def test_summarise_computes_flip_rate_by_leg_options_and_workflow():
    records = [
        {
            "leg": "a",
            "workflow": "wf1",
            "options": ["x", "y"],
            "flip": True,
            "canonical_error": None,
            "reversed_error": None,
        },
        {
            "leg": "a",
            "workflow": "wf1",
            "options": ["x", "y", "z"],
            "flip": False,
            "canonical_error": None,
            "reversed_error": None,
        },
        {
            "leg": "a",
            "workflow": "wf2",
            "options": ["x", "y", "z"],
            "flip": False,
            "canonical_error": None,
            "reversed_error": None,
        },
        {
            "leg": "b",
            "workflow": "wf1",
            "options": ["x", "y"],
            "flip": None,
            "canonical_error": "timeout",
            "reversed_error": None,
        },
    ]
    summary = probe.summarise(records)
    assert summary["a"]["questions_compared"] == 3
    assert summary["a"]["flips"] == 1
    assert summary["a"]["flip_rate"] == pytest.approx(0.3333)
    assert summary["a"]["flip_rate_by_option_count"]["2"] == {"n": 1, "flip_rate": 1.0}
    assert summary["a"]["flip_rate_by_option_count"]["3"] == {"n": 2, "flip_rate": 0.0}
    assert summary["a"]["flip_rate_by_workflow"]["wf2"] == {"n": 1, "flip_rate": 0.0}
    assert summary["b"]["questions_compared"] == 0
    assert summary["b"]["flip_rate"] is None
    assert summary["b"]["errors"] == {"timeout": 1}
