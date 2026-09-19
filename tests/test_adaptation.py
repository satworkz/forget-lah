import json
from datetime import UTC, datetime, timedelta

import pytest
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, headers, start, view
from test_simulator import ADMIN, new_slot
from test_simulator import simulator as simulator

from forget_lah.db import uid
from forget_lah.runtime.adaptation import matching_slots
from forget_lah.runtime.provider import MockModel, ModelReply


class BarrierModel(MockModel):
    """Explicit test decisions, not an NLP implementation."""

    def __init__(self, *, issue="NONE", action="SEARCH_SLOTS", invalid=None):
        self.issue, self.action, self.invalid = issue, action, invalid

    def decide(self, obs, **kwargs):
        event = obs["latest_event"]
        if (
            obs["role"] == "coordinator"
            and event["kind"] == "demo_reply"
            and not obs.get("barriers")
        ):
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "ASSESS_BARRIERS",
                        "reason_code": "PATIENT_BARRIERS_REVIEWED",
                        "reply_event_id": uid()
                        if self.invalid == "binding"
                        else event.get("reply_event_id", event["id"]),
                        "evidence_quotes": ["invented"]
                        if self.invalid == "quote"
                        else [event["content"]],
                        "earliest_minute": 900,
                        "preparation_issue": self.issue,
                        "next_action": self.action,
                    }
                )
            )
        return super().decide(obs, **kwargs)


def add_slot(source, hour):
    at = (datetime.now(UTC) + timedelta(days=3)).replace(
        hour=hour - 8, minute=0, second=0, microsecond=0
    )
    body = new_slot(
        specialty="myopia",
        starts_at=at.isoformat(),
        ends_at=(at + timedelta(minutes=30)).isoformat(),
    )
    return source.post("/internal/admin/slots", headers=ADMIN, json=body).json()["id"]


def test_constraint_search_and_booking(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 10)
    afternoon = add_slot(source, 16)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(
        runtime[1], case, "demo_reply", "My daughter can accompany me after 3 pm"
    ).raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    assert result["handoff"] is None
    offer = result["patient_simulator"]["messages"][-1]
    assert [s["id"] for s in offer["evidence"]["slots"]] == [afternoon]
    assert source_count(engine) == 0
    event(runtime[1], case, "demo_reply", "option 1 is fine").raise_for_status()
    drain(runtime, tools=tools)
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result
    assert result["plan"]["attendance"] == "Source confirmed"
    assert source_count(engine) == 1
    import httpx
    from pydantic import SecretStr
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentStep
    from forget_lah.runtime.provider import OrganiserModel

    settings = runtime[2].model_copy(
        update={
            "agent_request_max_bytes": 32000,  # Shipped cap; ignore private .env.
            "llm_gateway_url": "https://gateway.example",
            "llm_gateway_api_key": SecretStr("test-only"),
        }
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, json={"done": True, "message": {"role": "assistant", "content": "{}"}}
        )
    )
    with runtime[0]() as db:
        for step in db.scalars(select(AgentStep).where(AgentStep.run_id == result["run"]["id"])):
            from forget_lah.runtime.provider import ModelError, prompt_for

            try:
                OrganiserModel(settings, transport).decide(step.observation)
            except ModelError as exc:
                raise AssertionError(
                    (step.sequence, step.role, len(prompt_for(step.observation, False)), str(exc))
                ) from None


def test_no_matching_time_asks_without_escalation(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 10)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only after 3 pm").raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    assert result["handoff"] is None
    assert "Would another day or time work" in result["patient_simulator"]["messages"][-1]["body"]
    assert source_count(engine) == 0


