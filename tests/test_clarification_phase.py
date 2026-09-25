from forget_lah.runtime.provider import decision_formats_for


def _phase_observation() -> dict:
    """A coordinator observation in the simulator REVIEW_NEEDS phase after a patient reply."""
    return {
        "role": "coordinator",
        "simulation": {"enabled": True},
        "latest_event": {"kind": "demo_reply", "id": "m1", "reply_event_id": "m1"},
        "needs_reviewed": None,
        "returned_specialists": [],
        "clarification_count": 0,
        "allowed_tools": [],
    }


def test_clarify_is_offered_in_the_simulation_review_phase() -> None:
    """A reminder asks nothing, so a bare acknowledgement must be able to resolve to a clarification.

    Regression guard for the recorded ambiguous-family over-read (oracle_rubric.md W2b): the phase
    previously allowlisted only REVIEW_NEEDS and REPORT_SYMPTOMS, so CLARIFY was unreachable and the
    model forced an intent (CONFIRM) and then escalated.
    """
    formats = decision_formats_for(_phase_observation())
    assert "REVIEW_NEEDS" in formats
    assert "CLARIFY" in formats


def test_clarify_is_withheld_once_a_specialist_has_returned() -> None:
    observation = _phase_observation()
    observation["returned_specialists"] = ["preparation"]
    assert "CLARIFY" not in decision_formats_for(observation)


def test_clarify_is_withheld_after_two_clarifications() -> None:
    observation = _phase_observation()
    observation["clarification_count"] = 2
    assert "CLARIFY" not in decision_formats_for(observation)
