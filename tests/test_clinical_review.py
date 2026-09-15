import json

import pytest
from sqlalchemy import select
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import simulator as simulator

from forget_lah.db import Principal, uid
from forget_lah.runtime.models import AgentStep, StaffHandoff
from forget_lah.runtime.provider import MockModel, ModelReply

REPLY = "yes, I confirm the attendance, but I have swelling in my eyes now and pain as well."


class ClinicalModel(MockModel):
    def __init__(self, invalid=None):
        self.invalid = invalid

    def decide(self, obs, **kwargs):
        if obs["latest_event"].get("content") == REPLY:
            return ModelReply(
                json.dumps(
                    {
                        "request_id": obs["request_id"],
                        "expected_case_version": obs["expected_case_version"],
                        "step_type": "REPORT_SYMPTOMS",
                        "reason_code": "PATIENT_REPORTED_SYMPTOMS",
                        "reply_event_id": uid()
                        if self.invalid == "reply"
                        else obs["latest_event"].get("reply_event_id", obs["latest_event"]["id"]),
                        "symptom_quotes": ["invented symptom"]
                        if self.invalid == "quote"
                        else ["swelling in my eyes now and pain as well"],
                        "attendance_quote": "I confirm the attendance",
                    }
                )
            )
        return super().decide(obs, **kwargs)


def test_clinical_callback_lifecycle(simulated_runtime):
    runtime, tools, _, source_engine = simulated_runtime
    case_id, run_id = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", REPLY).raise_for_status()
    drain(runtime, tools=tools, model=ClinicalModel())
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "escalated"
    assert result["handoff"]["risk"] == "RED"
    assert result["handoff"]["reason_code"] == "PATIENT_REPORTED_SYMPTOMS"
    review = result["handoff"]["clinical_review"]
    assert review["status"] == "requested" and review["attendance_intent"] == "stated"
    message = result["patient_simulator"]["messages"][-1]
    assert message["kind"] == "clinical_acknowledgement"
    assert "call you back as soon as possible" in message["body"]
    assert source_count(source_engine) == 0
    assert event(runtime[1], case_id, "resolve_clinical", "Contacted").status_code == 409
    with runtime[0]() as db:
        before = len(list(db.scalars(select(AgentStep).where(AgentStep.run_id == run_id))))
    event(runtime[1], case_id, "accept_handoff").raise_for_status()
    assert view(runtime[1], case_id)["run"]["status"] == "escalated"
    with runtime[0].begin() as db:
        handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run_id))
        owner = handoff.accepted_by
        other = Principal(
            id=uid(),
            email="clinical-other@forget-lah.example",
            password_hash="not-a-login",
            active=False,
        )
        db.add(other)
        db.flush()
        handoff.accepted_by = other.id
    assert event(runtime[1], case_id, "resolve_clinical", "Not the owner").status_code == 409
    with runtime[0].begin() as db:
        db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run_id)).accepted_by = owner
    assert event(runtime[1], case_id, "resolve_clinical", " ").status_code == 422
    event(
        runtime[1],
        case_id,
        "resolve_clinical",
        "Demo: contacted patient; clinician reviewed and arranged follow-up.",
    ).raise_for_status()
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "completed"
    assert result["handoff"]["staff_task_status"] == "resolved"
    assert result["handoff"]["clinical_review"]["resolution"]
    with runtime[0]() as db:
        assert len(list(db.scalars(select(AgentStep).where(AgentStep.run_id == run_id)))) == before
    assert event(runtime[1], case_id, "resolve_clinical", "Again").status_code == 409


@pytest.mark.parametrize("invalid", ["reply", "quote"])
def test_clinical_report_requires_patient_evidence(simulated_runtime, invalid):
    runtime, tools, _, source_engine = simulated_runtime
    case_id, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", REPLY).raise_for_status()
    drain(runtime, tools=tools, model=ClinicalModel(invalid))
    result = view(runtime[1], case_id)
    assert result["run"]["status"] == "paused"
    assert result["handoff"] is None
    assert result["steps"][-1]["policy"]["decision"] == "DENY"
    assert source_count(source_engine) == 0