@pytest.mark.parametrize("issue", ["INCOMPLETE", "NEEDS_EXPLANATION"])
def test_preparation_callback_is_not_attendance_confirmation(simulated_runtime, issue):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "I have not completed my preparation").raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel(issue=issue, action="REVIEW_PREPARATION"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "escalated", result
    assert result["handoff"]["reason_code"] == "PREPARATION_HELP_REQUIRED"
    assert result["plan"]["attendance"] == "Not confirmed by source"
    assert result["patient_simulator"]["messages"][-1]["kind"] == "preparation_callback"
    assert source_count(engine) == 0
    event(runtime[1], case, "accept_handoff").raise_for_status()
    event(
        runtime[1], case, "resolve_callback", "Called patient; clinician will clarify prerequisite."
    ).raise_for_status()
    result = view(runtime[1], case)
    assert result["run"]["outcome"] == "PREPARATION_REVIEW_RESOLVED_BY_STAFF"
    assert source_count(engine) == 0


@pytest.mark.parametrize("invalid", ["quote", "binding"])
def test_barrier_evidence_is_validated(simulated_runtime, invalid):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only afternoons").raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel(invalid=invalid))
    result = view(runtime[1], case)
    assert result["steps"][-1]["policy"]["decision"] == "DENY"
    assert source_count(engine) == 0


def test_preferences_consent_reuse_and_forget(simulated_runtime):
    runtime, tools, source, _ = simulated_runtime
    add_slot(source, 10)
    afternoon = add_slot(source, 16)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    client = runtime[1]

    def save(**values):
        return client.post(
            f"/api/cases/{case}/preferences",
            headers=headers(client),
            json={
                "expected_case_version": view(client, case)["case_version"],
                "consent": True,
                "earliest_minute": 900,
                **values,
            },
        )

    assert save(consent=False).status_code == 422
    save().raise_for_status()
    assert (
        client.post(
            f"/api/cases/{case}/preferences",
            json={"expected_case_version": view(client, case)["case_version"], "consent": True},
        ).status_code
        == 403
    )
    from types import SimpleNamespace

    from forget_lah.db import FollowupCase
    from forget_lah.runtime.adaptation import preferences_for

    with runtime[0]() as db:
        current = db.get(FollowupCase, case)
        another_followup = SimpleNamespace(
            clinic_id=current.clinic_id, patient_id=current.patient_id
        )
        assert preferences_for(db, another_followup)["earliest_minute"] == 900
        assert (
            preferences_for(db, SimpleNamespace(clinic_id=uid(), patient_id=current.patient_id))
            == {}
        )
    event(client, case, "demo_reply", "What are the available slots?").raise_for_status()
    drain(runtime, tools=tools)
    result = view(client, case)
    assert [s["id"] for s in result["patient_simulator"]["messages"][-1]["evidence"]["slots"]] == [
        afternoon
    ]
    save(clear=True, consent=False).raise_for_status()
    assert view(client, case)["preferences"] == {}


def test_current_visit_overrides_memory():
    from types import SimpleNamespace

    from forget_lah.runtime.adaptation import effective_constraints

    run = SimpleNamespace(checkpoint={"barriers": {"earliest_minute": 540}})
    assert effective_constraints(run, {"earliest_minute": 900})["earliest_minute"] == 540


def test_slot_filter_uses_singapore_day_and_time():
    slots = [{"starts_at": "2030-01-01T16:00:00+00:00"}, {"starts_at": "2030-01-02T08:00:00+00:00"}]
    assert matching_slots(slots, {"requested_date": "2030-01-02", "earliest_minute": 900}) == [
        slots[1]
    ]


def test_ambiguous_time_asks_question(simulated_runtime):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "When my daughter can come").raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel(action="CLARIFY_TIME"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting"
    assert "Which dates and times" in result["patient_simulator"]["messages"][-1]["body"]
    assert source_count(engine) == 0


def test_unavailable_times_and_rejected_slots_are_not_offered():
    slots = [
        {"id": "morning", "starts_at": "2026-09-22T02:00:00+00:00"},
        {"id": "afternoon", "starts_at": "2026-09-22T08:00:00+00:00"},
    ]
    assert matching_slots(slots, {"excluded_minutes": [600]}) == slots[1:]
    assert matching_slots(slots, {"rejected_slot_ids": ["morning", "afternoon"]}) == []


@pytest.mark.parametrize("action", ["CLARIFY_TIME", "SEARCH_SLOTS"])
def test_offer_rejection_is_saved_and_clarified(simulated_runtime, action):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 10)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "What are the available slots?").raise_for_status()
    drain(runtime, tools=tools)
    before = view(runtime[1], case)
    offered = next(
        m for m in reversed(before["patient_simulator"]["messages"]) if m["kind"] == "options"
    )

    class RejectionModel(MockModel):
        def decide(self, obs, **kwargs):
            assert obs["recent_messages"]
            assert "Option 1" in obs["recent_messages"][-1]["text"]
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "ASSESS_BARRIERS",
                        "reason_code": "PATIENT_BARRIERS_REVIEWED",
                        "reply_event_id": obs["latest_event"]["id"],
                        "evidence_quotes": ["None of those works"],
                        "rejects_current_offer": True,
                        "excluded_minutes": [600],
                        "next_action": action,
                    }
                )
            )

    event(runtime[1], case, "demo_reply", "None of those works").raise_for_status()
    drain(runtime, tools=tools, model=RejectionModel())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting"
    assert result["handoff"] is None
    assert result["patient_simulator"]["messages"][-1]["kind"] == "clarification"
    assert source_count(engine) == 0
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentRun

    with runtime[0]() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.case_id == case))
        assert run.checkpoint["barriers"]["rejected_slot_ids"] == [
            s["id"] for s in offered["evidence"]["slots"]
        ]


