import json
from datetime import UTC, datetime, timedelta, timezone

from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import (
    MockModel,
    ModelReply,
    _anthropic_schema,
    prompt_for,
    response_schema_for,
)


class QualifiedConfirmationModel(MockModel):
    def __init__(self, qualification, *, request_quote="confirm my appointment", plans=None):
        self.qualification = qualification
        self.request_quote = request_quote
        self.plans = plans or []

    def decide(self, obs, **kwargs):
        event = obs["latest_event"]
        if (
            obs["role"] == "coordinator"
            and event["kind"] == "demo_reply"
            and not obs.get("needs_reviewed")
        ):
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "REVIEW_NEEDS",
                        "reason_code": "PATIENT_NEEDS_REVIEWED",
                        "reply_event_id": event.get("reply_event_id", event["id"]),
                        "updates": [],
                        "patient_questions": [],
                        "preparation_plans": self.plans,
                        "appointment_intent": "CONFIRM",
                        "appointment_request_quote": self.request_quote,
                        "attendance_qualification": self.qualification,
                        "question": None,
                        "comprehension_quote": None,
                        "concern_quote": None,
                    }
                )
            )
        review = obs.get("simulation", {}).get("attendance_review")
        if obs["role"] == "engagement" and review:
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "INTERPRET_ATTENDANCE",
                        "reason_code": "PATIENT_ATTENDANCE_REVIEWED",
                        "reply_event_id": review["reply_event_id"],
                        "source_step_id": review["source_step_id"],
                        "confirmed": True,
                        "unsupported_question": "NONE",
                    }
                )
            )
        return super().decide(obs, **kwargs)


def set_appointment(source, *, hour=10, doctor_note="Bring existing spectacles."):
    local = (datetime.now(UTC) + timedelta(days=2)).astimezone(timezone(timedelta(hours=8)))
    local = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    body = episode_body(source)
    body.update(scheduled_at=local.isoformat(), doctor_note=doctor_note, note_approved=True)
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()


