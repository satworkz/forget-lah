import json
from pathlib import Path

import pytest

from forget_lah.corpus.replay import cross_language_equivalence, grade

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "development" / "pilot"
ARCHIVES = ROOT / "corpus" / "development" / "archives"

VARIANT = "fam-ambiguous-01-en"


def test_archived_observation_regrades_deterministically() -> None:
    """The archive's captured observation must regrade to the recorded verdict, offline."""
    path = ARCHIVES / f"{VARIANT}.json"
    if not path.exists():
        pytest.skip(f"no archive at {path}")
    archive = json.loads(path.read_text())
    variant = json.loads((PILOT / f"{VARIANT.removeprefix('fam-')}.json").read_text())

    assert archive["execution_origin"] == "replay"
    verdict = grade(variant, archive["observed"])
    assert verdict == archive["verdict"], verdict["differences"]
    assert verdict["grade"] in {"PASS", "FAILED", "UNSCORED"}


def test_archived_en_and_zh_diverge() -> None:
    """Recorded finding: the en and zh variants of the ambiguous family do NOT match.

    en escalated where the oracle expects waiting; zh waited but recorded a memory update the oracle
    did not author. The divergence is asserted (not skipped) so a future fix flips this test
    deliberately.
    """
    en_path = ARCHIVES / "fam-ambiguous-01-en.json"
    zh_path = ARCHIVES / "fam-ambiguous-01-zh.json"
    if not (en_path.exists() and zh_path.exists()):
        pytest.skip("need both en and zh archives")
    en = json.loads(en_path.read_text())
    zh = json.loads(zh_path.read_text())

    result = cross_language_equivalence(en["observed"], zh["observed"])
    assert result["equivalent"] is False
    paths = [difference["path"] for difference in result["differences"]]
    assert any(path.startswith("terminal") for path in paths)
    # The visit-only language update D2 permits is no longer reported as a difference.
    assert not any(path.endswith("memory") for path in paths)


def test_archive_carries_truthful_provenance() -> None:
    path = ARCHIVES / f"{VARIANT}.json"
    if not path.exists():
        pytest.skip(f"no archive at {path}")
    archive = json.loads(path.read_text())
    assert archive["source_run"]["model_id"]
    assert archive["source_run"]["model_id"] != "mock-deterministic"
    assert archive["evidence"]["recorded_decisions"] > 0
    assert archive["variant_id"] == VARIANT
