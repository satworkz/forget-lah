"""Lane C: cross-model decision benchmark replay.

Replays a public, gold-labelled typed-decisions benchmark against any endpoint that speaks the
System One wire contract, so independent decision models answer byte-identical questions and
are scored by the same rules. Three legs are compared: Jev through a hosted provider, the
open implementation served locally (Kev), and Laya (open weights, served locally).

Nothing in this module is imported by the production decision path.

Why this is a separate experiment from Lane B: Lane B replays *application observations* that
have no adjudicated correctness labels, so it can report validity, policy admissibility,
stability, latency and cost but never accuracy. This module supplies the missing axis by
replaying a benchmark with gold distributions. Judgement therefore stays with the dataset:

* `choice` and `score` are scored on argmax agreement with the gold label;
* `score` additionally on absolute error of the expected level;
* every primitive on Brier distance to the gold distribution, which is the only axis that
  rewards a calibrated distribution instead of a lucky argmax;
* the dataset's own `label_agreement` block supplies the teacher self-agreement ceiling, so a
  leg can be read against the label noise rather than against a perfect score.

Latency is wall time from this process's clock. Cost is taken from each response's own usage
and priced only where the leg declares a price basis, so a hosted quote cannot be mistaken for
a measured self-hosted figure.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

SYSTEMONE_ROUTE = "/v1/systemone"
RAN = "RAN"
ERROR = "ERROR"
SKIPPED = "SKIPPED"

# Published TypeSafe Jev list price on OpenRouter, used only when a hosted leg declares it.
# Self-hosted legs are reported at $0 marginal cost, with their wall time shown separately.
JEV_INPUT_PRICE_USD_PER_MTOK = 0.042
PRICE_BASIS_JEV = "TypeSafe Jev list price 0.042 USD / 1M input tokens (2026-09); output free"


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 2)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return round(float(ordered[low] * (1 - weight) + ordered[high] * weight), 2)


def _json_field(value: Any) -> Any:
    """Benchmark fields arrive as JSON strings; tolerate an already-decoded value."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return round(float(value), 6) if isinstance(value, (int, float)) else None


@dataclass(frozen=True)
class Leg:
    """One decision endpoint under comparison."""

    name: str
    url: str
    model: str
    billable: bool = False
    price_input_per_mtok: float | None = None
    price_basis: str | None = None

    def __post_init__(self) -> None:
        # A base URL and the full route are both accepted; store the base so reporting is stable.
        normalized = self.url.rstrip("/")
        if normalized.endswith(SYSTEMONE_ROUTE):
            normalized = normalized[: -len(SYSTEMONE_ROUTE)]
        object.__setattr__(self, "url", normalized)

    @classmethod
    def from_spec(cls, spec: str) -> Leg:
        data = json.loads(spec)
        if not isinstance(data, dict) or "name" not in data or "url" not in data:
            raise ValueError(f"leg spec needs name and url: {spec!r}")
        return cls(
            name=str(data["name"]),
            url=str(data["url"]).rstrip("/"),
            model=str(data.get("model") or "systemone"),
            billable=bool(data.get("billable", False)),
            price_input_per_mtok=data.get("price_input_per_mtok"),
            price_basis=data.get("price_basis"),
        )

    def cost_usd(self, input_tokens: int | None) -> float | None:
        if self.price_input_per_mtok is None:
            return 0.0 if not self.billable else None
        if input_tokens is None:
            return None
        return round(input_tokens / 1e6 * float(self.price_input_per_mtok), 6)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Ledger:
    """Budget guard on calls that leave the process for a metered service."""

    limit: int = 400
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def charge(self, leg: Leg) -> None:
        if leg.billable:
            self.counts[leg.name] += 1

    @property
    def billable(self) -> int:
        return sum(self.counts.values())

    @property
    def remaining(self) -> int:
        return max(self.limit - self.billable, 0)

    def fits(self, leg: Leg) -> bool:
        return (not leg.billable) or self.remaining > 0

    def as_dict(self) -> dict:
        return {
            "limit": self.limit,
            "billable": self.billable,
            "remaining": self.remaining,
            "by_leg": dict(sorted(self.counts.items())),
        }


