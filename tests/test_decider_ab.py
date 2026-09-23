"""Lane B acceptance tests for the A/B harness.

Hermetic by construction: every leg is a stub or the deterministic mock, no test here
performs live inference, and every measured number is asserted against hand-computed maths.
"""

import json

import pytest

from forget_lah.db import uid
from forget_lah.runtime import decider_ab as ab
from forget_lah.runtime.decider import DeciderModelReply, derive_options
from forget_lah.runtime.provider import MockModel, ModelError, ModelReply

OPTIONS = {"1": 0.45, "2": 0.3, "3": 0.15, "BLOCKED": 0.1}


def coordinator_observation(**changes):
    observation = {
        "role": "coordinator",
        "request_id": uid(),
        "expected_case_version": 1,
        "goal": "Advance the follow-up goal for the latest event.",
        "latest_event": {"id": uid(), "kind": "started", "content": ""},
        "tools": [],
        "returned_specialists": [],
        "specialist_reports": [],
        "handoff": None,
    }
    observation.update(changes)
    return observation


def decision_document(observation, **changes):
    document = {
        "request_id": observation["request_id"],
        "expected_case_version": observation["expected_case_version"],
        "step_type": "ESCALATE",
        "reason_code": "AMBIGUOUS_REPLY",
    }
    document.update(changes)
    return document


class StubCall:
    def __init__(self, reply=None, error=None):
        self.calls = []
        self._reply = reply
        self._error = error

    def __call__(self, observation):
        self.calls.append(observation)
        if self._error is not None:
            raise self._error
        return self._reply


class StubPassThrough:
    """A provider-shaped stub for the capture wrapper."""

    def __init__(self, reply=None, error=None):
        self.calls = []
        self._reply = reply
        self._error = error

    def decide(self, observation, *, repair=False):
        self.calls.append((observation, repair))
        if self._error is not None:
            raise self._error
        return self._reply


def outcome(leg, **changes):
    values = {
        "leg": leg,
        "status": ab.REPLAY,
        "step_type": "ESCALATE",
        "reason_code": "AMBIGUOUS_REPLY",
        "contract_valid": True,
        "policy": "ALLOW",
    }
    values.update(changes)
    return ab.LegOutcome(**values)


def row(index, **outcomes):
    return ab.ReplayRow(
        index=index,
        role="coordinator",
        phase="demo_reply",
        repair=False,
        legal_step_types=("ESCALATE", "TOOL"),
        context={"request_id": uid()},
        observation=coordinator_observation(),
        outcomes=outcomes,
    )


# -- capture -----------------------------------------------------------------------------


def test_capture_provider_records_then_delegates(tmp_path):
    observation = coordinator_observation()
    reply = ModelReply(json.dumps(decision_document(observation)), 3, 4, 1)
    inner = StubPassThrough(reply=reply)
    sink: list[dict] = []
    capture = ab.CaptureProvider(inner, sink, meta={"arm": "paired"}, path=tmp_path / "c.jsonl")

    returned = capture.decide(observation, repair=True)

    assert returned is reply, "the wrapper must return the inner reply unchanged"
    assert inner.calls == [(observation, True)]
    assert sink[0]["observation"] is observation
    assert sink[0]["reply_text"] == reply.text
    assert sink[0]["arm"] == "paired"
    assert sink[0]["error_code"] is None
    written = [json.loads(line) for line in (tmp_path / "c.jsonl").read_text().splitlines()]
    assert written == sink


def test_capture_provider_records_failure_and_reraises(tmp_path):
    inner = StubPassThrough(error=ModelError("MODEL_TIMEOUT", retryable=True))
    sink: list[dict] = []
    capture = ab.CaptureProvider(inner, sink)

    with pytest.raises(ModelError):
        capture.decide(coordinator_observation())

    assert sink[0]["error_code"] == "MODEL_TIMEOUT"
    assert sink[0]["reply_text"] is None


# -- budget ------------------------------------------------------------------------------


