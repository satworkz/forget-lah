"""Lane B measurement core: corpus capture, paired replay, aggregation, scorecard.

Nothing here is imported by the production decision path. The module exists so that the
"LLM versus openjev decider" comparison is a reproducible command instead of a narrative.

Three experiments stay deliberately separate:

* **corpus capture** — mock-driven trajectories, so a state is not caused by the leg being
  measured and the paired replay is off-policy by construction;
* **paired replay** — every leg decides the identical recorded observation, scored on
  objective axes only (`parse_decision` validity, `policy_for` verdict, agreement, latency,
  cost);
* **closed loop** — each arm drives whole scenarios and the end-to-end run state is compared.

`CallLedger` counts every call that leaves the process, so an arm that cannot fit the
remaining budget is SKIPPED with a reason instead of half-completed.
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from forget_lah.runtime.contracts import parse_decision
from forget_lah.runtime.provider import ModelError

LEG_ANTHROPIC = "llm-anthropic"
LEG_KEV_4B = "decider-kev4b"
LEG_KEV_27B = "decider-kev27b"
LEG_HOSTED = "decider-hosted-jev"
LEG_MOCK = "mock"

# Only legs that leave the process for a metered service count against the budget.
BILLABLE_LEGS = frozenset({LEG_ANTHROPIC, LEG_HOSTED})

# claude-sonnet-4-5 list price; cache tokens are reported but not priced here.
ANTHROPIC_PRICE_USD_PER_MTOK = {"input": 3.0, "output": 15.0}
PRICE_BASIS = "claude-sonnet-4-5 list price 2026-09, cache tokens excluded"

REPLAY = "RAN"
SKIPPED = "SKIPPED"
ERROR = "ERROR"


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


def cost_usd(leg: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Anthropic spend for a call; None where the leg has no published per-token price."""
    if leg in BILLABLE_LEGS and leg != LEG_ANTHROPIC:
        return None
    if leg not in BILLABLE_LEGS:
        return 0.0
    if input_tokens is None and output_tokens is None:
        return None
    return round(
        (input_tokens or 0) / 1e6 * ANTHROPIC_PRICE_USD_PER_MTOK["input"]
        + (output_tokens or 0) / 1e6 * ANTHROPIC_PRICE_USD_PER_MTOK["output"],
        6,
    )


@dataclass
class CallLedger:
    """Budget guard: count every metered call and refuse an arm that cannot fit."""

    limit: int = 40
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def charge(self, leg: str) -> None:
        self.counts[leg] += 1

    @property
    def billable(self) -> int:
        return sum(count for leg, count in self.counts.items() if leg in BILLABLE_LEGS)

    @property
    def remaining(self) -> int:
        return max(self.limit - self.billable, 0)

    def fits(self, calls: int) -> bool:
        return calls <= self.remaining

    def as_dict(self) -> dict:
        return {
            "limit": self.limit,
            "billable": self.billable,
            "remaining": self.remaining,
            "by_leg": dict(sorted(self.counts.items())),
        }


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def signature(document: Mapping[str, Any] | None) -> tuple[str, str, str] | None:
    """The comparable identity of a decision: step type, reason code and target/tool."""
    if not isinstance(document, Mapping):
        return None
    step_type = document.get("step_type")
    if not isinstance(step_type, str):
        return None
    detail = document.get("target") or document.get("tool_name") or ""
    return (step_type, str(document.get("reason_code") or ""), str(detail))


def label(value: tuple[str, str, str] | None) -> str:
    return "|".join(value) if value else "NONE"


