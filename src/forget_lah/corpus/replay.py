"""Replay grading for the multilingual corpus pilot.

`execution_origin: replay` means *reproduce one observed execution from archived evidence* and grade
it against the authored oracle. This module is that grading core:

- `grade(oracle_item, observed)` projects both sides with `comparison_projection` and returns a
  per-field verdict: `PASS`, `FAILED` or `UNSCORED`, with the exact differing paths.
- `cross_language_equivalence(a, b)` compares two variants of an aligned family after dropping the
  declared language-dependent paths, which is the cross-language property the PRD asks for.
- `load_archive(path)` reads an archived execution record (see `docs/corpus/m2/M2_REPLAY.md`).

Pure: stdlib only, no I/O beyond reading a caller-supplied archive path, no runtime imports. Grading
is deterministic. Producing the archive from a live simulator run is the separate execution step; this
module never fabricates one.

Verdict rules follow `docs/corpus/m1/oracle_rubric.md`: any field difference or a hard translation
failure is FAILED; a quarantined stratum is UNSCORED and earns no passing credit; translation
nondeterminism and `TRANSLATION_VALIDATION_FAILED` are failures, never unscored.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .comparison_projection import LANGUAGE_DEPENDENT_PATHS, project

REPLAY_VERSION = "1"

#: Translation/execution outcomes that are failures of the system under test, never unscored.
HARD_FAILURE_STATUSES = frozenset(
    {
        "TRANSLATION_VALIDATION_FAILED",
        "TRANSLATION_INCOMPLETE",
        "semantic_corruption",
        "wrong_target_language",
        "missing_required_delivery",
        "worker_interruption",
    }
)

_ALIGNMENT_IGNORED = LANGUAGE_DEPENDENT_PATHS | {"identity.variant_id"}

#: A visit-scoped `preferred_language` whose value equals the variant's own language is a D2
#: comprehension repair: it is *permitted* rather than required, so its presence or absence must not
#: decide a grade. A `future`-scoped preference, or a value for another language, is still graded.
_PERMITTED_OPTIONAL_MEMORY_KEY = "preferred_language"


def strip_permitted_optional_memory(projection: dict[str, Any], language: str | None) -> None:
    """Normalise permitted, non-deciding differences in place.

    1. Drop a visit-scoped `preferred_language` whose value equals the variant's own language
       (D2 comprehension repair — permitted, not required).
    2. Treat an unrecorded `callback_requested` as `false`: the runtime stores no negative callback, so
       absence and `false` are the same state. A scenario that requires a callback authors `true`.
    """
    for checkpoint in projection.get("checkpoints") or []:
        if checkpoint.get("callback_requested") is None:
            checkpoint["callback_requested"] = False
        entries = checkpoint.get("memory")
        if not isinstance(entries, list):
            continue
        checkpoint["memory"] = [
            entry
            for entry in entries
            if not (
                entry.get("key") == _PERMITTED_OPTIONAL_MEMORY_KEY
                and entry.get("scope") == "visit"
                and entry.get("value") == language
            )
        ]


def _drop_path(node: dict[str, Any], path: str) -> None:
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


def _diff(expected: Any, observed: Any, path: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(expected, Mapping) and isinstance(observed, Mapping):
        for key in sorted(set(expected) | set(observed)):
            child = f"{path}.{key}" if path else key
            if key not in expected:
                out.append({"path": child, "expected": "<absent>", "observed": observed[key]})
            elif key not in observed:
                out.append({"path": child, "expected": expected[key], "observed": "<absent>"})
            else:
                out.extend(_diff(expected[key], observed[key], child))
    elif isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            out.append(
                {
                    "path": path,
                    "expected": f"len {len(expected)}",
                    "observed": f"len {len(observed)}",
                }
            )
        else:
            for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
                out.extend(_diff(left, right, f"{path}[{index}]"))
    elif expected != observed:
        out.append({"path": path, "expected": expected, "observed": observed})
    return out


def grade(
    oracle_item: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    origin: str = "replay",
    translation_status: str | None = None,
) -> dict[str, Any]:
    """Grade one observed execution against the authored oracle item."""
    expected = project(oracle_item)
    actual = project(observed)
    expected.pop("projection_version", None)
    actual.pop("projection_version", None)

    expected_language = (oracle_item.get("identity") or {}).get("language")
    observed_language = (observed.get("identity") or {}).get("language")
    strip_permitted_optional_memory(expected, expected_language)
    strip_permitted_optional_memory(actual, observed_language or expected_language)

    hard_failures: list[str] = []
    if translation_status in HARD_FAILURE_STATUSES:
        hard_failures.append(f"translation_status={translation_status}")

    if observed_language is not None and observed_language != expected_language:
        hard_failures.append(f"wrong_target_language={observed_language}")

    differences = _diff(expected, actual)

    scoring = oracle_item.get("scoring") or {}
    if scoring.get("scored") is False:
        verdict = "UNSCORED"
    elif hard_failures or differences:
        verdict = "FAILED"
    else:
        verdict = "PASS"

    return {
        "replay_version": REPLAY_VERSION,
        "variant_id": (oracle_item.get("identity") or {}).get("variant_id"),
        "origin": origin,
        "grade": verdict,
        "unscored_reason": scoring.get("unscored_reason") if verdict == "UNSCORED" else None,
        "hard_failures": hard_failures,
        "differences": differences,
    }


def cross_language_equivalence(
    item_a: Mapping[str, Any], item_b: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare two aligned variants after dropping declared language-dependent paths."""
    left = project(item_a)
    right = project(item_b)
    strip_permitted_optional_memory(left, (item_a.get("identity") or {}).get("language"))
    strip_permitted_optional_memory(right, (item_b.get("identity") or {}).get("language"))
    for projection in (left, right):
        projection.pop("projection_version", None)
        for path in _ALIGNMENT_IGNORED:
            _drop_path(projection, path)
    differences = _diff(left, right)
    return {"equivalent": not differences, "differences": differences}


def load_archive(path: str | Path) -> dict[str, Any]:
    """Read an archived execution record; see docs/corpus/m2/M2_REPLAY.md for the schema."""
    return json.loads(Path(path).read_text())