def test_ledger_counts_only_billable_legs():
    ledger = ab.CallLedger(limit=3)
    ledger.charge(ab.LEG_KEV_4B)
    ledger.charge(ab.LEG_ANTHROPIC)
    ledger.charge(ab.LEG_ANTHROPIC)

    assert ledger.billable == 2
    assert ledger.remaining == 1
    assert ledger.fits(1)
    assert not ledger.fits(2)
    assert ledger.as_dict()["by_leg"] == {ab.LEG_ANTHROPIC: 2, ab.LEG_KEV_4B: 1}


# -- evaluate_leg ------------------------------------------------------------------------


def test_evaluate_leg_scores_contract_validity_and_policy():
    observation = coordinator_observation()
    document = decision_document(observation)
    call = StubCall(ModelReply(json.dumps(document), 10, 5, 7))
    verdicts = []

    def policy(decision):
        verdicts.append(decision.step_type)
        return {"decision": "DENY", "reason_codes": ["STALE_OR_WRONG_REQUEST"]}

    scored = ab.evaluate_leg(ab.LEG_KEV_4B, call, observation, policy=policy)

    assert scored.status == ab.REPLAY
    assert scored.contract_valid is True
    assert scored.chosen == ("ESCALATE", "AMBIGUOUS_REPLY", "")
    assert scored.policy == "DENY"
    assert scored.policy_codes == ("STALE_OR_WRONG_REQUEST",)
    assert scored.latency_ms == 7
    assert scored.cost_usd == 0.0
    assert verdicts == ["ESCALATE"]


def test_evaluate_leg_rejects_invalid_text_without_a_policy_verdict():
    call = StubCall(ModelReply("{not json", 1, 1, 1))
    verdicts = []

    scored = ab.evaluate_leg(
        ab.LEG_ANTHROPIC, call, coordinator_observation(), policy=lambda _d: verdicts.append(1)
    )

    assert scored.contract_valid is False
    assert scored.policy is None
    assert verdicts == []
    assert scored.cost_usd == pytest.approx(1.8e-05), "an invalid reply is still a paid call"


def test_evaluate_leg_records_transport_errors_and_prices_tokens():
    error = ab.evaluate_leg(
        ab.LEG_ANTHROPIC,
        StubCall(error=ModelError("MODEL_HTTP_500", retryable=True)),
        coordinator_observation(),
    )
    assert error.status == ab.ERROR
    assert error.error_code == "MODEL_HTTP_500"

    observation = coordinator_observation()
    call = StubCall(ModelReply(json.dumps(decision_document(observation)), 1_000_000, 1_000_000, 5))
    priced = ab.evaluate_leg(ab.LEG_ANTHROPIC, call, observation)
    assert priced.cost_usd == pytest.approx(18.0)


def test_evaluate_leg_separates_the_proposal_from_the_acted_decision():
    observation = coordinator_observation()
    inner_document = decision_document(
        observation, step_type="TOOL", reason_code="READ_SOURCE", tool_name="read_followup_context"
    )
    proposal = decision_document(observation)
    reply = DeciderModelReply(
        text=json.dumps(inner_document),
        input_tokens=1,
        output_tokens=1,
        latency_ms=2,
        provenance={
            "fell_back": True,
            "fallback_reason": "low_confidence",
            "mapped_decision": proposal,
            "choice": "1",
            "confidence": 0.31,
            "probabilities": dict(OPTIONS),
        },
    )
    policies = []

    def policy(decision):
        policies.append(decision.step_type)
        return {"decision": "ALLOW", "reason_codes": []}

    scored = ab.evaluate_leg(ab.LEG_KEV_4B, StubCall(reply), observation, policy=policy)

    assert scored.abstained is True
    assert scored.fallback_reason == "low_confidence"
    assert scored.chosen == ("TOOL", "READ_SOURCE", "read_followup_context")
    assert scored.proposed_choice == ("ESCALATE", "AMBIGUOUS_REPLY", "")
    assert scored.choice == "1"
    assert scored.probability == 0.45
    assert scored.proposed_policy == "ALLOW"
    assert policies == ["TOOL", "ESCALATE"], "both the acted decision and the proposal are scored"