@dataclass
class CallOutcome:
    """One leg's reply on one case, reduced to objective facts."""

    leg: str
    status: str
    answers: dict | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    ok_questions: int = 0
    missing_questions: tuple[str, ...] = ()


def load_rows(path: str | Path) -> list[dict]:
    """Read a benchmark JSONL file and decode the three JSON-string columns per row."""
    rows: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            state = _json_field(raw.get("state"))
            questions = _json_field(raw.get("questions"))
            gold = _json_field(raw.get("gold"))
            agreement = _json_field(raw.get("label_agreement"))
            if not isinstance(questions, dict) or not isinstance(gold, dict):
                continue
            rows.append(
                {
                    "id": raw.get("id"),
                    "workflow": raw.get("workflow"),
                    "state": state,
                    "questions": questions,
                    "gold": gold,
                    "agreement": agreement if isinstance(agreement, dict) else {},
                }
            )
    return rows


def post_systemone(
    leg: Leg,
    state: Any,
    questions: Mapping[str, Any],
    *,
    timeout: float = 60.0,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[dict | None, dict | None, str | None, int]:
    """POST one case to a leg. Returns (answers, usage, error_code, latency_ms)."""
    payload = {"model": leg.model, "state": state, "questions": dict(questions)}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    endpoint = leg.url if leg.url.endswith(SYSTEMONE_ROUTE) else leg.url + SYSTEMONE_ROUTE
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
        with client:
            response = client.post(endpoint, content=body, headers=headers)
    except httpx.TimeoutException:
        return None, None, "timeout", elapsed()
    except httpx.HTTPError:
        return None, None, "transport_error", elapsed()
    latency = elapsed()
    if response.status_code != 200:
        return None, None, f"http_{response.status_code}", latency
    try:
        parsed = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, None, "envelope_invalid", latency
    if not isinstance(parsed, dict):
        return None, None, "envelope_invalid", latency
    answers = parsed.get("answers")
    usage = parsed.get("usage")
    if not isinstance(answers, dict):
        return None, None, "no_answers", latency
    return answers, usage if isinstance(usage, dict) else None, None, latency


def predicted_label(question: Mapping[str, Any], answer: Mapping[str, Any]) -> str | None:
    """The leg's hard label, on the same scale the benchmark's gold `label` uses."""
    qtype = question.get("type")
    if qtype == "noul":
        value = _float_or_none(answer.get("noul"))
        if value is None:
            return None
        return "true" if value >= 0.5 else "false"
    if qtype == "choice":
        choice = answer.get("choice")
        return str(choice) if choice is not None else None
    if qtype == "score":
        probabilities = answer.get("probabilities")
        if isinstance(probabilities, dict) and probabilities:
            try:
                return str(max(probabilities, key=lambda k: float(probabilities[k])))
            except (TypeError, ValueError):
                return None
        value = _float_or_none(answer.get("score"))
        return None if value is None else str(int(round(value)))
    return None


def predicted_distribution(
    question: Mapping[str, Any], answer: Mapping[str, Any]
) -> dict[str, float]:
    """The leg's distribution over the benchmark's own option keys."""
    qtype = question.get("type")
    if qtype == "noul":
        value = _float_or_none(answer.get("noul"))
        if value is None:
            return {}
        return {"false": round(1.0 - value, 6), "true": round(value, 6)}
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in probabilities.items():
        number = _float_or_none(value)
        if number is not None:
            out[str(key)] = number
    return out


def score_question(
    question_id: str,
    question: Mapping[str, Any],
    answer: Mapping[str, Any] | None,
    gold: Mapping[str, Any],
    agreement: Mapping[str, Any] | None = None,
) -> dict:
    """Score one answered question against the benchmark's gold distribution.

    Every axis is defined here rather than imported from any leg's own metric code, so the
    three legs cannot be compared on three different definitions of "accurate".
    """
    qtype = question.get("type")
    gold_label = gold.get("label")
    record: dict[str, Any] = {
        "qid": question_id,
        "qtype": qtype,
        "gold": str(gold_label) if gold_label is not None else None,
        "predicted": None,
        "correct": None,
        "brier": None,
        "tv": None,
        "gold_mass": None,
        "score_mae": None,
        "teacher_agree": None,
    }
    if isinstance(agreement, Mapping) and "argmax_agree" in agreement:
        record["teacher_agree"] = bool(agreement.get("argmax_agree"))
    if not isinstance(answer, Mapping):
        return record

    record["predicted"] = predicted_label(question, answer)
    if record["predicted"] is not None and record["gold"] is not None:
        record["correct"] = record["predicted"] == record["gold"]

    gold_dist = predicted_distribution(question, gold)
    pred_dist = predicted_distribution(question, answer)
    keys = sorted(set(gold_dist) | set(pred_dist))
    if keys and gold_dist and pred_dist:
        brier = sum((pred_dist.get(k, 0.0) - gold_dist.get(k, 0.0)) ** 2 for k in keys) / len(keys)
        tv = 0.5 * sum(abs(pred_dist.get(k, 0.0) - gold_dist.get(k, 0.0)) for k in keys)
        record["brier"] = round(brier, 6)
        record["tv"] = round(tv, 6)
        if record["gold"] is not None:
            record["gold_mass"] = round(pred_dist.get(record["gold"], 0.0), 6)

    if qtype == "score":
        gold_score = _float_or_none(gold.get("score"))
        predicted_score = _float_or_none(answer.get("score"))
        if gold_score is not None and predicted_score is not None:
            record["score_mae"] = round(abs(predicted_score - gold_score), 6)
    return record


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def call_leg(
    leg: Leg,
    row: Mapping[str, Any],
    *,
    timeout: float,
    api_key: str | None,
    transport: httpx.BaseTransport | None = None,
) -> CallOutcome:
    answers, usage, error, latency = post_systemone(
        leg, row["state"], row["questions"], timeout=timeout, api_key=api_key, transport=transport
    )
    if error is not None or answers is None:
        return CallOutcome(
            leg=leg.name, status=ERROR, error_code=error or "no_answers", latency_ms=latency
        )
    expected = set(row["questions"])
    present = expected & set(answers)
    return CallOutcome(
        leg=leg.name,
        status=RAN,
        answers=answers,
        usage=usage,
        latency_ms=latency,
        ok_questions=len(present),
        missing_questions=tuple(sorted(expected - present)),
    )


def aggregate(
    leg: Leg, records: Sequence[Mapping[str, Any]], outcomes: Sequence[CallOutcome]
) -> dict:
    """Reduce per-question records to the leg's scorecard."""
    graded = [r for r in records if r.get("gold") is not None]
    answered = [r for r in graded if r.get("predicted") is not None]
    correct = [r for r in answered if r.get("correct") is True]

    def group(key: str) -> dict:
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "correct": 0})
        for record in answered:
            bucket = buckets[record[key] or "unknown"]
            bucket["n"] += 1
            bucket["correct"] += 1 if record.get("correct") else 0
        return {
            name: {"n": value["n"], "accuracy": rate(value["correct"], value["n"])}
            for name, value in sorted(buckets.items())
        }

    brier = [r["brier"] for r in answered if r.get("brier") is not None]
    tv = [r["tv"] for r in answered if r.get("tv") is not None]
    mae = [r["score_mae"] for r in answered if r.get("score_mae") is not None]
    gold_mass = [r["gold_mass"] for r in answered if r.get("gold_mass") is not None]
    latencies = [o.latency_ms for o in outcomes if o.latency_ms is not None]
    input_tokens = sum((o.usage or {}).get("input_tokens") or 0 for o in outcomes)
    usage_reported = sum(1 for o in outcomes if o.usage)
    return {
        "leg": leg.name,
        "url": leg.url,
        "model": leg.model,
        "billable": leg.billable,
        "price_basis": leg.price_basis,
        "calls": len(outcomes),
        "calls_ok": sum(1 for o in outcomes if o.status == RAN),
        "errors": dict(
            sorted(Counter(o.error_code for o in outcomes if o.status == ERROR).items())
        ),
        "skipped": dict(
            sorted(Counter(o.error_code for o in outcomes if o.status == SKIPPED).items())
        ),
        "questions_expected": len(records),
        "questions_answered": len(answered),
        "questions_missing": len(graded) - len(answered),
        "accuracy": rate(len(correct), len(answered)),
        "accuracy_by_workflow": group("workflow"),
        "accuracy_by_primitive": group("qtype"),
        "brier": _mean(brier),
        "tv": _mean(tv),
        "gold_mass": _mean(gold_mass),
        "score_mae": _mean(mae),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "mean": _mean(latencies),
        },
        "input_tokens": input_tokens,
        "output_tokens": sum((o.usage or {}).get("output_tokens") or 0 for o in outcomes),
        "reported_cost_usd": sum(
            float((o.usage or {}).get("cost") or 0.0)
            for o in outcomes
            if isinstance((o.usage or {}).get("cost"), (int, float))
        ),
        # A billable leg that reported no usage at all is unpriced, not free.
        "priced_cost_usd": (
            None if (leg.billable and usage_reported == 0) else leg.cost_usd(input_tokens)
        ),
    }