@dataclass(frozen=True)
class LegOutcome:
    """One leg's reply on one observation, reduced to objective facts."""

    leg: str
    status: str
    step_type: str | None = None
    reason_code: str | None = None
    target: str | None = None
    tool_name: str | None = None
    contract_valid: bool | None = None
    policy: str | None = None
    policy_codes: tuple[str, ...] = ()
    confidence: float | None = None
    probability: float | None = None
    probabilities: dict | None = None
    choice: str | None = None
    abstained: bool = False
    fallback_reason: str | None = None
    bypass_reason: str | None = None
    proposed: dict | None = None
    proposed_policy: str | None = None
    proposed_policy_codes: tuple[str, ...] = ()
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error_code: str | None = None
    skip_reason: str | None = None

    @property
    def chosen(self) -> tuple[str, str, str] | None:
        return signature(
            {
                "step_type": self.step_type,
                "reason_code": self.reason_code,
                "target": self.target,
                "tool_name": self.tool_name,
            }
        )

    @property
    def proposed_choice(self) -> tuple[str, str, str] | None:
        return signature(self.proposed)

    @property
    def eligible(self) -> bool:
        return self.status == REPLAY and bool(self.contract_valid)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LegOutcome:
        data = dict(value)
        data["policy_codes"] = tuple(data.get("policy_codes") or ())
        data["proposed_policy_codes"] = tuple(data.get("proposed_policy_codes") or ())
        return cls(**data)


def skipped(leg: str, reason: str) -> LegOutcome:
    return LegOutcome(leg=leg, status=SKIPPED, skip_reason=reason)