# -- aggregation -------------------------------------------------------------------------


def test_aggregate_reports_rates_agreement_and_fallbacks():
    rows = [
        row(
            1,
            **{
                ab.LEG_KEV_4B: outcome(ab.LEG_KEV_4B, confidence=0.9),
                ab.LEG_ANTHROPIC: outcome(
                    ab.LEG_ANTHROPIC,
                    step_type="TOOL",
                    reason_code="READ_SOURCE",
                    tool_name="read_followup_context",
                ),
            },
        ),
        row(
            2,
            **{
                ab.LEG_KEV_4B: outcome(
                    ab.LEG_KEV_4B, abstained=True, fallback_reason="low_confidence", policy="DENY"
                ),
                ab.LEG_ANTHROPIC: outcome(ab.LEG_ANTHROPIC, contract_valid=False, policy=None),
            },
        ),
        row(
            3,
            **{
                ab.LEG_KEV_4B: outcome(ab.LEG_KEV_4B),
                ab.LEG_ANTHROPIC: outcome(ab.LEG_ANTHROPIC, latency_ms=900, cost_usd=0.01),
            },
        ),
    ]

    summary = ab.aggregate(rows, decider_legs=[ab.LEG_KEV_4B], llm_leg=ab.LEG_ANTHROPIC)

    decider = summary["legs"][ab.LEG_KEV_4B]
    assert decider["ran"] == 3
    assert decider["contract_validity_rate"] == 1.0
    assert decider["policy_allow_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert decider["abstain_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert decider["fallback_causes"] == {"low_confidence": 1}

    llm = summary["legs"][ab.LEG_ANTHROPIC]
    assert llm["contract_validity_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert llm["policy_allow_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert llm["cost_usd"] == 0.01

    agreement = summary["agreement"][f"{ab.LEG_KEV_4B}|{ab.LEG_ANTHROPIC}"]
    assert agreement["n_compared"] == 2, "an invalid LLM reply is not comparable"
    assert agreement["n_dropped"] == 1
    assert agreement["step_type"] == 0.5
    assert agreement["step_type_and_reason"] == 0.5
    assert agreement["full"] == 0.5
    assert agreement["disagreements_by_step_type"] == {"ESCALATE": {"TOOL": 1, "ESCALATE": 1}}

    acted = summary["agreement_when_decider_acted"][f"{ab.LEG_KEV_4B}|{ab.LEG_ANTHROPIC}"]
    assert acted["n_compared"] == 2


# -- gate sweep --------------------------------------------------------------------------


def gate_outcome(**changes):
    values = {
        "leg": ab.LEG_KEV_4B,
        "status": ab.REPLAY,
        "contract_valid": True,
        "choice": "1",
        "confidence": 0.31,
        "probabilities": dict(OPTIONS),
        "proposed": {"step_type": "ESCALATE", "reason_code": "AMBIGUOUS_REPLY"},
        "proposed_policy": "ALLOW",
    }
    values.update(changes)
    return ab.LegOutcome(**values)


def sweep(rows, **sweep):
    return ab.gate_sweep(rows, ab.LEG_KEV_4B, sweeps=[sweep])[0]


def test_gate_sweep_replays_the_shipped_gate():
    rows = [row(1, **{ab.LEG_KEV_4B: gate_outcome()})]

    assert sweep(rows, mode="confidence", min_confidence=0.5)["blocked_reasons"] == {
        "low_confidence": 1
    }
    assert sweep(rows, mode="confidence", min_confidence=0.2)["accepted"] == 1
    assert sweep(rows, mode="probability", min_probability=0.4)["accepted"] == 1
    assert sweep(rows, mode="probability", min_probability=0.5)["blocked_reasons"] == {
        "low_probability": 1
    }


def test_gate_sweep_treats_blocked_as_a_margin_competitor():
    rows = [row(1, **{ab.LEG_KEV_4B: gate_outcome()})]

    accepted = sweep(rows, mode="joint", min_confidence=0.3, min_probability=0.4, min_margin=0.1)
    blocked = sweep(rows, mode="joint", min_confidence=0.3, min_probability=0.4, min_margin=0.2)

    assert accepted["accepted"] == 1
    assert accepted["coverage"] == 1.0
    assert accepted["accepted_policy_allow_rate"] == 1.0
    assert blocked["blocked_reasons"] == {"low_margin": 1}


def test_gate_sweep_ignores_legs_without_a_raw_answer():
    rows = [
        row(1, **{ab.LEG_KEV_4B: gate_outcome()}),
        row(2, **{ab.LEG_KEV_4B: ab.skipped(ab.LEG_KEV_4B, "budget_subsample")}),
    ]

    entry = sweep(rows, mode="probability", min_probability=0.0)

    assert entry["answerable"] == 1
    assert entry["accepted"] == 1


# -- order stability ---------------------------------------------------------------------


def option_observation():
    observation = coordinator_observation(
        tools=[
            {
                "id": uid(),
                "role": "coordinator",
                "sequence": 1,
                "result": {
                    "tool_name": "read_followup_context",
                    "status": "succeeded",
                    "data": {},
                },
            }
        ],
        allowed_tools=["read_followup_context", "send_simulated_options"],
    )
    derived = derive_options(observation)
    assert len(derived.candidates) >= 2, "the fixture must expose a choice"
    return observation


class PositionalCall:
    """Chooses whichever candidate the presentation puts first."""

    def __init__(self, fixed=None):
        self.fixed = fixed

    def __call__(self, observation):
        candidates = list(derive_options(observation).candidates)
        if self.fixed is None:
            chosen = candidates[0]
        else:
            chosen = next(c for c in candidates if ab.signature(c.spec) == self.fixed)
        probabilities = {}
        for candidate in candidates:
            probabilities[candidate.key] = 0.1
        probabilities[chosen.key] = round(1.0 - 0.1 * (len(candidates) - 1), 2)
        return DeciderModelReply(
            text=json.dumps(chosen.spec),
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            provenance={
                "choice": chosen.key,
                "confidence": 0.9,
                "probabilities": probabilities,
                "mapped_decision": chosen.spec,
            },
        )


def test_order_stability_measuring_flips_and_spread():
    observation = option_observation()
    canonical = derive_options(observation)

    flipping = ab.order_stability(PositionalCall(), observation, leg=ab.LEG_KEV_4B, n=4, seed=7)

    assert flipping["status"] == ab.REPLAY
    assert flipping["options"] == len(canonical.candidates)
    assert flipping["n"] == 4
    assert flipping["flip_rate_vs_canonical"] is not None
    assert flipping["distinct_choices"] > 1, "position-first choices must move with the order"
    assert set(flipping["probability_spread"]) == {
        ab.label(ab.signature(candidate.spec)) for candidate in canonical.candidates
    }


def test_order_stability_is_zero_when_the_choice_is_identity_bound():
    observation = option_observation()
    candidates = derive_options(observation).candidates
    fixed = ab.signature(candidates[-1].spec)

    stable = ab.order_stability(
        PositionalCall(fixed=fixed), observation, leg=ab.LEG_KEV_4B, n=4, seed=3
    )

    assert stable["flip_rate_vs_canonical"] == 0.0
    assert stable["flip_rate_vs_modal"] == 0.0
    assert stable["distinct_choices"] == 1


def test_order_stability_skips_when_there_is_nothing_to_choose():
    observation = coordinator_observation()
    observation["role"] = "engagement"
    observation["simulation"] = {}
    derived = derive_options(observation)
    if len(derived.candidates) >= 2:
        pytest.skip("fixture exposes options; the single-option path is covered below")
    result = ab.order_stability(PositionalCall(), observation)
    assert result["status"] == ab.SKIPPED
    assert result["reason"] == "fewer_than_two_options"


# -- the measurement-only order seam ------------------------------------------------------


def test_option_order_seam_permutes_labels_but_not_the_option_set():
    observation = option_observation()
    baseline = derive_options(observation)
    baseline_specs = [ab.label(ab.signature(candidate.spec)) for candidate in baseline.candidates]

    reversed_order = list(range(len(baseline.candidates), 0, -1))
    shuffled = derive_options({**observation, "_decider_option_order": reversed_order})

    assert [ab.label(ab.signature(c.spec)) for c in shuffled.candidates] == list(
        reversed(baseline_specs)
    )
    assert [candidate.key for candidate in shuffled.candidates] == [
        str(index) for index in range(1, len(baseline.candidates) + 1)
    ]


def test_option_order_seam_ignores_malformed_permutations():
    observation = option_observation()
    baseline = derive_options(observation)

    for malformed in ([1, 2], "2,1,3", [1, 1, 3], [], None):
        result = derive_options({**observation, "_decider_option_order": malformed})
        assert [candidate.key for candidate in result.candidates] == [
            candidate.key for candidate in baseline.candidates
        ], f"{malformed!r} must not reorder the offer"


# -- artifacts ---------------------------------------------------------------------------


def test_rows_round_trip_through_jsonl(tmp_path):
    original = [
        row(1, **{ab.LEG_KEV_4B: outcome(ab.LEG_KEV_4B, policy_codes=("A",))}),
        row(2, **{ab.LEG_KEV_4B: ab.skipped(ab.LEG_KEV_4B, "budget_subsample")}),
    ]
    path = tmp_path / "corpus.jsonl"

    assert ab.write_rows(path, original) == 2
    loaded = ab.read_rows(path)

    assert [item.index for item in loaded] == [1, 2]
    assert loaded[0].outcomes[ab.LEG_KEV_4B].policy_codes == ("A",)
    assert loaded[1].outcomes[ab.LEG_KEV_4B].skip_reason == "budget_subsample"
    assert loaded[0].observation == original[0].observation


def test_corpus_distribution_names_the_uncovered_classes():
    rows = [
        row(1, **{ab.LEG_KEV_4B: outcome(ab.LEG_KEV_4B)}),
        ab.ReplayRow(
            index=2,
            role="engagement",
            phase=None,
            repair=True,
            legal_step_types=("TOOL", "WAIT"),
            context={},
            observation=coordinator_observation(),
            outcomes={
                ab.LEG_KEV_4B: outcome(ab.LEG_KEV_4B, step_type="TOOL", reason_code="READ_SOURCE")
            },
        ),
    ]

    distribution = ab.corpus_distribution(rows)

    assert distribution["observations"] == 2
    assert distribution["by_role"] == {"coordinator": 1, "engagement": 1}
    assert distribution["by_phase"] == {"demo_reply": 1, "unknown": 1}
    assert distribution["repair_observations"] == 1
    assert distribution["uncovered_legal_step_types"] == ["WAIT"]


def test_scorecard_marks_every_unmeasured_section():
    markdown = ab.scorecard_markdown(
        {
            "command": "uv run python -m forget_lah.runtime.decider_ab_run --dry-run",
            "corpus": {},
            "replay": {},
            "stability": {"status": ab.SKIPPED, "reason": "dry_run"},
            "closed_loop": [],
            "budget": {"limit": 40},
            "verdict": "no measurement",
        }
    )

    assert "No corpus was captured" in markdown
    assert "No leg ran" in markdown
    assert "Not measured: dry_run" in markdown
    assert "No closed-loop arm ran" in markdown
    assert "no measurement" in markdown


# -- the deterministic mock as a leg -----------------------------------------------------


def test_mock_leg_is_also_scoreable_without_network():
    observation = coordinator_observation(
        handoff={"accepted": True, "id": uid()},
    )
    scored = ab.evaluate_leg(ab.LEG_MOCK, MockModel().decide, observation)

    assert scored.status == ab.REPLAY
    assert scored.chosen[0] == "COMPLETE"


# -- gate inputs come from the decider register -------------------------------------------


def test_evaluate_leg_reads_gate_inputs_from_the_register(tmp_path):
    observation = coordinator_observation()
    register = tmp_path / "leg.jsonl"
    probabilities = {"1": 0.2, "2": 0.7, "BLOCKED": 0.1}

    class RegisterCall:
        def __call__(self, obs):
            record = {
                "confidence": 0.62,
                "probabilities": probabilities,
                "raw_answer": {
                    "type": "choice",
                    "choice": "2",
                    "confidence": 0.62,
                    "probabilities": probabilities,
                },
            }
            with open(register, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            return ModelReply(json.dumps(decision_document(observation)), 3, 4, 1)

    scored = ab.evaluate_leg(ab.LEG_KEV_4B, RegisterCall(), observation, record=register)

    assert scored.choice == "2", "the register answer is the only carrier of the choice"
    assert scored.confidence == pytest.approx(0.62)
    assert scored.probabilities == probabilities
    assert scored.probability == pytest.approx(0.7)


def test_evaluate_leg_treats_a_redacted_register_choice_as_absent(tmp_path):
    observation = coordinator_observation()
    register = tmp_path / "leg.jsonl"
    probabilities = {"1": 0.8, "2": 0.2}

    class RegisterCall:
        def __call__(self, obs):
            record = {
                "confidence": 0.4,
                "probabilities": probabilities,
                "raw_answer": {
                    "type": "choice",
                    "choice": "[REDACTED]",
                    "confidence": 0.4,
                    "probabilities": probabilities,
                },
            }
            with open(register, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            return DeciderModelReply(
                json.dumps(decision_document(observation)),
                1,
                1,
                1,
                provenance={"choice": "1", "probabilities": probabilities},
            )

    scored = ab.evaluate_leg(ab.LEG_KEV_4B, RegisterCall(), observation, record=register)

    assert scored.choice == "1", "an out-of-offer choice is redacted and must not be scored"
    assert scored.probability == pytest.approx(0.8)


# -- order stability measures the decider, not the fallback --------------------------------


class PositionalAnswerCall:
    """Answers whichever option is presented first and records it in the register."""

    def __init__(self, register):
        self.register = register

    def __call__(self, observation):
        candidates = list(derive_options(observation).candidates)
        first = candidates[0]
        probabilities = {candidate.key: 0.05 for candidate in candidates}
        probabilities[first.key] = round(1.0 - 0.05 * (len(candidates) - 1), 2)
        record = {
            "confidence": 0.9,
            "probabilities": probabilities,
            "raw_answer": {
                "type": "choice",
                "choice": first.key,
                "confidence": 0.9,
                "probabilities": probabilities,
            },
        }
        with open(self.register, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        # Deliberately unparsable: this isolates the decider's own answer from what is acted.
        return ModelReply("not a decision", 1, 1, 1)


def test_order_stability_reports_the_deciders_own_answer(tmp_path):
    register = tmp_path / "stability.jsonl"
    result = ab.order_stability(
        PositionalAnswerCall(register),
        option_observation(),
        leg=ab.LEG_KEV_4B,
        n=4,
        seed=7,
        record=register,
    )

    assert result["answered"] == 4, "the answer exists in the register whether or not it is acted"
    assert result["distinct_answer_choices"] > 1, "a position-first answer must move with the order"
    assert result["distinct_choices"] == 0, "nothing parsed as a decision, so nothing was acted"
    assert result["modal_choice"] is None
    assert result["answer_flip_rate_vs_modal"] > 0
    assert any(run["answer_probability"] for run in result["runs"])
