import json
from pathlib import Path

import pytest

from forget_lah.corpus.replay import grade

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


def test_archive_carries_truthful_provenance() -> None:
    path = ARCHIVES / f"{VARIANT}.json"
    if not path.exists():
        pytest.skip(f"no archive at {path}")
    archive = json.loads(path.read_text())
    assert archive["source_run"]["model_id"]
    assert archive["source_run"]["model_id"] != "mock-deterministic"
    assert archive["evidence"]["recorded_decisions"] > 0
    assert archive["variant_id"] == VARIANT