def reference_ceiling(rows: Sequence[Mapping[str, Any]]) -> dict:
    """The dataset's own label-noise ceiling, for reading every leg's accuracy against."""
    agreements = [
        bool(per_q.get("argmax_agree"))
        for row in rows
        for per_q in (row.get("agreement") or {}).values()
        if isinstance(per_q, Mapping) and "argmax_agree" in per_q
    ]
    majority_hits = [
        1
        for row in rows
        for qid, per_q in (row.get("agreement") or {}).items()
        if isinstance(per_q, Mapping)
        and per_q.get("argmax_majority") is not None
        and str(per_q.get("argmax_majority"))
        == str((row.get("gold") or {}).get(qid, {}).get("label"))
    ]
    total = sum(
        1
        for row in rows
        for per_q in (row.get("agreement") or {}).values()
        if isinstance(per_q, Mapping) and per_q.get("argmax_majority") is not None
    )
    return {
        "questions": total,
        "teacher_self_agreement": rate(sum(1 for a in agreements if a), len(agreements)),
        "teacher_argmax_vs_gold": rate(len(majority_hits), total),
    }


def summarise(result: Mapping[str, Any]) -> str:
    parts = [
        "Cross-model benchmark replay on the public typed-decisions test split: every leg "
        "answered byte-identical questions and was scored on argmax agreement with the gold "
        "label, Brier distance to the gold distribution, and expected-level error for `score`."
    ]
    ceiling = result.get("ceiling") or {}
    if ceiling:
        parts.append(
            f"Label ceilings: teacher self-agreement {ceiling.get('teacher_self_agreement')}, "
            f"teacher argmax versus gold {ceiling.get('teacher_argmax_vs_gold')} "
            f"over {ceiling.get('questions')} questions."
        )
    for leg in result.get("legs", []):
        parts.append(
            f"{leg['leg']}: accuracy {leg['accuracy']} over {leg['questions_answered']} answered "
            f"questions, Brier {leg['brier']}, p50 {leg['latency_ms']['p50']} ms, "
            f"errors {json.dumps(leg['errors'], sort_keys=True)}."
        )
    parts.append(
        "Accuracy here is agreement with synthetic gold labels, not with clinical judgement, so "
        "it ranks these models on a routing-style benchmark and does not by itself license any "
        "change to the application's decision policy."
    )
    return " ".join(parts)


