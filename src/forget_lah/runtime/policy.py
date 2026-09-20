from sqlalchemy import select

from forget_lah.db import Membership, Principal
from forget_lah.runtime.contracts import (
    REQUIRED_EVIDENCE_BY_ROLE,
    AttendanceDecision,
    BarrierDecision,
    ClarifyDecision,
    ClinicalReportDecision,
    CompleteDecision,
    CompleteSimulationDecision,
    DelegateDecision,
    EscalateDecision,
    InstructionCheckDecision,
    NeedsDecision,
    ReturnDecision,
    SelectionDecision,
    ToolDecision,
    WaitDecision,
    tools_for,
)
from forget_lah.runtime.models import AgentDelegation, AgentStep, StaffHandoff
from forget_lah.runtime.questions import validate_answers
from forget_lah.runtime.simulation import (
    clarification_allowed,
    clarification_count,
    explicit_confirmation,
    latest_selection_offer,
    pending_instruction_question,
    read_already_available,
    saved_reply,
    simulation_enabled,
    simulation_evidence,
)
from forget_lah.service_identity import AUTOMATION_PRINCIPAL_ID
from forget_lah.source import DEMO_CLINIC_ID


def has_authority(db, run):
    if run.authorised_by == AUTOMATION_PRINCIPAL_ID and run.clinic_id != DEMO_CLINIC_ID:
        return False
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
    reasons = [
        "REQUEST_AND_CASE_BOUND",
        "SERVICE_AUTHORITY_RECHECKED"
        if run.authorised_by == AUTOMATION_PRINCIPAL_ID
        else "STAFF_AUTHORITY_RECHECKED",
    ]
    deny = None
    if not has_authority(db, run):
        deny = (
            "SERVICE_AUTHORITY_REVOKED"
            if run.authorised_by == AUTOMATION_PRINCIPAL_ID
            else "STAFF_AUTHORITY_REVOKED"
        )
    elif decision.request_id != step.id or decision.expected_case_version != case.case_version:
        deny = "STALE_OR_WRONG_REQUEST"
    elif step.role != run.active_role:
        deny = "ROLE_CHANGED"
    elif (
        isinstance(decision, (ClarifyDecision, BarrierDecision))
        and decision.concern_quote is not None
        and (
            not saved_reply(db, run)
            or not decision.concern_quote.strip()
            or decision.concern_quote not in saved_reply(db, run).content
        )
    ):
        deny = "CONCERN_QUOTE_NOT_IN_PATIENT_REPLY"
    elif isinstance(decision, ClarifyDecision) and any(
        not q.strip()
        or len(q) > 200
        or not saved_reply(db, run)
        or q not in saved_reply(db, run).content
        for q in decision.evidence_quotes
    ):
        deny = "CONCERN_QUOTES_NOT_IN_PATIENT_REPLY"
    elif isinstance(decision, NeedsDecision):
        reply = saved_reply(db, run)
        if (
            not simulation_enabled(run)
            or run.active_role != "coordinator"
            or not reply
            or reply.id != decision.reply_event_id
        ):
            deny = "MEMORY_REPLY_BINDING_REQUIRED"
        elif any(
            not q.strip() or len(q) > 600 or q not in reply.content
            for q in decision.patient_questions + decision.preparation_plans
        ):
            deny = "QUESTION_NOT_IN_PATIENT_REPLY"
        elif run.checkpoint.get("needs_reviewed") == reply.id:
            deny = "NEEDS_ALREADY_REVIEWED"
        elif any(not u.quote.strip() or u.quote not in reply.content for u in decision.updates) or (
            decision.concern_quote is not None
            and (not decision.concern_quote.strip() or decision.concern_quote not in reply.content)
        ):
            deny = "MEMORY_QUOTE_NOT_IN_PATIENT_REPLY"
        elif decision.comprehension_quote is not None and (
            not decision.comprehension_quote.strip()
            or decision.comprehension_quote not in reply.content
        ):
            deny = "COMPREHENSION_QUOTE_NOT_IN_REPLY"
        elif decision.appointment_request_quote is not None and (
            not decision.appointment_request_quote.strip()
            or decision.appointment_request_quote not in reply.content
        ):
            deny = "APPOINTMENT_INTENT_QUOTE_NOT_IN_REPLY"
        else:
            reasons.append("REPORTED_NEEDS_BOUND_TO_REPLY")
    elif isinstance(decision, ClarifyDecision):
        reply = saved_reply(db, run)
        if (
            not simulation_enabled(run)
            or run.active_role != "coordinator"
            or not reply
            or reply.id != decision.reply_event_id
        ):
            deny = "CLARIFICATION_REPLY_BINDING_REQUIRED"
        elif clarification_count(db, run) >= 2:
            deny = "CLARIFICATION_LIMIT_REACHED"
        elif not clarification_allowed(db, run):
            deny = "CLARIFICATION_NOT_APPLICABLE"
        else:
            reasons.append("CLARIFICATION_WITHOUT_APPOINTMENT_WRITE")
    elif isinstance(decision, BarrierDecision):
        reply = saved_reply(db, run)
        if (
            not simulation_enabled(run)
            or run.active_role != "coordinator"
            or not reply
            or decision.reply_event_id != reply.id
        ):
            deny = "BARRIER_REPLY_BINDING_REQUIRED"
        elif run.checkpoint.get("barriers", {}).get("reply_event_id") == reply.id:
            deny = "BARRIER_ALREADY_REVIEWED"
        elif any(
            not q.strip() or len(q) > 200 or q not in reply.content
            for q in decision.evidence_quotes
        ):
            deny = "BARRIER_QUOTES_NOT_IN_PATIENT_REPLY"
        else:
            reasons.append("PATIENT_CONSTRAINTS_BOUND_TO_SAVED_REPLY")
    elif isinstance(decision, ClinicalReportDecision):
        reply = saved_reply(db, run)
        if (
            run.active_role != "coordinator"
            or not simulation_enabled(run)
            or not reply
            or decision.reply_event_id != reply.id
        ):
            deny = "CLINICAL_REPLY_BINDING_REQUIRED"
        elif any(
            not q.strip() or len(q) > 200 or q not in reply.content for q in decision.symptom_quotes
        ):
            deny = "SYMPTOM_QUOTES_NOT_IN_PATIENT_REPLY"
        elif decision.contact_stop_quote is not None and (
            not decision.contact_stop_quote.strip()
            or decision.contact_stop_quote not in reply.content
        ):
            deny = "CONTACT_STOP_QUOTE_NOT_IN_PATIENT_REPLY"
        elif explicit_confirmation(reply.content) or any(
            explicit_confirmation(q)
            or q.strip().lower().rstrip("?.! ")
            in {"what should i bring", "what do i need to bring"}
            or (decision.attendance_quote is not None and q == decision.attendance_quote)
            for q in decision.symptom_quotes
        ):
            deny = "ADMINISTRATIVE_TEXT_IS_NOT_SYMPTOM_EVIDENCE"
        elif decision.attendance_quote is not None and (
            not decision.attendance_quote.strip()
            or len(decision.attendance_quote) > 200
            or decision.attendance_quote not in reply.content
        ):
            deny = "ATTENDANCE_QUOTE_NOT_IN_PATIENT_REPLY"
        else:
            reasons.append("PATIENT_REPORT_BOUND_CLINIC_REVIEW_REQUIRED")
    elif isinstance(decision, InstructionCheckDecision):
        reply = saved_reply(db, run)
        question = pending_instruction_question(db, run)
        if (
            run.active_role != "coordinator"
            or not simulation_enabled(run)
            or not reply
            or not question
            or decision.reply_event_id != reply.id
            or decision.question_message_id != question.id
        ):
            deny = "INSTRUCTION_CHECK_BINDING_REQUIRED"
        elif not decision.answer_quote.strip() or decision.answer_quote not in reply.content:
            deny = "INSTRUCTION_CHECK_ANSWER_NOT_IN_REPLY"
        else:
            reasons.append("PATIENT_ANSWER_BOUND_TO_APPROVED_INSTRUCTION_CHECK")
    elif isinstance(decision, AttendanceDecision):
        review = simulation_evidence(db, run).get("attendance_review")
        delegation = db.scalar(
            select(AgentDelegation).where(
                AgentDelegation.run_id == run.id,
                AgentDelegation.status == "active",
                AgentDelegation.target == "engagement",
            )
        )
        if not review or not delegation or run.active_role != "engagement":
            deny = "ATTENDANCE_REVIEW_NOT_AVAILABLE"
        elif (
            decision.reply_event_id != review["reply_event_id"]
            or decision.source_step_id != review["source_step_id"]
        ):
            deny = "ATTENDANCE_REPLY_OR_SOURCE_MISMATCH"
        else:
            reasons.append("MODEL_INTERPRETATION_BOUND_TO_SAVED_REPLY_AND_APPOINTMENT")
    elif isinstance(decision, SelectionDecision):
        offer = latest_selection_offer(db, run)
        reply = saved_reply(db, run)
        evidence = simulation_evidence(db, run)
        delegation = db.scalar(
            select(AgentDelegation).where(
                AgentDelegation.run_id == run.id,
                AgentDelegation.status == "active",
                AgentDelegation.target == "engagement",
            )
        )
        if (
            not simulation_enabled(run)
            or run.active_role != "engagement"
            or not delegation
            or not evidence.get("selection_offer")
        ):
            deny = "SELECTION_REVIEW_NOT_AVAILABLE"
        elif (
            not offer
            or not reply
            or decision.offer_id != offer.id
            or decision.reply_event_id != reply.id
        ):
            deny = "SELECTION_REPLY_OR_OFFER_MISMATCH"
        elif decision.option_number is not None and not 1 <= decision.option_number <= len(
            offer.evidence.get("slots", [])
        ):
            deny = "SELECTION_NOT_IN_OFFER"
        else:
            reasons.append("MODEL_INTERPRETATION_BOUND_TO_SAVED_REPLY_AND_OFFER")
    elif isinstance(decision, ToolDecision):
        if decision.tool_name not in tools_for(run.active_role, simulation_enabled(run)):
            deny = "TOOL_NOT_ALLOWED_FOR_ROLE"
        elif read_already_available(db, run, decision.tool_name):
            deny = "READ_EVIDENCE_ALREADY_AVAILABLE"
        elif decision.tool_name in {
            "record_simulated_confirmation",
            "send_simulated_acknowledgement",
            "send_simulated_options",
        }:
            evidence = simulation_evidence(db, run)
            ready = {
                "record_simulated_confirmation": "record_ready",
                "send_simulated_acknowledgement": "ack_ready",
                "send_simulated_options": "options_ready",
            }[decision.tool_name]
            if not evidence[ready]:
                deny = "SIMULATION_EVIDENCE_REQUIRED"
            else:
                reasons.append("SYNTHETIC_PATIENT_AND_APPOINTMENT_BOUND")
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
            if run.active_role == "engagement" and simulation_evidence(db, run).get(
                "record_required"
            ):
                required.add("record_simulated_confirmation")
            if not deny and not required.issubset(evidence_tools):
                deny = "SPECIALIST_EVIDENCE_INCOMPLETE"
            if not deny and run.active_role == "preparation":
                deny = validate_answers(db, run, decision)
                if not deny:
                    from forget_lah.runtime.scheduling import validate_review

                    deny = validate_review(db, run, decision)
    elif isinstance(decision, WaitDecision):
        if (
            simulation_enabled(run)
            and run.checkpoint["latest_event"]["kind"] == "demo_reply"
            and decision.reason_code == "AWAITING_PATIENT_REPLY"
        ):
            deny = "PATIENT_REPLY_ALREADY_AVAILABLE"
    elif isinstance(decision, EscalateDecision):
        if decision.reason_code == "CLINICAL_REVIEW_REQUIRED":
            deny = "CLINICAL_ESCALATION_REQUIRES_STAFF_FLAG"
        elif decision.reason_code == "AMBIGUOUS_REPLY" and clarification_allowed(db, run):
            reasons.append("CLARIFICATION_FIRST_NO_HANDOFF")
        else:
            reasons.append("ADMINISTRATIVE_HANDOFF_ONLY")
    elif isinstance(decision, CompleteSimulationDecision):
        proof = simulation_evidence(db, run)["complete_evidence_ids"]
        if run.active_role != "coordinator":
            deny = "ONLY_COORDINATOR_CAN_COMPLETE"
        elif not proof or set(decision.evidence_ids) != set(proof):
            deny = "SIMULATED_CONFIRMATION_AND_ACK_REQUIRED"
        else:
            reasons.append("SOURCE_RECEIPT_AND_SIMULATED_DELIVERY_VERIFIED")
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
    clinical = existing_handoff is not None and existing_handoff.risk == "RED"
    return {
        "request_id": step.id,
        "case_id": case.id,
        "case_version": case.case_version,
        "action": "CLARIFY" if "CLARIFICATION_FIRST_NO_HANDOFF" in reasons else decision.step_type,
        "policy_version": "m2a-staff-clinical-flag-v2",
        "decision": "DENY" if deny else "ALLOW",
        "risk": "RED"
        if clinical or (isinstance(decision, ClinicalReportDecision) and not deny)
        else "AMBER"
        if decision.step_type == "ESCALATE" and "CLARIFICATION_FIRST_NO_HANDOFF" not in reasons
        else "GREEN",
        "reason_codes": [deny] if deny else reasons,
    }