def _record_line_count(record: str | Path | None) -> int:
    """Line count of a decider register, or 0 when it is absent or unreadable."""
    if record is None:
        return 0
    try:
        with open(record, encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _records_since(record: str | Path | None, count: int) -> list[dict]:
    """Register lines appended since `count`, newest last; malformed lines are dropped.

    The register is the designed carrier for gate inputs: it records the answer's confidence
    and probabilities before validation so a rejected answer can be replayed against other
    thresholds with no further live request. The returned provenance carries neither, so the
    harness reads them from here rather than asking the model wrapper to change shape.
    """
    if record is None:
        return []
    try:
        with open(record, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[count:]:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def evaluate_leg(
    leg: str,
    call: Callable[[dict], Any],
    observation: Mapping[str, Any],
    *,
    policy: Callable[[Any], Mapping[str, Any] | None] | None = None,
    patient_source: str | None = None,
    charge: Callable[[str], None] | None = None,
    record: str | Path | None = None,
) -> LegOutcome:
    """Run one leg on one observation and score it without interpretation.

    Validity comes from `parse_decision` and the verdict from `policy_for`, so both are
    deterministic project rules rather than harness judgement. A leg that falls back to its
    inner provider is scored on the decision that would actually be executed, and the
    fallback is recorded separately so an abstaining leg cannot look accurate by default.

    `record` is the leg's own decider register. Gate inputs are taken from the line the call
    appended, because the returned provenance omits the answer's choice and probabilities;
    a register line is only used when it exists for this call.
    """
    if charge is not None:
        charge(leg)
    started = time.monotonic()
    record_before = _record_line_count(record)
    try:
        reply = call(dict(observation))
    except ModelError as exc:
        return LegOutcome(
            leg=leg,
            status=ERROR,
            error_code=exc.code,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 - the harness records any transport failure
        return LegOutcome(
            leg=leg,
            status=ERROR,
            error_code=type(exc).__name__,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    provenance = getattr(reply, "provenance", None)
    provenance = provenance if isinstance(provenance, dict) else {}
    fresh = _records_since(record, record_before)
    registered = fresh[-1] if fresh else {}
    if not isinstance(registered, dict):
        registered = {}
    probabilities = registered.get("probabilities")
    if not isinstance(probabilities, dict):
        probabilities = provenance.get("probabilities")
    raw_answer = registered.get("raw_answer")
    choice = raw_answer.get("choice") if isinstance(raw_answer, dict) else None
    if choice is None or choice == "[REDACTED]":
        choice = provenance.get("choice")
    confidence = registered.get("confidence")
    if confidence is None:
        confidence = provenance.get("confidence")
    probability = None
    if isinstance(probabilities, dict) and choice is not None:
        probability = _float_or_none(probabilities.get(str(choice)))

    step_type = reason_code = target = tool_name = None
    valid: bool | None = None
    verdict: Mapping[str, Any] | None = None
    try:
        decision = parse_decision(
            reply.text,
            observation["request_id"],
            observation["expected_case_version"],
            patient_source=patient_source,
        )
    except (ValueError, KeyError, TypeError):
        valid = False
    else:
        valid = True
        step_type = decision.step_type
        reason_code = getattr(decision, "reason_code", None)
        target = getattr(decision, "target", None)
        tool_name = getattr(decision, "tool_name", None)
        if policy is not None:
            verdict = policy(decision)

    # The decider's own proposal is scored separately: an abstaining leg executes the inner
    # provider's decision, so scoring only the acted decision would hide what the gate blocked.
    proposed = registered.get("mapped_decision")
    if not isinstance(proposed, dict):
        proposed = provenance.get("mapped_decision")
    proposed_verdict: Mapping[str, Any] | None = None
    if isinstance(proposed, dict) and policy is not None:
        try:
            proposed_decision = parse_decision(
                json.dumps(proposed),
                observation["request_id"],
                observation["expected_case_version"],
                patient_source=patient_source,
            )
        except (ValueError, KeyError, TypeError):
            proposed_verdict = None
        else:
            proposed_verdict = policy(proposed_decision)

    return LegOutcome(
        leg=leg,
        status=REPLAY,
        step_type=step_type,
        reason_code=reason_code,
        target=target,
        tool_name=tool_name,
        contract_valid=valid,
        policy=(verdict or {}).get("decision"),
        policy_codes=tuple((verdict or {}).get("reason_codes") or ()),
        confidence=_float_or_none(confidence),
        probability=probability,
        probabilities=probabilities if isinstance(probabilities, dict) else None,
        choice=str(choice) if choice is not None else None,
        abstained=bool(provenance.get("fell_back")),
        fallback_reason=provenance.get("fallback_reason"),
        bypass_reason=provenance.get("bypass_reason"),
        proposed=proposed if isinstance(proposed, dict) else None,
        proposed_policy=(proposed_verdict or {}).get("decision"),
        proposed_policy_codes=tuple((proposed_verdict or {}).get("reason_codes") or ()),
        latency_ms=reply.latency_ms
        if reply.latency_ms is not None
        else int((time.monotonic() - started) * 1000),
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        cost_usd=cost_usd(leg, reply.input_tokens, reply.output_tokens),
    )


class CaptureProvider:
    """Record the request/reply pair at the decision point, then delegate unchanged.

    The observation is still current when this runs, which is what makes a later
    `policy_for` verdict meaningful. Records are written outside the repository and never
    contain a credential; the decision text is the model's own output.
    """

    name = "lane-b-capture"

    def __init__(
        self,
        inner: Any,
        sink: list[dict],
        *,
        meta: Mapping[str, Any] | None = None,
        path: str | Path | None = None,
    ) -> None:
        self.inner = inner
        self.sink = sink
        self.meta = dict(meta or {})
        self.path = Path(path) if path else None

    def decide(self, observation: dict, *, repair: bool = False) -> Any:
        try:
            reply = self.inner.decide(observation, repair=repair)
        except ModelError as exc:
            self._record(observation, None, repair, exc.code)
            raise
        self._record(observation, reply, repair, None)
        return reply

    def _record(self, observation: dict, reply: Any, repair: bool, error_code: str | None) -> None:
        row = {
            "observation": observation,
            "reply_text": getattr(reply, "text", None),
            "repair": repair,
            "error_code": error_code,
            **self.meta,
        }
        self.sink.append(row)
        if self.path is not None:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


# -- corpus ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayRow:
    """One recorded decision point plus every leg's outcome on that same observation."""

    index: int
    role: str
    phase: str | None
    repair: bool
    legal_step_types: tuple[str, ...]
    context: dict
    observation: dict
    outcomes: dict[str, LegOutcome]

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "role": self.role,
            "phase": self.phase,
            "repair": self.repair,
            "legal_step_types": list(self.legal_step_types),
            "context": self.context,
            "observation": self.observation,
            "outcomes": {leg: outcome.as_dict() for leg, outcome in self.outcomes.items()},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReplayRow:
        return cls(
            index=int(value["index"]),
            role=str(value["role"]),
            phase=value.get("phase"),
            repair=bool(value.get("repair")),
            legal_step_types=tuple(value.get("legal_step_types") or ()),
            context=dict(value.get("context") or {}),
            observation=dict(value["observation"]),
            outcomes={
                leg: LegOutcome.from_dict(outcome)
                for leg, outcome in (value.get("outcomes") or {}).items()
            },
        )


def write_rows(path: str | Path, rows: Iterable[ReplayRow], *, append: bool = False) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    mode = "a" if append else "w"
    with open(target, mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            count += 1
    return count


def read_rows(path: str | Path) -> list[ReplayRow]:
    rows: list[ReplayRow] = []
    with open(Path(path), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(ReplayRow.from_dict(json.loads(line)))
    return rows


def corpus_distribution(rows: Sequence[ReplayRow]) -> dict:
    """What the corpus covers, and which legal classes it never exercises."""
    legal: Counter = Counter()
    observed: Counter = Counter()
    for row in rows:
        legal.update(row.legal_step_types)
        for outcome in row.outcomes.values():
            if outcome.step_type:
                observed[outcome.step_type] += 1
    return {
        "observations": len(rows),
        "by_role": dict(sorted(Counter(row.role for row in rows).items())),
        "by_phase": dict(sorted(Counter(row.phase or "unknown" for row in rows).items())),
        "legal_step_types": dict(sorted(legal.items())),
        "observed_step_types": dict(sorted(observed.items())),
        "uncovered_legal_step_types": sorted(set(legal) - set(observed)),
        "repair_observations": sum(1 for row in rows if row.repair),
    }


# -- aggregation -------------------------------------------------------------------------


def leg_summary(rows: Sequence[ReplayRow], leg: str) -> dict:
    outcomes = [row.outcomes[leg] for row in rows if leg in row.outcomes]
    ran = [outcome for outcome in outcomes if outcome.status == REPLAY]
    error = [outcome for outcome in outcomes if outcome.status == ERROR]
    skipped_rows = [outcome for outcome in outcomes if outcome.status == SKIPPED]
    valid = [outcome for outcome in ran if outcome.contract_valid]
    allowed = [outcome for outcome in valid if outcome.policy == "ALLOW"]
    denied = [outcome for outcome in valid if outcome.policy == "DENY"]
    acted = [outcome for outcome in ran if not outcome.abstained]
    fallbacks: Counter = Counter(
        outcome.fallback_reason or outcome.bypass_reason or "unspecified"
        for outcome in ran
        if outcome.abstained
    )
    latencies = [outcome.latency_ms for outcome in ran if outcome.latency_ms is not None]
    return {
        "attempted": len(outcomes),
        "ran": len(ran),
        "errors": len(error),
        "skipped": len(skipped_rows),
        "error_codes": dict(sorted(Counter(o.error_code for o in error if o.error_code).items())),
        "contract_validity_rate": rate(len(valid), len(ran)),
        "policy_allow_rate": rate(len(allowed), len(ran)),
        "policy_deny_rate": rate(len(denied), len(ran)),
        "policy_allow_rate_when_valid": rate(len(allowed), len(valid)),
        "abstain_rate": rate(len(ran) - len(acted), len(ran)),
        "fallback_causes": dict(sorted(fallbacks.items())),
        "step_types": dict(sorted(Counter(o.step_type for o in valid).items())),
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "input_tokens": sum(o.input_tokens or 0 for o in ran) or None,
        "output_tokens": sum(o.output_tokens or 0 for o in ran) or None,
        "cost_usd": round(sum(o.cost_usd or 0.0 for o in ran), 6),
    }


def _comparable(row: ReplayRow, leg: str) -> bool:
    outcome = row.outcomes.get(leg)
    return bool(outcome and outcome.eligible)


def agreement(rows: Sequence[ReplayRow], a: str, b: str) -> dict:
    """Agreement over observations where both legs produced a contract-valid decision."""
    compared = [row for row in rows if _comparable(row, a) and _comparable(row, b)]
    step_type = step_reason = full = 0
    breakdown: dict[str, Counter] = defaultdict(Counter)
    for row in compared:
        left = row.outcomes[a].chosen
        right = row.outcomes[b].chosen
        if left[0] == right[0]:
            step_type += 1
        if left[:2] == right[:2]:
            step_reason += 1
        if left == right:
            full += 1
        breakdown[left[0]][right[0]] += 1
    return {
        "n_compared": len(compared),
        "n_dropped": len(rows) - len(compared),
        "step_type": rate(step_type, len(compared)),
        "step_type_and_reason": rate(step_reason, len(compared)),
        "full": rate(full, len(compared)),
        "disagreements_by_step_type": {
            left: dict(sorted(counter.items())) for left, counter in sorted(breakdown.items())
        },
    }


def agreement_when_decider_acted(rows: Sequence[ReplayRow], decider: str, other: str) -> dict:
    acted = [
        row
        for row in rows
        if row.outcomes.get(decider)
        and row.outcomes[decider].status == REPLAY
        and not row.outcomes[decider].abstained
    ]
    return agreement(acted, decider, other)


def aggregate(
    rows: Sequence[ReplayRow], *, decider_legs: Sequence[str] = (), llm_leg: str | None = None
) -> dict:
    legs = sorted({leg for row in rows for leg in row.outcomes})
    pairs = [(decider, llm_leg) for decider in decider_legs if llm_leg]
    return {
        "observations": len(rows),
        "legs": {leg: leg_summary(rows, leg) for leg in legs},
        "agreement": {
            f"{a}|{b}": agreement(rows, a, b) for a, b in pairs if a in legs and b in legs
        },
        "agreement_when_decider_acted": {
            f"{a}|{b}": agreement_when_decider_acted(rows, a, b)
            for a, b in pairs
            if a in legs and b in legs
        },
        "price_basis": PRICE_BASIS,
    }


# -- order stability ---------------------------------------------------------------------


def _permutations(size: int, count: int, seed: int) -> list[list[int]]:
    canonical = list(range(1, size + 1))
    if count <= 1:
        return [canonical]
    rng = random.Random(seed)
    orders = [canonical]
    while len(orders) < count:
        candidate = list(canonical)
        rng.shuffle(candidate)
        if candidate not in orders:
            orders.append(candidate)
    return orders


def _identity_at(position: Any, order: Sequence[int], identity: Mapping[str, Any]) -> str | None:
    """Map a presentation key (1-based position) back to the canonical option identity."""
    if position is None or not str(position).isdigit():
        return None
    index = int(position)
    if not 1 <= index <= len(order):
        return None
    canonical_key = str(order[index - 1])
    if canonical_key not in identity:
        return None
    return label(identity[canonical_key])


def order_stability(
    call: Callable[[dict], Any],
    observation: Mapping[str, Any],
    *,
    leg: str = LEG_KEV_4B,
    n: int = 6,
    seed: int = 0,
    charge: Callable[[str], None] | None = None,
    record: str | Path | None = None,
) -> dict:
    """Re-offer the identical option set in `n` orders and measure argmax flips.

    Uses the measurement-only `_decider_option_order` permutation read by `derive_options`,
    so the criteria text and the option set are unchanged; only the presentation order and
    the resulting option keys move.
    """
    from forget_lah.runtime.decider import derive_options

    canonical = derive_options(dict(observation))
    candidates = list(canonical.candidates)
    if len(candidates) < 2:
        return {"status": SKIPPED, "reason": "fewer_than_two_options", "options": len(candidates)}
    identity = {candidate.key: signature(candidate.spec) for candidate in candidates}
    runs = []
    for order in _permutations(len(candidates), n, seed):
        shuffled = dict(observation)
        shuffled["_decider_option_order"] = order
        outcome = evaluate_leg(leg, call, shuffled, charge=charge, record=record)
        chosen = outcome.proposed_choice or outcome.chosen
        by_identity: dict[str, float] = {}
        for key, value in (outcome.probabilities or {}).items():
            if not str(key).isdigit():
                continue
            position = int(key)
            if not 1 <= position <= len(order):
                continue
            canonical_key = str(order[position - 1])
            if canonical_key in identity:
                by_identity[label(identity[canonical_key])] = _float_or_none(value)
        answer_identity = _identity_at(outcome.choice, order, identity)
        runs.append(
            {
                "order": order,
                "status": outcome.status,
                "abstained": outcome.abstained,
                "chosen": label(chosen) if chosen else None,
                # The decider's own answer, mapped through this permutation. It exists whether
                # or not the gate accepted, so it measures the decider rather than the inner
                # provider that an abstention falls back to.
                "answer_identity": answer_identity,
                "answer_probability": by_identity.get(answer_identity) if answer_identity else None,
                "probability_by_identity": {
                    name: value for name, value in by_identity.items() if value is not None
                },
            }
        )
    acted = [run for run in runs if run["chosen"]]
    answered = [run for run in runs if run["answer_identity"]]
    sample = answered or acted
    if len(sample) < 2:
        return {
            "status": SKIPPED,
            "reason": "leg_did_not_act_twice",
            "runs": runs,
            "options": len(candidates),
        }
    modal = Counter(run["chosen"] for run in acted).most_common(1)[0][0] if acted else None
    answer_modal = (
        Counter(run["answer_identity"] for run in answered).most_common(1)[0][0]
        if answered
        else None
    )
    spread = {}
    for name in {name for run in acted for name in run["probability_by_identity"]}:
        values = [
            run["probability_by_identity"][name]
            for run in acted
            if name in run["probability_by_identity"]
        ]
        spread[name] = round(max(values) - min(values), 4)
    return {
        "status": REPLAY,
        "leg": leg,
        "n": len(runs),
        "options": len(candidates),
        "distinct_choices": len({run["chosen"] for run in acted}),
        "modal_choice": modal,
        "flip_rate_vs_canonical": rate(
            sum(1 for run in acted if run["chosen"] != acted[0]["chosen"]), len(acted)
        )
        if acted
        else None,
        "flip_rate_vs_modal": rate(sum(1 for run in acted if run["chosen"] != modal), len(acted))
        if modal
        else None,
        # Decider-only view: the identity the model itself answered, independent of the gate.
        "answered": len(answered),
        "distinct_answer_choices": len({run["answer_identity"] for run in answered}),
        "answer_modal_choice": answer_modal,
        "answer_flip_rate_vs_modal": rate(
            sum(1 for run in answered if run["answer_identity"] != answer_modal), len(answered)
        ),
        "gate_abstain_rate": rate(sum(1 for run in runs if run["abstained"]), len(runs)),
        "probability_spread": spread,
        "runs": runs,
    }


def _raw_answer(row: ReplayRow, leg: str) -> dict | None:
    """Reconstruct the System One answer body from the recorded outcome, or None."""
    outcome = row.outcomes.get(leg)
    if outcome is None or outcome.choice is None or not isinstance(outcome.probabilities, dict):
        return None
    return {
        "choice": outcome.choice,
        "confidence": outcome.confidence,
        "probabilities": outcome.probabilities,
    }


DEFAULT_SWEEPS: tuple[dict, ...] = (
    *({"mode": "confidence", "min_confidence": floor} for floor in (0.0, 0.2, 0.3, 0.4, 0.5)),
    *({"mode": "probability", "min_probability": floor} for floor in (0.0, 0.2, 0.3, 0.4, 0.5)),
    *(
        {"mode": "joint", "min_confidence": 0.3, "min_probability": 0.4, "min_margin": margin}
        for margin in (0.0, 0.1, 0.2)
    ),
)


def gate_sweep(
    rows: Sequence[ReplayRow],
    leg: str = LEG_KEV_4B,
    *,
    llm_leg: str | None = None,
    sweeps: Sequence[Mapping[str, Any]] = DEFAULT_SWEEPS,
) -> list[dict]:
    """Replay the real gate over recorded answers instead of spending live calls.

    Thresholds are chosen from measurement: coverage, the accepted decisions' own policy
    verdict and their agreement with the LLM leg. `_valid_choice` is the same function the
    runtime uses, so the sweep cannot drift from shipped behaviour.
    """
    from forget_lah.runtime.decider import DeciderGate, _valid_choice

    answerable = [row for row in rows if _raw_answer(row, leg) is not None]
    results = []
    for sweep in sweeps:
        gate = DeciderGate(
            mode=str(sweep.get("mode", "confidence")),
            min_confidence=float(sweep.get("min_confidence", 0.0)),
            min_probability=float(sweep.get("min_probability", 0.0)),
            min_margin=float(sweep.get("min_margin", 0.0)),
        )
        accepted: list[ReplayRow] = []
        blocked: Counter = Counter()
        for row in answerable:
            answer = _raw_answer(row, leg)
            reason = _valid_choice(answer, set(answer["probabilities"]), gate)
            if reason is None:
                accepted.append(row)
            else:
                blocked[reason] += 1
        # An accepted answer is the decision that executes (the decider authors it in
        # non-shadow mode), so the proposal's own verdict is the acted verdict. The returned
        # provenance only carries `mapped_decision` in shadow mode, so both are consulted.
        allowed = [
            row
            for row in accepted
            if (row.outcomes[leg].proposed_policy or row.outcomes[leg].policy) == "ALLOW"
        ]
        entry: dict[str, Any] = {
            "gate": gate.as_dict(),
            "answerable": len(answerable),
            "accepted": len(accepted),
            "coverage": rate(len(accepted), len(answerable)),
            "blocked_reasons": dict(sorted(blocked.items())),
            "accepted_policy_allow_rate": rate(len(allowed), len(accepted)),
            "accepted_distinct_choices": len(
                {label(row.outcomes[leg].proposed_choice) for row in accepted}
            ),
        }
        if llm_leg:
            entry["accepted_agreement_with_llm"] = agreement(accepted, leg, llm_leg)
        results.append(entry)
    return results


# -- scorecard ---------------------------------------------------------------------------


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(cells) + " |" for cells in rows)
    return "\n".join(lines)


def scorecard_markdown(results: Mapping[str, Any]) -> str:
    """Render the measured results. Sections with no measurement say so explicitly."""
    corpus = results.get("corpus") or {}
    replay = results.get("replay") or {}
    legs = replay.get("legs") or {}
    budget = results.get("budget") or {}
    lines = [
        "# Lane B scorecard — LLM vs openjev decider (forget-lah)",
        "",
        f"Commands: `{results.get('command', 'n/a')}`",
        "",
        "## Corpus",
        "",
    ]
    if corpus:
        lines.append(
            f"{corpus.get('observations', 0)} recorded decision points, "
            f"roles {corpus.get('by_role', {})}, "
            f"phases {corpus.get('by_phase', {})}."
        )
        uncovered = corpus.get("uncovered_legal_step_types") or []
        lines.append(
            f"Never exercised: {', '.join(uncovered) if uncovered else 'none of the legal types'}."
        )
    else:
        lines.append("No corpus was captured.")
    lines += ["", "## Paired replay — per leg", ""]
    if legs:
        rows = []
        for leg, summary in legs.items():
            rows.append(
                [
                    leg,
                    str(summary.get("ran")),
                    _percent(summary.get("contract_validity_rate")),
                    _percent(summary.get("policy_allow_rate")),
                    _percent(summary.get("abstain_rate")),
                    str(summary.get("latency_ms", {}).get("p50")),
                    str(summary.get("input_tokens") or 0),
                    str(summary.get("output_tokens") or 0),
                    "free" if not summary.get("cost_usd") else f"${summary['cost_usd']:.4f}",
                ]
            )
        lines.append(
            _table(
                [
                    "leg",
                    "ran",
                    "contract valid",
                    "policy ALLOW",
                    "abstain",
                    "p50 ms",
                    "in tok",
                    "out tok",
                    "cost",
                ],
                rows,
            )
        )
        fallbacks = {
            leg: summary.get("fallback_causes")
            for leg, summary in legs.items()
            if summary.get("fallback_causes")
        }
        if fallbacks:
            lines += ["", f"Fallback causes: `{json.dumps(fallbacks, sort_keys=True)}`"]
    else:
        lines.append("No leg ran.")
    lines += ["", "## Agreement (contract-valid decisions on identical observations)", ""]
    agreement_map = replay.get("agreement") or {}
    if agreement_map:
        rows = [
            [
                pair,
                str(value.get("n_compared")),
                _percent(value.get("step_type")),
                _percent(value.get("step_type_and_reason")),
                _percent(value.get("full")),
            ]
            for pair, value in agreement_map.items()
        ]
        lines.append(_table(["pair", "n", "step type", "type+reason", "full"], rows))
        lines += ["", "Disagreement by step type:"]
        for pair, value in agreement_map.items():
            lines.append(
                f"- `{pair}`: `{json.dumps(value.get('disagreements_by_step_type'), sort_keys=True)}`"
            )
        lines.append(
            "Agreement is not accuracy: two legs agreeing on a wrong step is not evidence of quality."
        )
    else:
        lines.append("No pair produced a contract-valid decision on the same observation.")
    lines += ["", "## Order stability (decider only)", ""]
    stability = results.get("stability") or {}
    if stability.get("status") == REPLAY:
        lines.append(
            f"{stability.get('n')} shuffled presentations of "
            f"{stability.get('options')} options: flip rate vs canonical "
            f"{_percent(stability.get('flip_rate_vs_canonical'))}, vs modal "
            f"{_percent(stability.get('flip_rate_vs_modal'))}, "
            f"{stability.get('distinct_choices')} distinct choices, "
            f"probability spread `{json.dumps(stability.get('probability_spread'), sort_keys=True)}`."
        )
    else:
        lines.append(f"Not measured: {stability.get('reason', 'no stability run')}.")
    lines += ["", "## Closed loop", ""]
    arms = results.get("closed_loop") or []
    if arms:
        rows = [
            [
                arm.get("arm", ""),
                arm.get("status", ""),
                str(arm.get("steps") or 0),
                str(arm.get("repairs") or 0),
                str(arm.get("events") or 0),
                str(arm.get("pause_outcomes") or 0),
                str(arm.get("failure_codes") or {}),
                str(arm.get("calls") or {}),
            ]
            for arm in arms
        ]
        lines.append(
            _table(
                ["arm", "run status", "steps", "repairs", "events", "pauses", "failures", "calls"],
                rows,
            )
        )
    else:
        lines.append("No closed-loop arm ran.")
    lines += ["", "## Budget", "", f"`{json.dumps(budget, sort_keys=True)}`"]
    lines += ["", "## Verdict", ""]
    lines.append(results.get("verdict") or "No verdict recorded.")
    return "\n".join(lines) + "\n"


__all__ = [
    "ANTHROPIC_PRICE_USD_PER_MTOK",
    "BILLABLE_LEGS",
    "CaptureProvider",
    "CallLedger",
    "DEFAULT_SWEEPS",
    "ERROR",
    "LEG_ANTHROPIC",
    "LEG_HOSTED",
    "LEG_KEV_27B",
    "LEG_KEV_4B",
    "LEG_MOCK",
    "PRICE_BASIS",
    "REPLAY",
    "ReplayRow",
    "SKIPPED",
    "LegOutcome",
    "aggregate",
    "agreement",
    "agreement_when_decider_acted",
    "corpus_distribution",
    "cost_usd",
    "evaluate_leg",
    "gate_sweep",
    "label",
    "leg_summary",
    "order_stability",
    "read_rows",
    "scorecard_markdown",
    "signature",
    "skipped",
    "write_rows",
]
