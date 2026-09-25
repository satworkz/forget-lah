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


def test_archived_ambiguous_family_is_cross_language_equivalent() -> None:
    """With the authored source, en and zh agree — and both fail identically on the CONFIRM over-read.

    The earlier en-escalated/zh-waited divergence disappeared once `variant_tools` served the item's
    authored instructions; it was a harness-default-source artefact, not a language defect.
    """
    en_path = ARCHIVES / "fam-ambiguous-01-en.json"
    zh_path = ARCHIVES / "fam-ambiguous-01-zh.json"
    if not (en_path.exists() and zh_path.exists()):
        pytest.skip("need both en and zh archives")
    en = json.loads(en_path.read_text())
    zh = json.loads(zh_path.read_text())

    assert en["verdict"]["grade"] == zh["verdict"]["grade"] == "FAILED"
    assert cross_language_equivalence(en["observed"], zh["observed"])["equivalent"] is True
    en_paths = {difference["path"] for difference in en["verdict"]["differences"]}
    zh_paths = {difference["path"] for difference in zh["verdict"]["differences"]}
    assert en_paths == zh_paths, "both languages must fail on the same paths"


def test_archived_switch_family_is_cross_language_equivalent() -> None:
    """After the source-fixture fix, en and zh agree on terminal, task outcome and cited source.

    Both cited the authored `instr-fast`, so the earlier UNSUPPORTED vs ANSWERED divergence is gone.
    Asserted so a regression flips this test deliberately.
    """
    en_path = ARCHIVES / "fam-switch-01-en.json"
    zh_path = ARCHIVES / "fam-switch-01-zh.json"
    if not (en_path.exists() and zh_path.exists()):
        pytest.skip("need both switch-family archives")
    en = json.loads(en_path.read_text())
    zh = json.loads(zh_path.read_text())

    assert (
        en["evidence"]["observed_run_status"] == zh["evidence"]["observed_run_status"] == "waiting"
    )
    assert en["verdict"]["grade"] == zh["verdict"]["grade"] == "PASS"
    assert cross_language_equivalence(en["observed"], zh["observed"])["equivalent"] is True
    assert en["observed"]["checkpoint_oracle"][0]["tasks"][0]["instruction_id"] == "instr-fast"


def test_archive_carries_truthful_provenance() -> None:
    path = ARCHIVES / f"{VARIANT}.json"
    if not path.exists():
        pytest.skip(f"no archive at {path}")
    archive = json.loads(path.read_text())
    assert archive["source_run"]["model_id"]
    assert archive["source_run"]["model_id"] != "mock-deterministic"
    assert archive["evidence"]["recorded_decisions"] > 0
    assert archive["variant_id"] == VARIANT