def run(
    legs: Sequence[Leg],
    rows: Sequence[Mapping[str, Any]],
    out: Path,
    *,
    timeout: float = 60.0,
    budget: int = 400,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Replay every leg over every row, writing raw answers, per-question records and results."""
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(limit=budget)
    records: dict[str, list[dict]] = {leg.name: [] for leg in legs}
    outcomes: dict[str, list[CallOutcome]] = {leg.name: [] for leg in legs}

    for index, row in enumerate(rows, start=1):
        for leg in legs:
            if not ledger.fits(leg):
                outcomes[leg.name].append(
                    CallOutcome(leg=leg.name, status=SKIPPED, error_code="budget_exhausted")
                )
                continue
            ledger.charge(leg)
            outcome = call_leg(leg, row, timeout=timeout, api_key=api_key, transport=transport)
            outcomes[leg.name].append(outcome)
            answers = outcome.answers or {}
            for qid, question in row["questions"].items():
                record = score_question(
                    qid,
                    question,
                    answers.get(qid),
                    row["gold"].get(qid, {}),
                    (row.get("agreement") or {}).get(qid),
                )
                record["workflow"] = row.get("workflow")
                record["case_id"] = row.get("id")
                record["leg"] = leg.name
                records[leg.name].append(record)
        print(f"LANE_C_PROGRESS case {index}/{len(rows)}", flush=True)

    legs_summary = [aggregate(leg, records[leg.name], outcomes[leg.name]) for leg in legs]
    result = {
        "experiment": "lane-c-cross-model-benchmark",
        "rows": len(rows),
        "questions": sum(len(row["questions"]) for row in rows),
        "legs": legs_summary,
        "budget": ledger.as_dict(),
        "ceiling": reference_ceiling(rows),
    }
    result["summary"] = summarise(result)

    for leg in legs:
        with open(out / f"records-{leg.name}.jsonl", "w", encoding="utf-8") as handle:
            for record in records[leg.name]:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        with open(out / f"answers-{leg.name}.jsonl", "w", encoding="utf-8") as handle:
            for row, outcome in zip(rows, outcomes[leg.name], strict=True):
                handle.write(
                    json.dumps(
                        {
                            "case_id": row.get("id"),
                            "workflow": row.get("workflow"),
                            "status": outcome.status,
                            "error_code": outcome.error_code,
                            "latency_ms": outcome.latency_ms,
                            "usage": outcome.usage,
                            "answers": outcome.answers,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
    (out / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("LANE_C_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lane C cross-model decision benchmark replay")
    parser.add_argument("--rows", required=True, help="benchmark JSONL produced by the fetch step")
    parser.add_argument("--out", default="/tmp/opencode/lane-c")
    parser.add_argument(
        "--leg",
        action="append",
        default=[],
        help='JSON leg spec, e.g. {"name":"laya","url":"http://127.0.0.1:8014"}',
    )
    parser.add_argument("--limit", type=int, default=0, help="max cases (0 = all)")
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--decider-key-from",
        default=None,
        help="file holding the bearer token for hosted legs; never printed",
    )
    args = parser.parse_args(argv)

    legs = [Leg.from_spec(spec) for spec in args.leg]
    if not legs:
        parser.error("at least one --leg is required")
    rows = load_rows(args.rows)
    if args.limit:
        rows = rows[: args.limit]
    api_key = None
    if args.decider_key_from:
        try:
            api_key = Path(args.decider_key_from).read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"LANE_C_KEY error={type(exc).__name__}")
            return 2
    print(
        "LANE_C_PLAN "
        + json.dumps(
            {
                "rows": len(rows),
                "questions": sum(len(row["questions"]) for row in rows),
                "legs": [leg.as_dict() for leg in legs],
                "key_present": api_key is not None,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    run(
        legs,
        rows,
        Path(args.out),
        timeout=args.timeout,
        budget=args.budget,
        api_key=api_key,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ERROR",
    "JEV_INPUT_PRICE_USD_PER_MTOK",
    "PRICE_BASIS_JEV",
    "RAN",
    "SKIPPED",
    "CallOutcome",
    "Leg",
    "Ledger",
    "aggregate",
    "call_leg",
    "load_rows",
    "main",
    "post_systemone",
    "predicted_distribution",
    "predicted_label",
    "reference_ceiling",
    "run",
    "score_question",
    "summarise",
]
