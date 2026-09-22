"""Bounded staff scheduling review; never sends messages or changes appointments."""

from datetime import datetime

from forget_lah.runtime.contracts import DelegateDecision, ToolDecision

KEY = "staff_review_restore"
READS = {"read_followup_context", "get_approved_instructions", "check_prerequisites"}


def restore_review(run, step_id=None):
    from sqlalchemy.orm import object_session

    from forget_lah.runtime.models import AgentDelegation

    saved = run.checkpoint[KEY]
    db = object_session(run)
    for delegation_id in saved.get("delegation_ids", []):
        db.get(AgentDelegation, delegation_id).status = "active"
    run.checkpoint = {
        **saved["checkpoint"],
        **({"staff_scheduling_review_step_id": step_id} if step_id else {}),
    }
    run.status = saved["status"]
    run.active_role = saved["active_role"]
    run.authorised_by = saved["authorised_by"]
    run.available_at = (
        datetime.fromisoformat(saved["available_at"]) if saved["available_at"] else None
    )
    run.lease_token = run.lease_until = None


def coordinator_review(db, settings, run, case, step):
    from forget_lah.runtime.engine import apply_control, pause
    from forget_lah.runtime.policy import policy_for

    context = next(
        (
            t
            for t in step.observation["tools"]
            if t["result"]["tool_name"] == "read_followup_context"
        ),
        None,
    )
    common = {"request_id": step.id, "expected_case_version": case.case_version}
    if context and context["result"]["status"] != "succeeded":
        step.status = "error"
        step.error_code = "SOURCE_UNAVAILABLE"
        pause(run, "SOURCE_UNAVAILABLE")
        return
    decision = (
        DelegateDecision(
            **common,
            step_type="DELEGATE",
            reason_code="PREPARATION_REVIEW_REQUIRED",
            target="preparation",
            goal="Review all current doctor instructions for staff rescheduling. Return source-grounded scheduling constraints and patient checks; do not contact the patient or change the appointment.",
        )
        if context
        else ToolDecision(
            **common, step_type="TOOL", reason_code="READ_SOURCE", tool_name="read_followup_context"
        )
    )
    step.origin = "rule"
    step.observation = {
        **step.observation,
        "application_rule": {
            "name": "STAFF_SCHEDULING_REVIEW",
            "explanation": "Staff requested a read-only review of current doctor instructions before choosing a new appointment.",
        },
    }
    step.decision = decision.model_dump()
    step.policy = policy_for(db, run, case, step, decision)
    if step.policy["decision"] != "ALLOW":
        step.status, step.error_code = "rejected", "POLICY_DENIED"
        pause(run, "POLICY_DENIED")
    elif isinstance(decision, ToolDecision):
        step.status = "tool_pending"
    else:
        apply_control(db, run, case, step, decision, settings)
