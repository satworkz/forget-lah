"""Lane C, second experiment: cross-model option-order sensitivity.

Lane B found that whether a local decider acts at all can flip with the presentation order of
its options, deterministically and reproducibly. That matters more than an accuracy point,
because order is an accident of how the caller serialises a label set: `TOOLS_BY_ROLE`,
`DECISION_FORMATS`, a criteria map, a JSON object. If a model's answer depends on it, then a
gate threshold tuned on one ordering does not transfer to another.

This module measures the same property across model families on the gold-labelled benchmark:
it asks each leg the *identical* choice question twice, once with the criteria map in its
published order and once with the keys reversed, and reports how often the hard label moves.
Nothing here is imported by the production decision path, and `score`/`noul` questions are
excluded — reversing an ordered rubric or a yes/no probe would change the question, not just
its presentation.

Every call is scored with `decider_bench.predicted_label`, so a flip is defined once for all
legs rather than per leg.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from forget_lah.runtime import decider_bench as bench

CANONICAL = "canonical"
REVERSED = "reversed"


def choice_questions(row: Mapping[str, Any]) -> dict[str, dict]:
    """The row's choice questions, in the order the benchmark publishes them."""
    return {
        qid: question
        for qid, question in row["questions"].items()
        if isinstance(question, Mapping) and question.get("type") == "choice"
    }


def reversed_question(question: Mapping[str, Any]) -> dict:
    """The same choice question with its criteria keys reversed; the input is not mutated.

    Only the *presentation* changes: identical options, identical instructions, identical
    semantics. A label that moves between the two calls moved because of order alone.
    """
    if question.get("type") != "choice":
        raise ValueError("order reversal is defined for choice questions only")
    criteria = question.get("criteria")
    if not isinstance(criteria, Mapping):
        raise ValueError("choice question has no criteria map")
    return {**question, "criteria": {key: criteria[key] for key in reversed(list(criteria))}}


def probe_question(
    leg: bench.Leg,
    row: Mapping[str, Any],
    qid: str,
    *,
    timeout: float,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Ask one leg one choice question in both orders and report whether the label moved."""
    question = row["questions"][qid]

    def ask(presented: Mapping[str, Any]) -> tuple[str | None, dict, str | None, int]:
        answers, usage, error, latency = bench.post_systemone(
            leg,
            row["state"],
            {qid: dict(presented)},
            timeout=timeout,
            api_key=api_key,
            transport=transport,
        )
        if error is not None or not answers:
            return None, {}, error or "no_answers", latency
        answer = answers.get(qid) or {}
        return (
            bench.predicted_label(question, answer),
            bench.predicted_distribution(question, answer),
            None,
            latency,
        )

    first_label, first_dist, first_error, first_ms = ask(question)
    second_label, second_dist, second_error, second_ms = ask(reversed_question(question))
    options = list((question.get("criteria") or {}).keys())
    return {
        "leg": leg.name,
        "case_id": row.get("id"),
        "workflow": row.get("workflow"),
        "qid": qid,
        "options": options,
        "canonical_label": first_label,
        "reversed_label": second_label,
        "flip": (
            None if first_label is None or second_label is None else first_label != second_label
        ),
        "canonical_confidence": _confidence(first_dist, first_label),
        "reversed_confidence": _confidence(second_dist, second_label),
        "canonical_error": first_error,
        "reversed_error": second_error,
        "latency_ms": [first_ms, second_ms],
    }


def _confidence(distribution: Mapping[str, float], label: str | None) -> float | None:
    if label is None:
        return None
    value = distribution.get(label)
    return round(float(value), 6) if isinstance(value, (int, float)) else None


def summarise(records: Sequence[Mapping[str, Any]]) -> dict:
    """Flip rate per leg, plus the option-count buckets that explain most of the variance."""
    by_leg: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_leg[record["leg"]].append(record)
    out: dict[str, Any] = {}
    for leg, rows in sorted(by_leg.items()):
        comparable = [r for r in rows if r.get("flip") is not None]
        flipped = [r for r in comparable if r["flip"]]
        by_options: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "flipped": 0})
        by_workflow: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "flipped": 0})
        for record in comparable:
            bucket = by_options[str(len(record.get("options") or []))]
            bucket["n"] += 1
            bucket["flipped"] += 1 if record["flip"] else 0
            workflow = by_workflow[str(record.get("workflow"))]
            workflow["n"] += 1
            workflow["flipped"] += 1 if record["flip"] else 0
        errors = Counter(
            r[k]
            for r in rows
            for k in ("canonical_error", "reversed_error")
            if r.get(k) is not None
        )
        out[leg] = {
            "questions_compared": len(comparable),
            "flips": len(flipped),
            "flip_rate": bench.rate(len(flipped), len(comparable)),
            "errors": dict(sorted(errors.items())),
            "flip_rate_by_option_count": {
                name: {"n": v["n"], "flip_rate": bench.rate(v["flipped"], v["n"])}
                for name, v in sorted(by_options.items())
            },
            "flip_rate_by_workflow": {
                name: {"n": v["n"], "flip_rate": bench.rate(v["flipped"], v["n"])}
                for name, v in sorted(by_workflow.items())
            },
        }
    return out


def run(
    legs: Sequence[bench.Leg],
    rows: Sequence[Mapping[str, Any]],
    out: Path,
    *,
    timeout: float = 60.0,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Probe every leg on every choice question of every supplied row, in both orders."""
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    total = len(rows)
    for index, row in enumerate(rows, start=1):
        for qid in choice_questions(row):
            for leg in legs:
                records.append(
                    probe_question(
                        leg, row, qid, timeout=timeout, api_key=api_key, transport=transport
                    )
                )
        print(f"LANE_C_ORDER_PROGRESS case {index}/{total}", flush=True)

    with open(out / "order-records.jsonl", "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    result = {
        "experiment": "lane-c-order-sensitivity",
        "rows": total,
        "choice_questions": sum(len(choice_questions(row)) for row in rows),
        "legs": summarise(records),
    }
    (out / "order-results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("LANE_C_ORDER_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lane C option-order sensitivity probe")
    parser.add_argument("--rows", required=True)
    parser.add_argument("--out", default="/tmp/opencode/lane-c/order-probe")
    parser.add_argument("--leg", action="append", default=[])
    parser.add_argument("--cases", type=int, default=50, help="cases sampled (0 = all)")
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--decider-key-from", default=None)
    args = parser.parse_args(argv)

    legs = [bench.Leg.from_spec(spec) for spec in args.leg]
    if not legs:
        parser.error("at least one --leg is required")
    rows = [row for row in bench.load_rows(args.rows) if choice_questions(row)]
    if args.cases and args.cases < len(rows):
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.cases]
    api_key = None
    if args.decider_key_from:
        api_key = Path(args.decider_key_from).read_text(encoding="utf-8").strip()
    print(
        "LANE_C_ORDER_PLAN "
        + json.dumps(
            {
                "rows": len(rows),
                "choice_questions": sum(len(choice_questions(row)) for row in rows),
                "legs": [leg.name for leg in legs],
                "seed": args.seed,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    run(legs, rows, Path(args.out), timeout=args.timeout, api_key=api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICAL",
    "REVERSED",
    "choice_questions",
    "main",
    "probe_question",
    "reversed_question",
    "run",
    "summarise",
]
