"""Offline replay of semantic proposals from the failed multi-turn conversation.

These exercise orchestration and policy, not live language-model accuracy.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_adaptation import add_slot
from test_patient_memory import NeedsModel
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import ModelReply


class AvailabilityReplay(NeedsModel):
    def __init__(self, *, ambiguity="NONE", bound=None):
        super().__init__([], intent="CHANGE")
        self.ambiguity, self.bound = ambiguity, bound

    def decide(self, obs, **kwargs):
        response = super().decide(obs, **kwargs)
        value = json.loads(response.text)
        if (
            obs["role"] == "coordinator"
            and obs.get("needs_reviewed")
            and obs.get("barriers", {}).get("reply_event_id") != obs["latest_event"]["id"]
        ):
            value = dict(
                request_id=obs["request_id"],
                expected_case_version=obs["expected_case_version"],
                step_type="ASSESS_BARRIERS",
                reason_code="PATIENT_BARRIERS_REVIEWED",
                reply_event_id=obs["latest_event"]["id"],
                evidence_quotes=[obs["latest_event"]["content"]],
                next_action="CLARIFY_TIME",  # Replay the faulty proposal, not a corrected mock.
                clarification_reason=self.ambiguity,
                clarification_question=None
                if self.ambiguity == "NONE"
                else "Which month do you mean?",
            )
        if obs["role"] == "preparation" and value["step_type"] == "RETURN" and self.bound:
            for item in value["scheduling_review"]:
                item.update(effect="DATE_WINDOW", date_to=self.bound)
        return ModelReply(json.dumps(value))


@pytest.mark.parametrize(
    "replies",
    [
        ["No, I can’t", "What slots available!?", "I asked for available slots"],
        ["நான் வர முடியாது", "கிடைக்கும் நேரங்கள் என்ன?", "கிடைக்கும் நேரங்களைக் கேட்டேன்"],
        ["Saya tidak boleh datang", "Apakah slot yang tersedia?", "Saya minta slot yang tersedia"],
    ],
)
def test_repeated_optional_clarification_progresses_to_verified_options(simulated_runtime, replies):
    runtime, tools, source, engine = simulated_runtime
    slot = add_slot(source, 16)
    from test_simulator import new_slot

    existing_time = datetime.fromisoformat(episode_body(source)["scheduled_at"])
    source.post(
        "/internal/admin/slots",
        headers=ADMIN,
        json=new_slot(
            specialty="myopia",
            starts_at=existing_time.isoformat(),
            ends_at=(existing_time + timedelta(minutes=30)).isoformat(),
        ),
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    for reply in replies:
        event(runtime[1], case, "demo_reply", reply).raise_for_status()
        drain(runtime, tools=tools, model=AvailabilityReplay())
        result = view(runtime[1], case)
        message = result["patient_simulator"]["messages"][-1]
        assert result["run"]["status"] == "waiting", result
        assert result["handoff"] is None
        assert "slots" in message["evidence"], (
            reply,
            message,
            [s.get("decision") for s in result["steps"][-6:]],
        )
        assert [s["id"] for s in message["evidence"]["slots"]] == [slot]
        assert message["evidence"]["scheduling_review_step_id"]
        assert "Which dates and times" not in message["original_body"]
        assert source_count(engine) == 0  # Asking for options is never booking consent.
    event(runtime[1], case, "demo_reply", "option 1 is fine").raise_for_status()
    drain(runtime, tools=tools)
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result
    assert source_count(engine) == 1
    # Longer conversations must also fit the shipped provider request cap.
    import httpx
    from pydantic import SecretStr
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentStep
    from forget_lah.runtime.provider import OrganiserModel

    settings = runtime[2].model_copy(
        update={
            "agent_request_max_bytes": 32000,
            "llm_gateway_url": "https://gateway.example",
            "llm_gateway_api_key": SecretStr("offline-only"),
        }
    )
    model = OrganiserModel(
        settings,
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"done": True, "message": {"role": "assistant", "content": "{}"}}
            )
        ),
    )
    with runtime[0]() as db:
        for step in db.scalars(select(AgentStep).where(AgentStep.run_id == result["run"]["id"])):
            model.decide(step.observation)


def test_unconstrained_search_still_enforces_doctor_deadline(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 16)
    bound = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    body = episode_body(source)
    body["doctor_note"] = "This mandatory appointment must be completed by " + bound + "."
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "What slots available!?").raise_for_status()
    drain(runtime, tools=tools, model=AvailabilityReplay(bound=bound))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "escalated"
    message = result["patient_simulator"]["messages"][-1]
    assert message["evidence"]["slots"] == []
    assert body["doctor_note"] in message["original_body"]
    assert source_count(engine) == 0


def test_stated_date_ambiguity_is_not_silently_ignored(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 16)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "The 18th, not sure which month").raise_for_status()
    drain(runtime, tools=tools, model=AvailabilityReplay(ambiguity="AMBIGUOUS_DATE"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting"
    assert "Which month" in result["patient_simulator"]["messages"][-1]["original_body"]
    assert source_count(engine) == 0


def test_retry_cannot_reset_exhausted_reply_allowance(simulated_runtime):
    from forget_lah.runtime.models import AgentRun

    runtime, tools, _, _ = simulated_runtime
    case, run_id = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "What slots are available?").raise_for_status()
    with runtime[0]() as db, db.begin():
        run = db.get(AgentRun, run_id)
        assert run.checkpoint["turn_start_step"] > 0
        run.step_count = run.checkpoint["turn_start_step"] + runtime[2].agent_max_steps
    drain(runtime, tools=tools)
    assert view(runtime[1], case)["run"]["pause_reason"] == "STEP_BUDGET_EXHAUSTED"
    event(runtime[1], case, "retry").raise_for_status()
    drain(runtime, tools=tools)
    result = view(runtime[1], case)
    assert result["run"]["pause_reason"] == "STEP_BUDGET_EXHAUSTED"
    assert result["run"]["turn_step_count"] == runtime[2].agent_max_steps
