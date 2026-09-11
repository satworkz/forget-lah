from sqlalchemy import select

from forget_lah.db import Membership, Principal
from forget_lah.runtime.contracts import (
    REQUIRED_EVIDENCE_BY_ROLE,
    TOOLS_BY_ROLE,
    CompleteDecision,
    DelegateDecision,
    ReturnDecision,
    ToolDecision,
)
from forget_lah.runtime.models import AgentDelegation, AgentStep, StaffHandoff


def has_authority(db, run):
    return (
        db.scalar(
            select(Membership.id)
            .join(Principal)
            .where(
                Membership.principal_id == run.authorised_by,
                Membership.clinic_id == run.clinic_id,
                Membership.active.is_(True),
                Principal.active.is_(True),
            )
        )
        is not None
    )


def policy_for(db, run, case, step, decision):
    reasons = ["REQUEST_AND_CASE_BOUND", "STAFF_AUTHORITY_RECHECKED"]
    deny = None
    if not has_authority(db, run):
        deny = "STAFF_AUTHORITY_REVOKED"
    elif decision.request_id != step.id or decision.expected_case_version != case.case_version:
        deny = "STALE_OR_WRONG_REQUEST"
    elif step.role != run.active_role:
        deny = "ROLE_CHANGED"
    elif isinstance(decision, ToolDecision):
        if decision.tool_name not in TOOLS_BY_ROLE.get(run.active_role, ()):
            deny = "TOOL_NOT_ALLOWED_FOR_ROLE"
        else:
            reasons.append("READ_ONLY_SYNTHETIC_SOURCE")
    elif isinstance(decision, DelegateDecision):
        if run.active_role != "coordinator":
            deny = "ONLY_COORDINATOR_CAN_DELEGATE"
        elif db.scalar(
            select(AgentDelegation.id).where(
                AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
            )
        ):
            deny = "DELEGATION_ALREADY_ACTIVE"
        elif (decision.target == "preparation") != (
            decision.reason_code == "PREPARATION_REVIEW_REQUIRED"
        ):
            deny = "ACTION_REASON_MISMATCH"
    elif isinstance(decision, ReturnDecision):
        delegation = db.scalar(
            select(AgentDelegation).where(
                AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
            )
        )
        if (
            run.active_role == "coordinator"
            or not delegation
            or delegation.target != run.active_role
        ):
            deny = "NO_ACTIVE_SPECIALIST_DELEGATION"
        elif (
            run.active_role == "engagement"
            and run.checkpoint["latest_event"]["kind"] != "demo_reply"
        ):
            deny = "PATIENT_REPLY_REQUIRED"
        elif (run.active_role == "preparation") != (
            decision.reason_code == "SPECIALIST_REVIEW_FINISHED"
        ):
            deny = "SPECIALIST_REPORT_REASON_MISMATCH"
        else:
            evidence_tools = set()
            for evidence_id in decision.evidence_ids:
                evidence = db.scalar(
                    select(AgentStep).where(
                        AgentStep.id == evidence_id,
                        AgentStep.run_id == run.id,
                        AgentStep.clinic_id == run.clinic_id,
                        AgentStep.role == run.active_role,
                        AgentStep.sequence > delegation.start_sequence,
                        AgentStep.status == "completed",
                    )
                )
                if (
                    not evidence
                    or not evidence.tool_result
                    or evidence.tool_result.get("status") != "succeeded"
                ):
                    deny = "SPECIALIST_EVIDENCE_MISSING"
                    break
                evidence_tools.add(evidence.tool_result["tool_name"])
            required = set(REQUIRED_EVIDENCE_BY_ROLE[run.active_role])
            if not deny and not required.issubset(evidence_tools):
                deny = "SPECIALIST_EVIDENCE_INCOMPLETE"
    elif isinstance(decision, CompleteDecision):
        handoff = db.scalar(
            select(StaffHandoff).where(
                StaffHandoff.id == decision.handoff_id,
                StaffHandoff.run_id == run.id,
                StaffHandoff.clinic_id == run.clinic_id,
                StaffHandoff.case_id == case.id,
            )
        )
        if run.active_role != "coordinator":
            deny = "ONLY_COORDINATOR_CAN_COMPLETE"
        elif not handoff or not handoff.accepted_by or not handoff.accepted_at:
            deny = "OWNED_HANDOFF_EVIDENCE_MISSING"
        else:
            reasons.append("NAMED_STAFF_ACCEPTANCE_VERIFIED")
    existing_handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
    clinical = decision.reason_code == "CLINICAL_REVIEW_REQUIRED" or (
        existing_handoff is not None and existing_handoff.risk == "RED"
    )
    return {
        "request_id": step.id,
        "case_id": case.id,
        "case_version": case.case_version,
        "action": decision.step_type,
        "policy_version": "m2a-read-only-v1",
        "decision": "DENY" if deny else "ALLOW",
        "risk": "RED" if clinical else "AMBER" if decision.step_type == "ESCALATE" else "GREEN",
        "reason_codes": [deny] if deny else reasons,
    }
