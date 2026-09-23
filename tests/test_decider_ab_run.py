"""Lane B runner tests: the per-arm budget guard and the decider key scoping.

Hermetic: no live inference, no network. The key scope is asserted on the environment the
decider wrapper would read, which is what the production endpoint rule consumes.
"""

import os

import pytest

from forget_lah.runtime import decider_ab as ab
from forget_lah.runtime import decider_ab_run as runner


def test_decider_key_is_presented_only_to_endpoints_allowed_to_carry_it(monkeypatch):
    monkeypatch.setenv("AGENT_DECIDER_API_KEY", "not-a-real-key")

    with runner._decider_key_scope("https://api.commandcode.ai/provider/v1/systemone"):
        assert os.environ["AGENT_DECIDER_API_KEY"] == "not-a-real-key"

    with runner._decider_key_scope("http://127.0.0.1:8011/v1/systemone"):
        assert "AGENT_DECIDER_API_KEY" not in os.environ

    with runner._decider_key_scope(None):
        assert "AGENT_DECIDER_API_KEY" not in os.environ

    assert os.environ["AGENT_DECIDER_API_KEY"] == "not-a-real-key", "the scope must restore"


def test_arm_allotment_counts_from_the_arms_own_start():
    ledger = ab.CallLedger(limit=40)
    for _ in range(3):
        ledger.charge(ab.LEG_ANTHROPIC)

    class Inner:
        """Provider-shaped stub: the arm wrapper calls `.decide`."""

        def __init__(self):
            self.seen = []

        def decide(self, observation, *, repair=False):
            self.seen.append(observation)
            return "ok"

    inner = Inner()
    provider = runner.CountingProvider(
        inner=inner,
        leg=ab.LEG_ANTHROPIC,
        ledger=ledger,
        allotment=2,
        start=3,
    )

    assert provider.decide({}) == "ok"
    assert provider.decide({}) == "ok"
    with pytest.raises(runner.BudgetStop):
        provider.decide({})

    assert len(inner.seen) == 2, "the refused call must not reach the inner provider"
    assert ledger.counts[ab.LEG_ANTHROPIC] == 5
