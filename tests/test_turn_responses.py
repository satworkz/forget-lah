import pytest
from test_patient_memory import NeedsModel
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator


@pytest.mark.parametrize(
    "scheduled,key,value,weekday",
    [
        ("2026-09-18T02:00:00+00:00", "excluded_weekdays", "5", "Friday"),
        ("2030-01-06T16:30:00+00:00", "excluded_weekdays", "6", "Monday"),
        ("2030-01-04T01:00:00+00:00", "excluded_minutes", "600", "Friday"),
    ],
)
def test_nonconflicting_preference_clarifies_current_appointment_once(
    simulated_runtime, scheduled, key, value, weekday
):
    runtime, tools, source, engine = simulated_runtime
    body = episode_body(source)
    body["scheduled_at"] = scheduled
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "I already told staff my preference. I am frustrated."
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(
        runtime, tools=tools, model=NeedsModel([(key, value, "future")], concern="I am frustrated")
    )
    result = view(runtime[1], case)
    replies = [m for m in result["patient_simulator"]["messages"] if m["kind"] != "reminder"]
    assert len(replies) == 1
    assert replies[0]["body"].startswith("I'm sorry")
    assert weekday in replies[0]["body"]
    assert "keep it, or choose another time" in replies[0]["body"]
    assert len(replies[0]["evidence"]["response_parts"]) == 2
    assert result["run"]["status"] == "waiting" and result["handoff"] is None
    assert source_count(engine) == 0


def test_explicit_change_is_not_overruled_by_nonconflicting_preference(simulated_runtime):
    runtime, tools, source, _ = simulated_runtime
    body = episode_body(source)
    body["scheduled_at"] = "2030-01-04T02:00:00+00:00"
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "Please change my appointment. No Saturdays."
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    import json

    from forget_lah.runtime.engine import claim_run, process_run
    from forget_lah.runtime.provider import ModelReply

    class ChangeModel(NeedsModel):
        def decide(self, obs, **kwargs):
            if obs.get("needs_reviewed") and not obs.get("barriers"):
                return ModelReply(
                    json.dumps(
                        dict(
                            request_id=obs["request_id"],
                            expected_case_version=obs["expected_case_version"],
                            step_type="ASSESS_BARRIERS",
                            reason_code="PATIENT_BARRIERS_REVIEWED",
                            reply_event_id=obs["latest_event"]["id"],
                            evidence_quotes=[text],
                            rejects_current_offer=True,
                            next_action="SEARCH_SLOTS",
                        )
                    )
                )
            return super().decide(obs, **kwargs)

    model = ChangeModel([("excluded_weekdays", "5", "future")], intent="CHANGE")
    claim = claim_run(runtime[0])
    assert claim is not None
    process_run(runtime[0], runtime[2], *claim, model=model, tools=tools)
    # Memory updates are internal evidence, not an early separate patient message.
    interim = view(runtime[1], case)
    assert len(interim["patient_simulator"]["messages"]) == 1
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)
    # Source fixture lists no slots. The outcome must not claim availability.
    replies = [m for m in result["patient_simulator"]["messages"] if m["kind"] != "reminder"]
    assert len(replies) == 1
    assert "no alternative slots" in replies[0]["body"]
    assert "slots are available now" not in replies[0]["body"]
    assert result["handoff"]["reason_code"] == "NO_AVAILABLE_SLOTS"