@pytest.mark.parametrize("proposal", ["CLARIFY", "ESCALATE"])
def test_general_clarification_before_handoff(simulated_runtime, proposal):
    runtime, tools, source, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)

    class Clarifier(MockModel):
        def decide(self, obs, **kwargs):
            count = obs["clarification_count"]
            if count:
                assert obs["recent_messages"][-1]["kind"] == "clarification"
            decision = {
                "request_id": obs["request_id"],
                "expected_case_version": obs["expected_case_version"],
                "step_type": proposal if count < 2 else "ESCALATE",
                "reason_code": "AMBIGUOUS_REPLY",
            }
            if decision["step_type"] == "CLARIFY":
                decision.update(
                    reply_event_id=obs["latest_event"]["id"],
                    question="Do you mean someone will accompany you, or attend instead of you?",
                )
            return ModelReply(json.dumps(decision))

    for index, text in enumerate(
        ["Can I send my son?", "The other thing", "Still the other thing"]
    ):
        event(runtime[1], case, "demo_reply", text).raise_for_status()
        drain(runtime, tools=tools, model=Clarifier())
        result = view(runtime[1], case)
        assert result["run"]["status"] == ("waiting" if index < 2 else "escalated")
        if index < 2:
            assert result["handoff"] is None
            assert result["patient_simulator"]["messages"][-1]["kind"] == "clarification"
        assert source_count(engine) == 0


@pytest.mark.parametrize("remember", [True, False])
@pytest.mark.parametrize("kind", ["ASSESS_BARRIERS", "CLARIFY"])
def test_frustration_ack_and_reported_memory(simulated_runtime, remember, kind):
    from types import SimpleNamespace

    from forget_lah.db import FollowupCase
    from forget_lah.runtime.adaptation import preferences_for

    runtime, tools, source, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "I told you several times that 10 wont work for me, i am frustrated."

    class ConcernModel(MockModel):
        def decide(self, obs, **kwargs):
            payload = {
                "request_id": obs["request_id"],
                "expected_case_version": obs["expected_case_version"],
                "step_type": kind,
                "reason_code": "PATIENT_BARRIERS_REVIEWED"
                if kind == "ASSESS_BARRIERS"
                else "AMBIGUOUS_REPLY",
                "reply_event_id": obs["latest_event"]["id"],
                "evidence_quotes": [text],
                "concern_quote": "i am frustrated",
                "excluded_minutes": [600],
                "remember_exclusions": remember,
            }
            payload.update(
                {"next_action": "CLARIFY_TIME"}
                if kind == "ASSESS_BARRIERS"
                else {"question": "What times would work better for you?"}
            )
            return ModelReply(json.dumps(payload))

    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(runtime, tools=tools, model=ConcernModel())
    result = view(runtime[1], case)
    messages = result["patient_simulator"]["messages"]
    responses = [m for m in messages if m["kind"] != "reminder"]
    assert len(responses) == 1
    assert responses[0]["kind"] == "clarification"
    assert responses[0]["body"].startswith("I'm sorry")
    assert "?" in responses[0]["body"]
    assert result["run"]["status"] == "waiting" and result["handoff"] is None
    assert source_count(engine) == 0
    with runtime[0]() as db:
        current = db.get(FollowupCase, case)
        prefs = preferences_for(
            db, SimpleNamespace(clinic_id=current.clinic_id, patient_id=current.patient_id)
        )
        assert prefs.get("excluded_minutes", []) == ([600] if remember else [])
        assert (
            preferences_for(db, SimpleNamespace(clinic_id=uid(), patient_id=current.patient_id))
            == {}
        )
        if remember:
            assert (
                matching_slots([{"id": "x", "starts_at": "2030-01-02T02:00:00+00:00"}], prefs) == []
            )
    if remember:
        from test_simulator import episode_body

        body = episode_body(source)
        body["scheduled_at"] = "2030-01-02T02:00:00+00:00"
        source.put(
            "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
        ).raise_for_status()
        runtime[1].post(
            f"/api/cases/{case}/agent/runs",
            headers=headers(runtime[1]),
            json={"expected_case_version": result["case_version"], "fresh_simulation": True},
        ).raise_for_status()
        drain(runtime, tools=tools)
        result = view(runtime[1], case)
        assert (
            "conflicts with your saved timing preference"
            in result["patient_simulator"]["messages"][0]["body"]
        )
    client = runtime[1]
    client.post(
        f"/api/cases/{case}/preferences",
        headers=headers(client),
        json={"expected_case_version": result["case_version"], "clear": True, "consent": False},
    ).raise_for_status()
    assert view(client, case)["preferences"] == {}


