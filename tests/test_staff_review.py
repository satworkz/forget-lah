"""Read-only staff review opens appointment choices without patient side effects."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_bridge_runtime import add_option, begin
from test_bridge_runtime import bridge_runtime as bridge_runtime
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_postgres import postgres_schema as postgres_schema
from test_runtime import drain, headers, view
from test_simulator import simulator as simulator

from forget_lah.db import BridgeEpisode, FollowupCase
from forget_lah.runtime.models import AgentEvent, AgentRun, SimulatedMessage
from forget_lah.runtime.provider import MockModel, ModelReply


def state(runtime, case_id):
    return runtime[1].get(f"/api/cases/{case_id}/appointment-change").json()


def start(runtime, case_id, action="review", h=None):
    return runtime[1].post(
        f"/api/cases/{case_id}/appointment-change/{action}",
        headers=h or headers(runtime[1]),
        json={"expected_case_version": state(runtime, case_id)["case_version"]},
    )


@pytest.mark.parametrize("initial_status", ["waiting", "completed"])
def test_review_restores_followup_and_opens_slots(bridge_runtime, initial_status):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    begin(runtime, tools, case_id)
    add_option(runtime, case_id)
    with runtime[0].begin() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.case_id == case_id))
        run.status = initial_status
    before = view(runtime[1], case_id)
    assert state(runtime, case_id)["can_review"]
    with runtime[0]() as db:
        run = db.get(AgentRun, before["run"]["id"])
        checkpoint, status = run.checkpoint, run.status
        message_count = db.scalar(select(func.count()).select_from(SimulatedMessage))
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        source_before = (episode.normalized, episode.version, episode.followup_status)
    response = start(runtime, case_id)
    assert response.status_code == 200, response.text
    assert state(runtime, case_id)["review_status"] == "running"
    drain(runtime, tools=tools)
    after = state(runtime, case_id)
    assert after["review_status"] == "ready", view(runtime[1], case_id)
    assert not after["blocked"], after
    assert after["slots"]
    with runtime[0]() as db:
        run = db.get(AgentRun, before["run"]["id"])
        assert run.status == status
        assert {
            k: v for k, v in run.checkpoint.items() if k != "staff_scheduling_review_step_id"
        } == checkpoint
        assert db.scalar(select(func.count()).select_from(SimulatedMessage)) == message_count
        episode = db.get(BridgeEpisode, episode.id)
        assert (episode.normalized, episode.version, episode.followup_status) == source_before
        assert db.scalar(
            select(AgentEvent).where(AgentEvent.kind == "staff_scheduling_review")
        ).actor_id


def test_review_cancel_and_stale_version(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    add_option(runtime, case_id)
    version = state(runtime, case_id)["case_version"]
    response = start(runtime, case_id)
    assert response.status_code == 200, response.text
    stale = runtime[1].post(
        f"/api/cases/{case_id}/appointment-change/review/cancel",
        headers=headers(runtime[1]),
        json={"expected_case_version": version},
    )
    assert stale.status_code == 409
    assert start(runtime, case_id, "review/cancel").status_code == 200
    assert state(runtime, case_id)["can_review"]
    drain(runtime, tools=tools)
    assert state(runtime, case_id)["review_status"] == "required"


class UnsafeReview(MockModel):
    def decide(self, obs, **kwargs):
        return ModelReply(
            json.dumps(
                {
                    "request_id": obs["request_id"],
                    "expected_case_version": obs["expected_case_version"],
                    "step_type": "WAIT",
                    "reason_code": "AWAITING_PATIENT_REPLY",
                }
            )
        )


def test_failed_review_can_retry_without_patient_message(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    add_option(runtime, case_id)
    assert start(runtime, case_id).status_code == 200
    drain(runtime, tools=tools, model=UnsafeReview())
    assert state(runtime, case_id)["review_status"] == "failed"
    assert start(runtime, case_id).status_code == 200
    drain(runtime, tools=tools)
    assert state(runtime, case_id)["review_status"] == "ready"
    with runtime[0]() as db:
        assert db.scalar(select(func.count()).select_from(SimulatedMessage)) == 0


@pytest.mark.parametrize("effect", ["DATE_WINDOW", "PATIENT_CHECK", "CLINIC_REVIEW"])
def test_review_shows_constraints_without_unlocking_invalid_slots(bridge_runtime, effect):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    add_option(runtime, case_id)
    note = (
        "Attend before January 2020"
        if effect == "DATE_WINDOW"
        else "Bring the completed form; otherwise ask the clinic."
    )
    with runtime[0].begin() as db:
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        episode.normalized = {**episode.normalized, "doctor_notes": note}

    class ReviewModel(MockModel):
        def decide(self, obs, **kwargs):
            answer = super().decide(obs, **kwargs)
            payload = json.loads(answer.text)
            if payload["step_type"] == "RETURN":
                for item in payload["scheduling_review"]:
                    if effect != "DATE_WINDOW":
                        item["effect"] = effect
                    if effect == "PATIENT_CHECK":
                        item.update(
                            condition_quote="Bring the completed form",
                            patient_question="Have you completed the form?",
                            if_not_met="CLINIC_REVIEW",
                        )
                return ModelReply(json.dumps(payload))
            return answer

    assert start(runtime, case_id).status_code == 200
    drain(runtime, tools=tools, model=ReviewModel())
    after = state(runtime, case_id)
    assert after["review_status"] == "ready", after
    assert after["slots"] == []
    assert after["review_requirements"][0]["effect"] == effect
    if effect == "PATIENT_CHECK":
        assert after["patient_checks"][0]["condition_quote"] == "Bring the completed form"
    with runtime[0]() as db:
        assert db.scalar(select(func.count()).select_from(SimulatedMessage)) == 0


def test_api_review_reads_external_source_then_allows_change(simulated_runtime):
    from test_staff_appointment_change import apply

    from forget_lah.db import session_factory, uid, utcnow
    from services.mock_clinic.store import Episode, Slot, StaffChange

    runtime, tools, source, engine = simulated_runtime
    runtime[1].app.state.staff_change_tools = tools
    with runtime[0]() as db:
        case = db.scalar(select(FollowupCase).where(FollowupCase.specialty == "myopia"))
        case_id, ref = case.id, case.source_episode_ref
    source_factory = session_factory(engine)
    with source_factory.begin() as db:
        episode = db.get(Episode, ref)
        episode.doctor_note = "Bring your booklet."
        original_version, original_time = episode.version, episode.scheduled_at
        db.add(
            Slot(
                id=uid(),
                specialty="myopia",
                starts_at=utcnow() + timedelta(days=4),
                ends_at=utcnow() + timedelta(days=4, minutes=30),
                doctor="Clinic team",
            )
        )
    assert state(runtime, case_id)["can_review"]
    response = start(runtime, case_id)
    assert response.status_code == 200, response.text
    drain(runtime, tools=tools)
    assert state(runtime, case_id)["slots"], state(runtime, case_id)
    with source_factory() as db:
        episode = db.get(Episode, ref)
        assert (episode.version, episode.scheduled_at) == (original_version, original_time)
        assert db.scalar(select(func.count()).select_from(StaffChange)) == 0
    result, *_ = apply(runtime[1], case_id)
    assert result["status"] == "committed"


def test_review_idempotency_and_source_change_requires_new_review(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    add_option(runtime, case_id)
    body = {"expected_case_version": state(runtime, case_id)["case_version"]}
    h = headers(runtime[1])
    endpoint = f"/api/cases/{case_id}/appointment-change/review"
    for _ in range(2):
        assert runtime[1].post(endpoint, headers=h, json=body).status_code == 200
    drain(runtime, tools=tools)
    assert state(runtime, case_id)["review_status"] == "ready"
    assert runtime[1].post(endpoint, headers=h, json=body).status_code == 200
    with runtime[0].begin() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentEvent)
                .where(AgentEvent.kind == "staff_scheduling_review")
            )
            == 1
        )
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        episode.version += 1
    assert state(runtime, case_id)["can_review"]
    assert not state(runtime, case_id)["slots"]


def test_cancel_ignores_late_model_result(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    add_option(runtime, case_id)
    assert start(runtime, case_id).status_code == 200

    class CancelWhileReading(MockModel):
        def decide(self, obs, **kwargs):
            response = start(runtime, case_id, "review/cancel")
            assert response.status_code == 200, response.text
            return super().decide(obs, **kwargs)

    drain(runtime, tools=tools, model=CancelWhileReading())
    after = state(runtime, case_id)
    assert after["can_review"]
    assert after["review_status"] == "required"
    assert not after["slots"]