def test_late_arrival_qualification_blocks_confirmation_without_escalation(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_appointment(
        source,
        doctor_note=(
            "Demo clinic note: bring your existing spectacles if you have them. "
            "Please remind him that he has a blood test."
        ),
    )
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = (
        "ok confirm my appointment, I will reach at 10:10 because I have a drinks party "
        "on 23rd Sep."
    )
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QualifiedConfirmationModel(
            {
                "quote": "I will reach at 10:10",
                "kind": "ARRIVAL_TIME",
                "arrival_minute": 610,
                "arrival_offset_minutes": None,
            },
            plans=["I have a drinks party on 23rd Sep."],
        ),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result["run"]
    assert result["handoff"] is None
    assert source_count(source_engine) == 0
    body = result["patient_simulator"]["messages"][-1]["body"]
    assert "reminder is for 10:00 AM SGT" in body
    assert "arrive at 10:10 AM SGT" in body
    assert "haven't recorded your attendance" in body
    assert "alternative appointment slots" in body
    assert "blood test" not in body.lower()


def test_on_time_arrival_allows_normal_confirmation(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_appointment(source)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "ok confirm my appointment, I will reach exactly at 10:00"
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QualifiedConfirmationModel(
            {
                "quote": "I will reach exactly at 10:00",
                "kind": "ARRIVAL_TIME",
                "arrival_minute": 600,
                "arrival_offset_minutes": None,
            }
        ),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result["run"]
    assert source_count(source_engine) == 1


def test_explicit_late_offset_blocks_confirmation(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_appointment(source)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "yes confirm, I will be about 10 minutes late"
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QualifiedConfirmationModel(
            {
                "quote": "I will be about 10 minutes late",
                "kind": "ARRIVAL_OFFSET",
                "arrival_minute": None,
                "arrival_offset_minutes": 10,
            },
            request_quote="yes confirm",
        ),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting"
    assert source_count(source_engine) == 0
    assert "10 minutes late" in result["patient_simulator"]["messages"][-1]["body"]


def test_conditional_confirmation_is_not_write_consent(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_appointment(source)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "yes I can attend if parking is available"
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QualifiedConfirmationModel(
            {
                "quote": "if parking is available",
                "kind": "CONDITION",
                "arrival_minute": None,
                "arrival_offset_minutes": None,
            },
            request_quote="yes I can attend",
        ),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting"
    assert source_count(source_engine) == 0
    assert "attendance conditional" in result["patient_simulator"]["messages"][-1]["body"]


def test_attendance_qualification_requires_exact_patient_quote(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    set_appointment(source)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    text = "yes confirm, I will reach at 10:10"
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(
        runtime,
        tools=tools,
        model=QualifiedConfirmationModel(
            {
                "quote": "invented arrival quote",
                "kind": "ARRIVAL_TIME",
                "arrival_minute": 610,
                "arrival_offset_minutes": None,
            },
            request_quote="yes confirm",
        ),
    )
    result = view(runtime[1], case)
    assert result["run"]["status"] == "paused"
    assert source_count(source_engine) == 0


def test_review_needs_prompt_requires_qualified_attendance_structure():
    obs = {
        "request_id": "00000000-0000-4000-8000-000000000001",
        "expected_case_version": 2,
        "role": "coordinator",
        "goal": "Follow up",
        "case": {"specialty": "myopia", "trigger": "UPCOMING_APPOINTMENT"},
        "latest_event": {
            "id": "00000000-0000-4000-8000-000000000002",
            "kind": "demo_reply",
            "content": "confirm, I will reach at 10:10",
        },
        "recent_messages": [],
        "today_sgt": "2026-09-21",
        "clarification_count": 0,
        "patient_memory": {},
        "patient_questions": [],
        "patient_task_types": [],
        "appointment_intent": "UNSPECIFIED",
        "appointment": {
            "scheduled_at": "2026-09-24T10:00:00+08:00",
            "local_display": "Thursday, 24 September 2026 at 10:00 AM SGT",
            "source_step_id": "00000000-0000-4000-8000-000000000003",
        },
        "needs_reviewed": False,
        "tools": [],
        "return_requirements": {
            "required_tools": [],
            "missing_tools": [],
            "eligible_evidence_ids": [],
        },
        "returned_specialists": [],
        "specialist_reports": [],
        "delegation_start": 0,
        "handoff": None,
        "allowed_tools": ["read_followup_context"],
        "simulation": {"enabled": True},
    }
    prompt = prompt_for(obs, False, native=True)
    assert "attendance_qualification" in prompt
    assert "ARRIVAL_TIME" in prompt
    assert (
        "application code compares the qualification with the verified source appointment" in prompt
    )


def test_native_schema_requires_qualification_decision_and_stays_anthropic_compatible():
    obs = {
        "request_id": "00000000-0000-4000-8000-000000000001",
        "expected_case_version": 2,
        "role": "coordinator",
        "goal": "Follow up",
        "case": {"specialty": "myopia", "trigger": "UPCOMING_APPOINTMENT"},
        "latest_event": {
            "id": "00000000-0000-4000-8000-000000000002",
            "kind": "demo_reply",
            "content": "confirm, I will reach at 10:10",
        },
        "recent_messages": [],
        "today_sgt": "2026-09-21",
        "clarification_count": 0,
        "patient_memory": {},
        "patient_questions": [],
        "patient_task_types": [],
        "appointment_intent": "UNSPECIFIED",
        "appointment": {
            "scheduled_at": "2026-09-24T10:00:00+08:00",
            "local_display": "Thursday, 24 September 2026 at 10:00 AM SGT",
            "source_step_id": "00000000-0000-4000-8000-000000000003",
        },
        "needs_reviewed": False,
        "tools": [],
        "return_requirements": {
            "required_tools": [],
            "missing_tools": [],
            "eligible_evidence_ids": [],
        },
        "returned_specialists": [],
        "specialist_reports": [],
        "delegation_start": 0,
        "handoff": None,
        "allowed_tools": ["read_followup_context"],
        "simulation": {"enabled": True},
    }
    schema = _anthropic_schema(response_schema_for(obs))
    review = next(
        choice
        for choice in schema["properties"]["decision"]["anyOf"]
        if choice["properties"]["step_type"].get("const") == "REVIEW_NEEDS"
    )
    assert "attendance_qualification" in review["required"]

    def contains_key(value, key):
        if isinstance(value, dict):
            return key in value or any(contains_key(v, key) for v in value.values())
        if isinstance(value, list):
            return any(contains_key(v, key) for v in value)
        return False

    assert not contains_key(schema, "maxItems")