def test_date_range_and_time_window_filter_in_singapore():
    slots = [
        {"id": "before", "starts_at": "2026-09-30T10:00:00+00:00"},
        {"id": "morning", "starts_at": "2026-10-01T02:00:00+00:00"},
        {"id": "first", "starts_at": "2026-10-01T10:00:00+00:00"},
        {"id": "last", "starts_at": "2026-10-31T11:00:00+00:00"},
        {"id": "november", "starts_at": "2026-10-31T16:00:00+00:00"},
    ]
    assert [
        s["id"]
        for s in matching_slots(
            slots,
            {
                "date_from": "2026-10-01",
                "date_to": "2026-10-31",
                "earliest_minute": 1080,
                "latest_minute": 1200,
            },
        )
    ] == ["first", "last"]


@pytest.mark.parametrize(
    "changes",
    [
        {"date_from": "2026-10-01"},
        {"date_from": "2026-10-31", "date_to": "2026-10-01"},
        {"date_from": "2026-02-30", "date_to": "2026-03-01"},
        {"date_from": "2026-10-01", "date_to": "2026-10-31", "requested_date": "2026-11-01"},
    ],
)
def test_invalid_date_windows_rejected(changes):
    from forget_lah.runtime.contracts import BarrierDecision

    with pytest.raises(ValueError):
        BarrierDecision(
            request_id=uid(),
            expected_case_version=1,
            reply_event_id=uid(),
            step_type="ASSESS_BARRIERS",
            reason_code="PATIENT_BARRIERS_REVIEWED",
            evidence_quotes=["October"],
            next_action="SEARCH_SLOTS",
            **changes,
        )


def test_specific_time_clarification_preserves_month(simulated_runtime):
    class MonthModel(BarrierModel):
        def decide(self, obs, **kwargs):
            if obs["role"] == "coordinator" and not obs["needs_reviewed"]:
                from test_patient_memory import NeedsModel

                return NeedsModel(
                    [("other_concern", "October outside office hours", "visit")],
                    question="What times are outside your office hours?",
                    intent="CHANGE",
                ).decide(obs, **kwargs)
            response = super().decide(obs, **kwargs)
            d = json.loads(response.text)
            if d["step_type"] == "ASSESS_BARRIERS":
                d.update(
                    date_from="2026-10-01",
                    date_to="2026-10-31",
                    earliest_minute=None,
                    next_action="CLARIFY_TIME",
                    clarification_question="What times outside office hours would suit you in October?",
                )
            return ModelReply(json.dumps(d))

    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(
        runtime[1], case, "demo_reply", "I prefer October outside my office hours"
    ).raise_for_status()
    drain(runtime, tools=tools, model=MonthModel())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting"
    assert result["handoff"] is None
    assert source_count(engine) == 0
    assert (
        "office hours would suit you in October"
        in result["patient_simulator"]["messages"][-1]["body"]
    )
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentRun

    with runtime[0]() as db:
        barrier = db.scalar(select(AgentRun).where(AgentRun.case_id == case)).checkpoint["barriers"]
        assert barrier["date_from"] == "2026-10-01"
        assert barrier["date_to"] == "2026-10-31"


def test_refining_time_search_does_not_reinterpret_old_offer(simulated_runtime):
    from test_patient_memory import NeedsModel

    class RefinementModel(BarrierModel):
        def decide(self, obs, **kwargs):
            e = obs["latest_event"]
            if obs["role"] == "coordinator" and not obs["needs_reviewed"]:
                return NeedsModel([], intent="CHANGE").decide(obs, **kwargs)
            if obs["role"] == "coordinator" and obs.get("barriers", {}).get(
                "reply_event_id"
            ) != e.get("reply_event_id", e["id"]):
                value = json.loads(super().decide({**obs, "barriers": {}}, **kwargs).text)
                value["earliest_minute"] = 1080
                return ModelReply(json.dumps(value))
            if obs["role"] == "engagement":
                assert "selection_offer" not in obs["simulation"]
                assert "attendance_review" not in obs["simulation"]
            return super().decide(obs, **kwargs)

    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 17)
    later = add_slot(source, 19)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only after 3 pm").raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    event(runtime[1], case, "demo_reply", "After 6 pm please").raise_for_status()
    drain(runtime, tools=tools, model=RefinementModel())
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting" and not result["handoff"]
    offer = result["patient_simulator"]["messages"][-1]
    assert offer["kind"] == "options"
    assert [s["id"] for s in offer["evidence"]["slots"]] == [later]
    assert source_count(engine) == 0
