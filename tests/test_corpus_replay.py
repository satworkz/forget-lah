import copy
import json
from pathlib import Path

from forget_lah.corpus.replay import (
    REPLAY_VERSION,
    cross_language_equivalence,
    grade,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "development" / "pilot"


def _variant(name: str) -> dict:
    return json.loads((PILOT / name).read_text())


def _observed_from(oracle: dict) -> dict:
    """A synthetic observation mirroring the oracle.

    This is a self-test of the grader, NOT execution evidence: no pilot variant carries an archive
    until the runtime archive producer exists (see docs/corpus/m2/M2_REPLAY.md).
    """
    return {
        "identity": copy.deepcopy(oracle["identity"]),
        "environment": copy.deepcopy(oracle["environment"]),
        "checkpoint_oracle": copy.deepcopy(oracle["checkpoint_oracle"]),
        "terminal_oracle": copy.deepcopy(oracle["terminal_oracle"]),
        "scoring": copy.deepcopy(oracle["scoring"]),
    }


def test_a_matching_observation_passes() -> None:
    oracle = _variant("confirmation-01-en.json")
    result = grade(oracle, _observed_from(oracle))
    assert result["grade"] == "PASS"
    assert result["differences"] == []
    assert result["hard_failures"] == []
    assert result["origin"] == "replay"
    assert result["replay_version"] == REPLAY_VERSION


def test_grading_is_deterministic() -> None:
    oracle = _variant("questions-01-zh.json")
    observed = _observed_from(oracle)
    assert grade(oracle, observed) == grade(oracle, observed)


def test_wrong_target_language_fails() -> None:
    oracle = _variant("confirmation-01-en.json")
    observed = _observed_from(oracle)
    observed["identity"]["language"] = "ms"
    observed["checkpoint_oracle"][0]["delivery"]["effective_language"] = "ms"
    result = grade(oracle, observed)
    assert result["grade"] == "FAILED"
    assert any(item.startswith("wrong_target_language") for item in result["hard_failures"])
    assert result["differences"]


def test_missing_required_delivery_fails() -> None:
    oracle = _variant("confirmation-01-en.json")
    observed = _observed_from(oracle)
    observed["checkpoint_oracle"][0]["delivery"].pop("expected_message_delivery")
    result = grade(oracle, observed)
    assert result["grade"] == "FAILED"
    assert any("expected_message_delivery" in diff["path"] for diff in result["differences"])


def test_translation_validation_failure_is_a_failure_not_unscored() -> None:
    oracle = _variant("confirmation-01-en.json")
    result = grade(
        oracle,
        _observed_from(oracle),
        translation_status="TRANSLATION_VALIDATION_FAILED",
    )
    assert result["grade"] == "FAILED"
    assert result["unscored_reason"] is None
    assert result["hard_failures"]


def test_quarantined_stratum_is_unscored_and_earns_no_credit() -> None:
    oracle = _variant("wrong-number-01-en.json")
    observed = _observed_from(oracle)
    result = grade(oracle, observed)
    assert result["grade"] == "UNSCORED"
    assert result["unscored_reason"] == "wrong_number_path_absent"

    observed["terminal_oracle"] = {
        "kind": "failure",
        "run_status": "paused",
        "failure_code": "STALE_CHECKPOINT",
    }
    mutated = grade(oracle, observed)
    assert mutated["grade"] == "UNSCORED"


def test_aligned_family_is_cross_language_equivalent() -> None:
    en = _variant("questions-01-en.json")
    zh = _variant("questions-01-zh.json")
    result = cross_language_equivalence(en, zh)
    assert result["equivalent"] is True
    assert result["differences"] == []


def test_a_semantic_difference_breaks_cross_language_equivalence() -> None:
    en = _variant("questions-01-en.json")
    zh = _variant("questions-01-zh.json")
    zh["checkpoint_oracle"][0]["tasks"][0]["outcome"] = "UNSUPPORTED"
    result = cross_language_equivalence(en, zh)
    assert result["equivalent"] is False
    assert any("outcome" in diff["path"] for diff in result["differences"])


def test_language_switch_family_still_agrees_on_semantics() -> None:
    en = _variant("ambiguous-01-en.json")
    ta = _variant("ambiguous-01-ta.json")
    assert cross_language_equivalence(en, ta)["equivalent"] is True
