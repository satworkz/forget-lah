"""One persisted decision per worker tick. Network calls never hold DB locks."""

import json
from datetime import UTC, timedelta

from sqlalchemy import and_, or_, select

from forget_lah.db import FollowupCase, uid, utcnow
from forget_lah.runtime.budget import reserve_call
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.contracts import (
    REQUIRED_EVIDENCE_BY_ROLE,
    AttendanceDecision,
    ClinicalReportDecision,
    CompleteDecision,
    CompleteSimulationDecision,
    DelegateDecision,
    EscalateDecision,
    ReturnDecision,
    SelectionDecision,
    ToolDecision,
    ToolResult,
    WaitDecision,
    parse_decision,
    tools_for,
)
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentRun,
    AgentStep,
    SimulatedMessage,
    StaffHandoff,
)
from forget_lah.runtime.policy import has_authority, policy_for
from forget_lah.runtime.provider import ModelError, model_for
from forget_lah.runtime.simulation import (
    booking_choice,
    current_tools,
    future_scheduled,
    latest_selection_offer,
    latest_tool,
    read_already_available,
    reply_evidence,
    save_acknowledgement,
    save_options,
    save_reminder,
    saved_reply,
    simulation_enabled,
    simulation_evidence,
    unsupported_question_reply,
)
from forget_lah.service_identity import AUTOMATION_PRINCIPAL_ID


def as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def release(run, status, *, delay=None):
    run.status = status
    run.lease_until = run.lease_token = None
    run.available_at = utcnow() + timedelta(seconds=delay) if delay is not None else None


def pause(run, code):
    run.checkpoint = {**run.checkpoint, "pause_reason": code}
    release(run, "paused")


def authority_revoked(run):
    return (
        "SERVICE_AUTHORITY_REVOKED"
        if run.authorised_by == AUTOMATION_PRINCIPAL_ID
        else "STAFF_AUTHORITY_REVOKED"
    )


def abort_delegation(db, run):
    for delegation in db.scalars(
        select(AgentDelegation).where(
            AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
        )
    ):
        delegation.status = "aborted"


def request_handoff(db, run, reason, *, risk):
    existing = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
    if not existing:
        db.add(
            StaffHandoff(
                id=uid(),
                clinic_id=run.clinic_id,
                case_id=run.case_id,
                run_id=run.id,
                reason_code=reason,
                risk=risk,
            )
        )
    abort_delegation(db, run)
    run.active_role = "coordinator"
    release(run, "escalated")


def claim_run(factory):
    now = utcnow()
    with factory.begin() as db:
        run = db.scalar(
            select(AgentRun)
            .where(
                or_(
                    and_(AgentRun.status.in_(["queued", "waiting"]), AgentRun.available_at <= now),
                    and_(AgentRun.status == "running", AgentRun.lease_until < now),
                )
            )
            .order_by(AgentRun.available_at, AgentRun.created_at, AgentRun.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not run:
            return None
        if not has_authority(db, run):
            pause(run, authority_revoked(run))
            return None
        if run.status == "waiting":
            if simulation_enabled(run) and run.checkpoint.get("next_source_retry"):
                run.checkpoint = {
                    **run.checkpoint,
                    "latest_event": {**run.checkpoint["latest_event"], "wake_reason": "timer"},
                }
            else:
                abort_delegation(db, run)
                run.active_role = "coordinator"
                run.checkpoint = {
                    **run.checkpoint,
                    "latest_event": {
                        **run.checkpoint["latest_event"],
                        "id": uid(),
                        "wake_reason": "timer",
                    },
                    "returned_specialists": [],
                    "delegation_start": 0,
                }
        run.status, run.lease_token = "running", uid()
        run.lease_until = now + timedelta(seconds=120)
        return run.id, run.lease_token


def current_run(db, run_id, token):
    run = db.scalar(
        select(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.status == "running",
            AgentRun.lease_token == token,
            AgentRun.lease_until > utcnow(),
        )
        .with_for_update()
    )
    return run


def current_case(db, run):
    return db.scalar(
        select(FollowupCase)
        .where(FollowupCase.id == run.case_id, FollowupCase.clinic_id == run.clinic_id)
        .with_for_update()
    )


def observation_for(db, run, case, step_id):
    event = run.checkpoint["latest_event"]
    recent = list(
        db.scalars(
            select(AgentStep)
            .where(AgentStep.run_id == run.id, AgentStep.status == "completed")
            .order_by(AgentStep.sequence.desc())
            .limit(24)
        )
    )
    tools = [
        {"id": step.id, "role": step.role, "sequence": step.sequence, "result": step.tool_result}
        for step in reversed(recent)
        if step.tool_result and step.observation.get("latest_event", {}).get("id") == event["id"]
    ][-6:]
    # Repeated reads remain in the journey; only the newest context is needed by the model.
    newest_context = next(
        (t["id"] for t in reversed(tools) if t["result"]["tool_name"] == "read_followup_context"),
        None,
    )
    tools = [
        t
        for t in tools
        if t["result"]["tool_name"] != "read_followup_context" or t["id"] == newest_context
    ]
    # The model needs receipt evidence, never source patient identifiers.
    tools = [
        {
            **t,
            "result": {
                **t["result"],
                "data": {
                    k: v
                    for k, v in t["result"]["data"].items()
                    if k not in {"patient_id", "source_episode_ref", "run_id"}
                },
            },
        }
        for t in tools
    ]
    # Slot offers are rendered from the full saved source result by application code.
    # Planning needs a bounded preview, not every slot repeated on every model turn.
    # AgentStep.tool_result retains the complete returned source page for audit/policy.
    for tool in tools:
        data = tool["result"]["data"]
        slots = data.get("available_slots")
        if slots is not None:
            data["available_slots"] = slots[:3]
            data["saved_slot_count"] = len(slots)
            data["more_available_slots"] = len(slots) > 3 or data.get("more_available_slots", False)
    handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
    delegation = db.scalar(
        select(AgentDelegation).where(
            AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
        )
    )
    eligible = [
        t
        for t in tools
        if delegation
        and t["role"] == run.active_role
        and t["sequence"] > delegation.start_sequence
        and t["result"]["status"] == "succeeded"
    ]
    required = REQUIRED_EVIDENCE_BY_ROLE[run.active_role]
    simulation = simulation_evidence(db, run)
    if run.active_role == "engagement" and simulation.get("record_required"):
        required = (*required, "record_simulated_confirmation")
    completed_tools = {t["result"]["tool_name"] for t in eligible}
    return {
        "request_id": step_id,
        "expected_case_version": case.case_version,
        "role": run.active_role,
        "goal": delegation.goal if delegation else run.goal,
        "case": {"specialty": case.specialty, "trigger": case.trigger},
        "latest_event": event,
        "tools": tools,
        "return_requirements": {
            "required_tools": list(required),
            "missing_tools": [name for name in required if name not in completed_tools],
            "eligible_evidence_ids": [t["id"] for t in eligible],
        },
        "returned_specialists": run.checkpoint.get("returned_specialists", []),
        "specialist_reports": [
            {"role": d.target, "reason_code": d.result_reason_code, "evidence_ids": d.evidence_ids}
            for d in db.scalars(
                select(AgentDelegation)
                .where(
                    AgentDelegation.run_id == run.id,
                    AgentDelegation.status == "returned",
                    AgentDelegation.event_id == event["id"],
                    AgentDelegation.target.in_(run.checkpoint.get("returned_specialists", [])),
                )
                .order_by(AgentDelegation.start_sequence.desc())
                .limit(2)
            )
        ],
        "delegation_start": run.checkpoint.get("delegation_start", 0),
        "handoff": {"id": handoff.id, "accepted": bool(handoff.accepted_by)} if handoff else None,
        "allowed_tools": [
            name
            for name in tools_for(run.active_role, simulation_enabled(run))
            if not read_already_available(db, run, name)
        ],
        "simulation": simulation,
        "outreach_enabled": False,
        "booking_writes_enabled": False,
    }


def rule_escalation(db, run, case):
    run.step_count += 1
    step_id = uid()
    db.add(
        AgentStep(
            id=step_id,
            clinic_id=run.clinic_id,
            case_id=run.case_id,
            run_id=run.id,
            sequence=run.step_count,
            case_version=case.case_version,
            role="coordinator",
            origin="rule",
            status="completed",
            observation={"latest_event": run.checkpoint["latest_event"]},
            decision={"step_type": "ESCALATE", "reason_code": "CLINICAL_REVIEW_REQUIRED"},
            policy={
                "request_id": step_id,
                "case_id": case.id,
                "case_version": case.case_version,
                "decision": "ALLOW",
                "risk": "RED",
                "reason_codes": ["STAFF_FLAGGED_CLINICAL_CONCERN"],
                "policy_version": "m2a-staff-clinical-flag-v2",
                "action": "ESCALATE",
            },
        )
    )
    request_handoff(db, run, "CLINICAL_REVIEW_REQUIRED", risk="RED")
    case.case_version += 1


def apply_initial_demo_wait(db, settings, run, case, step):
    """Save a fixed demo checkpoint without asking the model to choose WAIT."""
    observation = step.observation
    if (
        run.active_role != "engagement"
        or observation["latest_event"]["kind"] != "started"
        or observation["outreach_enabled"] is not False
        or observation["booking_writes_enabled"] is not False
    ):
        return False
    delegation = db.scalar(
        select(AgentDelegation).where(
            AgentDelegation.run_id == run.id,
            AgentDelegation.status == "active",
            AgentDelegation.target == "engagement",
            AgentDelegation.event_id == observation["latest_event"]["id"],
        )
    )
    # Only reuse the latest context result from this event. A failed or absent
    # source read must still go through normal recovery, never this shortcut.
    source = next(
        (
            tool
            for tool in reversed(observation["tools"])
            if tool["result"]["tool_name"] == "read_followup_context"
        ),
        None,
    )
    if not delegation or not source or source["result"]["status"] != "succeeded":
        return False
    if any(
        previous.observation.get("latest_event", {}).get("id") == observation["latest_event"]["id"]
        for previous in db.scalars(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.role == "engagement",
                AgentStep.origin == "rule",
                AgentStep.status == "completed",
            )
        )
    ):
        return False
    data = source["result"].get("data", {})
    if (
        data.get("can_contact_patient") is not False
        or data.get("can_write_appointments") is not False
    ):
        return False
    decision = WaitDecision(
        request_id=step.id,
        expected_case_version=case.case_version,
        step_type="WAIT",
        reason_code="AWAITING_PATIENT_REPLY",
        wake_after_seconds=0,
    )
    step.origin = "rule"
    step.observation = {
        **observation,
        "application_rule": {
            "name": "INITIAL_DEMO_REPLY_WAIT",
            "source_step_id": source["id"],
            "delegation_id": delegation.id,
            "explanation": "Outreach is disabled; wait for a staff-entered demo reply. No message was sent.",
        },
    }
    step.decision = decision.model_dump()
    step.policy = policy_for(db, run, case, step, decision)
    if step.policy["decision"] != "ALLOW":
        step.status, step.error_code = "rejected", "POLICY_DENIED"
        pause(run, "POLICY_DENIED")
    else:
        if simulation_enabled(run) and settings.simulation_configured:
            message = save_reminder(db, run, source)
            step.observation = {
                **step.observation,
                "application_rule": {
                    **step.observation["application_rule"],
                    "explanation": "A reminder was displayed in the patient simulator; wait for a staff-entered synthetic reply.",
                    "simulated_message_id": message.id,
                },
            }
        apply_control(db, run, case, step, decision, settings)
    return True


def prepare_step(factory, settings, run_id, token):
    with factory.begin() as db:
        run = current_run(db, run_id, token)
        if not run:
            return None
        case = current_case(db, run)
        if run.mode != settings.agent_model_mode:
            pause(run, "MODEL_MODE_CHANGED")
            return None
        if not has_authority(db, run):
            pause(run, authority_revoked(run))
            return None
        if run.checkpoint["latest_event"]["kind"] == "clinical_concern":
            rule_escalation(db, run, case)
            return None
        pending = db.scalar(
            select(AgentStep)
            .where(AgentStep.run_id == run.id, AgentStep.status.in_(["pending", "tool_pending"]))
            .order_by(AgentStep.sequence)
            .limit(1)
        )
        if pending and (
            pending.case_version != case.case_version or pending.role != run.active_role
        ):
            pending.status, pending.error_code = "rejected", "STALE_CHECKPOINT"
            pause(run, "STALE_CHECKPOINT")
            return None
        if not pending:
            if run.step_count >= settings.agent_max_steps:
                pause(run, "STEP_BUDGET_EXHAUSTED")
                return None
            # Per-event Coordinator limit and per-delegation specialist limit.
            steps = list(db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)))
            active = [
                s
                for s in steps
                if s.role == run.active_role
                and (
                    run.active_role != "coordinator"
                    or s.sequence > run.checkpoint.get("coordinator_resume_after", 0)
                )
                and not (simulation_enabled(run) and s.origin == "rule")
                and (
                    s.observation.get("latest_event", {}).get("id")
                    == run.checkpoint["latest_event"]["id"]
                    if run.active_role == "coordinator"
                    else s.sequence > run.checkpoint.get("delegation_start", 0)
                )
            ]
            if len(active) >= (
                6 if simulation_enabled(run) or run.active_role != "coordinator" else 4
            ):
                pause(run, "ROLE_BUDGET_EXHAUSTED")
                return None
            step_id = uid()
            run.step_count += 1
            pending = AgentStep(
                id=step_id,
                clinic_id=run.clinic_id,
                case_id=run.case_id,
                run_id=run.id,
                sequence=run.step_count,
                case_version=case.case_version,
                role=run.active_role,
                origin="mock" if run.mode == "mock" else "model",
                status="pending",
                observation=observation_for(db, run, case, step_id),
            )
            db.add(pending)
            db.flush()
            # Existing pending model attempts retain their original provenance.
            # Apply rules before reserving a live call or incrementing attempts.
            retry_tool = (
                run.checkpoint.get("next_source_retry") if simulation_enabled(run) else None
            )
            if retry_tool and run.checkpoint["latest_event"].get("wake_reason") == "timer":
                retries = run.checkpoint.get("simulated_tool_retries", {})
                run.checkpoint = {
                    **run.checkpoint,
                    "next_source_retry": None,
                    "simulated_tool_retries": {
                        **retries,
                        retry_tool: retries.get(retry_tool, 0) + 1,
                    },
                }
                decision = ToolDecision(
                    request_id=pending.id,
                    expected_case_version=case.case_version,
                    step_type="TOOL",
                    tool_name=retry_tool,
                    reason_code={
                        "record_simulated_confirmation": "RECORD_SIMULATED_CONFIRMATION",
                        "send_simulated_acknowledgement": "SEND_SIMULATED_ACKNOWLEDGEMENT",
                        "send_simulated_options": "SEND_SIMULATED_OPTIONS",
                    }[retry_tool],
                )
                pending.origin = "rule"
                pending.observation = {
                    **pending.observation,
                    "application_rule": {
                        "name": "SIMULATED_SOURCE_RETRY",
                        "explanation": "The worker retried the failed simulated tool with the same reply binding. No model call was needed; check the actual result.",
                    },
                }
                pending.decision = decision.model_dump()
                pending.policy = policy_for(db, run, case, pending, decision)
                if pending.policy["decision"] != "ALLOW":
                    pending.status, pending.error_code = "rejected", "POLICY_DENIED"
                    pause(run, "POLICY_DENIED")
                    return None
                pending.status = "tool_pending"
            elif (
                settings.simulation_configured
                and run.active_role == "engagement"
                and pending.observation["simulation"]["record_ready"]
                and not any(
                    s.tool_result
                    and s.tool_result.get("tool_name") == "record_simulated_confirmation"
                    and s.observation.get("latest_event", {}).get("id")
                    == run.checkpoint["latest_event"]["id"]
                    for s in steps
                )
            ):
                decision = ToolDecision(
                    request_id=pending.id,
                    expected_case_version=case.case_version,
                    step_type="TOOL",
                    reason_code="RECORD_SIMULATED_CONFIRMATION",
                    tool_name="record_simulated_confirmation",
                )
                pending.origin = "rule"
                pending.observation = {
                    **pending.observation,
                    "application_rule": {
                        "name": "EXPLICIT_SIMULATED_CONFIRMATION",
                        "explanation": "The worker recorded the explicitly confirmed simulator action through the gateway. The source still checks the appointment or selected slot. No model call was needed to authorize this action.",
                    },
                }
                pending.decision = decision.model_dump()
                pending.policy = policy_for(db, run, case, pending, decision)
                if pending.policy["decision"] != "ALLOW":
                    pending.status, pending.error_code = "rejected", "POLICY_DENIED"
                    pause(run, "POLICY_DENIED")
                    return None
                pending.status = "tool_pending"
            elif (
                pending.sequence == 1
                and run.active_role == "coordinator"
                and pending.observation["latest_event"]["kind"] == "started"
            ):
                decision = ToolDecision(
                    request_id=pending.id,
                    expected_case_version=case.case_version,
                    step_type="TOOL",
                    reason_code="READ_SOURCE",
                    tool_name="read_followup_context",
                )
                pending.origin = "rule"
                pending.observation = {
                    **pending.observation,
                    "application_rule": {
                        "name": "INITIAL_SOURCE_READ",
                        "explanation": "A new routine review requires current clinic context before model planning.",
                    },
                }
                pending.decision = decision.model_dump()
                pending.policy = policy_for(db, run, case, pending, decision)
                if pending.policy["decision"] != "ALLOW":
                    pending.status, pending.error_code = "rejected", "POLICY_DENIED"
                    pause(run, "POLICY_DENIED")
                    return None
                pending.status = "tool_pending"
            elif apply_initial_demo_wait(db, settings, run, case, pending):
                return None
        if pending.status == "pending":
            if pending.attempts >= 2:
                pending.status, pending.error_code = "error", "MODEL_ATTEMPTS_EXHAUSTED"
                pause(run, "MODEL_ATTEMPTS_EXHAUSTED")
                return None
            if run.mode != "mock":
                error, delay = reserve_call(db, settings)
                if error:
                    if delay:
                        release(run, "queued", delay=delay)
                    else:
                        pause(run, error)
                    return None
            pending.attempts += 1
        return {
            "step_id": pending.id,
            "mode": run.mode,
            "phase": pending.status,
            "observation": pending.observation,
            "repair": pending.error_code == "MODEL_SCHEMA_INVALID",
            "binding": {
                "clinic_id": case.clinic_id,
                "patient_id": case.patient_id,
                "source_episode_ref": case.source_episode_ref,
            },
        }


def record_failure(factory, run_id, token, step_id, code, *, retryable=False, delay=30):
    with factory.begin() as db:
        run = current_run(db, run_id, token)
        if not run:
            return False
        step = db.get(AgentStep, step_id)
        step.error_code = code
        if retryable and step.attempts < 2:
            release(run, "queued", delay=delay)
        else:
            step.status = "rejected" if code == "MODEL_SCHEMA_INVALID" else "error"
            pause(run, code)
        return True


def apply_control(db, run, case, step, decision, settings):
    step.status = "completed"
    case.case_version += 1
    delay = settings.agent_min_interval_seconds
    if isinstance(decision, ClinicalReportDecision):
        reply = saved_reply(db, run)
        body = "Thank you for letting us know. "
        if decision.attendance_quote:
            body = "Thank you for confirming that you plan to attend. "
        body += (
            "You reported: “"
            + "”; “".join(decision.symptom_quotes)
            + "”. I’ve flagged your message for clinical review and requested that the clinic team call you back as soon as possible."
        )
        message = SimulatedMessage(
            clinic_id=run.clinic_id,
            case_id=run.case_id,
            run_id=run.id,
            event_id=reply.id,
            kind="clinical_acknowledgement",
            body=body,
            source_version="patient-report-v1",
            evidence={"clinical_step_id": step.id, "reply_event_id": reply.id},
        )
        db.add(message)
        db.flush()
        run.checkpoint = {
            **run.checkpoint,
            "clinical_review": {
                "status": "requested",
                "patient_message": reply.content,
                "symptom_quotes": decision.symptom_quotes,
                "attendance_intent": "stated" if decision.attendance_quote else "not_stated",
                "attendance_quote": decision.attendance_quote,
                "reply_event_id": reply.id,
                "decision_step_id": step.id,
                "acknowledgement_id": message.id,
                "requested_at": utcnow().isoformat(),
            },
        }
        request_handoff(db, run, "PATIENT_REPORTED_SYMPTOMS", risk="RED")
    elif isinstance(decision, SelectionDecision):
        if decision.option_number is None:
            offer = latest_selection_offer(db, run)
            body = "Which option would you like me to book? Please tell me which time suits you. Your existing appointment has not been changed."
            if limitation := unsupported_question_reply(decision.unsupported_question):
                body += "\n\n" + limitation
            db.add(
                SimulatedMessage(
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    event_id=saved_reply(db, run).id,
                    kind="clarification",
                    body=body,
                    source_version=offer.source_version,
                    evidence={
                        "selection_step_id": step.id,
                        "offer_id": offer.id,
                        "unsupported_question": decision.unsupported_question,
                    },
                )
            )
            abort_delegation(db, run)
            run.active_role = "coordinator"
            run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
            release(run, "waiting")
        else:
            run.checkpoint = {
                **run.checkpoint,
                "selection": {
                    "step_id": step.id,
                    "offer_id": decision.offer_id,
                    "reply_event_id": decision.reply_event_id,
                },
            }
            release(run, "queued", delay=delay)
    elif isinstance(decision, AttendanceDecision):
        run.checkpoint = {
            **run.checkpoint,
            "attendance": {"step_id": step.id, "reply_event_id": decision.reply_event_id},
        }
        if decision.confirmed:
            release(run, "queued", delay=delay)
        else:
            from forget_lah.runtime.simulation import appointment_time

            source = db.get(AgentStep, decision.source_step_id)
            date = appointment_time(source.tool_result["data"]["scheduled_at"])
            body = f"Are you confirming that you’ll attend your appointment on {date}? Your appointment has not been changed."
            if limitation := unsupported_question_reply(decision.unsupported_question):
                body += "\n\n" + limitation
            db.add(
                SimulatedMessage(
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    event_id=decision.reply_event_id,
                    kind="clarification",
                    body=body,
                    source_version=source.tool_result["source_version"],
                    evidence={
                        "attendance_step_id": step.id,
                        "unsupported_question": decision.unsupported_question,
                    },
                )
            )
            abort_delegation(db, run)
            run.active_role = "coordinator"
            run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
            release(run, "waiting")
    elif isinstance(decision, DelegateDecision):
        db.add(
            AgentDelegation(
                id=uid(),
                clinic_id=run.clinic_id,
                case_id=run.case_id,
                run_id=run.id,
                target=decision.target,
                event_id=run.checkpoint["latest_event"]["id"],
                goal=decision.goal,
                start_sequence=step.sequence,
            )
        )
        run.active_role = decision.target
        run.checkpoint = {**run.checkpoint, "delegation_start": step.sequence}
        release(run, "queued", delay=delay)
    elif isinstance(decision, ReturnDecision):
        delegation = db.scalar(
            select(AgentDelegation).where(
                AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
            )
        )
        delegation.status, delegation.evidence_ids = "returned", decision.evidence_ids
        delegation.result_reason_code = decision.reason_code
        returned = run.checkpoint.get("returned_specialists", []) + [run.active_role]
        run.active_role = "coordinator"
        run.checkpoint = {**run.checkpoint, "returned_specialists": returned, "delegation_start": 0}
        release(run, "queued", delay=delay)
    elif isinstance(decision, WaitDecision):
        run.checkpoint = {**run.checkpoint, "wait_reason": decision.reason_code}
        if simulation_enabled(run) and decision.reason_code == "SOURCE_TEMPORARILY_UNAVAILABLE":
            previous = db.scalar(
                select(AgentStep)
                .where(
                    AgentStep.run_id == run.id,
                    AgentStep.sequence < step.sequence,
                    AgentStep.tool_result.is_not(None),
                )
                .order_by(AgentStep.sequence.desc())
            )
            if (
                previous
                and previous.tool_result.get("retryable")
                and previous.tool_result["tool_name"]
                in {
                    "record_simulated_confirmation",
                    "send_simulated_acknowledgement",
                    "send_simulated_options",
                }
            ):
                name = previous.tool_result["tool_name"]
                if run.checkpoint.get("simulated_tool_retries", {}).get(name, 0) >= 2:
                    pause(run, "SOURCE_ATTEMPTS_EXHAUSTED")
                    return
                run.checkpoint = {**run.checkpoint, "next_source_retry": name}
        release(run, "waiting", delay=decision.wake_after_seconds or None)
    elif isinstance(decision, EscalateDecision):
        request_handoff(db, run, decision.reason_code, risk=step.policy["risk"])
    elif isinstance(decision, CompleteDecision):
        run.checkpoint = {**run.checkpoint, "outcome": "OWNED_STAFF_HANDOFF"}
        release(run, "completed")
    elif isinstance(decision, CompleteSimulationDecision):
        run.checkpoint = {**run.checkpoint, "outcome": "SIMULATED_ATTENDANCE_CONFIRMED"}
        release(run, "completed")


def store_proposal(factory, settings, run_id, token, step_id, reply):
    with factory.begin() as db:
        run = current_run(db, run_id, token)
        if not run:
            return None
        case = current_case(db, run)
        step = db.get(AgentStep, step_id)
        if step.status != "pending":
            return None
        if step.case_version != case.case_version or not has_authority(db, run):
            step.status, step.error_code = "rejected", "STALE_OR_REVOKED_CONTEXT"
            pause(run, "STALE_OR_REVOKED_CONTEXT")
            return None
        for field in ("input_tokens", "output_tokens"):
            value = getattr(reply, field)
            if value is not None:
                setattr(step, field, (getattr(step, field) or 0) + value)
        step.latency_ms = reply.latency_ms
        try:
            decision = parse_decision(reply.text, step.id, case.case_version)
        except ValueError:
            step.error_code = "MODEL_SCHEMA_INVALID"
            if step.attempts < 2:
                release(run, "queued", delay=settings.agent_min_interval_seconds)
            else:
                step.status = "rejected"
                pause(run, "MODEL_SCHEMA_INVALID")
            return None
        step.decision = decision.model_dump()
        step.error_code = None
        step.policy = policy_for(db, run, case, step, decision)
        if step.policy["decision"] != "ALLOW":
            step.status, step.error_code = "rejected", "POLICY_DENIED"
            pause(run, "POLICY_DENIED")
            return None
        if isinstance(decision, ToolDecision):
            step.status = "tool_pending"
            return decision.tool_name
        apply_control(db, run, case, step, decision, settings)
        return None


def execute_pending_tool(factory, settings, run_id, token, step_id, tools):
    # Persisted proposal is re-authorised immediately before dispatch. Read tools
    # are replay-safe if the worker dies after GET but before saving its result.
    with factory.begin() as db:
        run = current_run(db, run_id, token)
        if not run:
            return False
        case = current_case(db, run)
        step = db.get(AgentStep, step_id)
        if step.status != "tool_pending":
            return False
        try:
            decision = parse_decision(json.dumps(step.decision), step.id, case.case_version)
        except ValueError:
            step.status, step.error_code = "rejected", "STALE_CHECKPOINT"
            pause(run, "STALE_CHECKPOINT")
            return False
        verdict = policy_for(db, run, case, step, decision)
        step.policy = verdict
        if verdict["decision"] != "ALLOW":
            step.status, step.error_code = "rejected", "POLICY_DENIED"
            pause(run, "POLICY_DENIED")
            return False
        binding = {
            "clinic_id": case.clinic_id,
            "patient_id": case.patient_id,
            "source_episode_ref": case.source_episode_ref,
        }
        tool_name, version = decision.tool_name, case.case_version
        simulation_action = tool_name in {
            "record_simulated_confirmation",
            "send_simulated_acknowledgement",
            "send_simulated_options",
        }
        if simulation_action and not settings.simulation_configured:
            step.status, step.error_code = "rejected", "SIMULATOR_DISABLED"
            pause(run, "SIMULATOR_DISABLED")
            return False
        if tool_name == "record_simulated_confirmation":
            context = latest_tool(current_tools(db, run), "read_followup_context", "engagement")
            operation = {
                "operation_id": reply_evidence(db, run).id,
                "run_id": run.id,
                "expected_version": context.tool_result["data"]["episode_version"],
            }
            choice = booking_choice(db, run)
            if choice:
                operation.update(
                    slot_id=choice["slot"]["id"], slot_version=choice["slot"]["version"]
                )
                if context.tool_result["data"].get("can_simulate_rescheduling"):
                    operation["reschedule"] = True
    if tool_name == "record_simulated_confirmation":
        result = tools.confirm(binding, operation)
    elif tool_name in {"send_simulated_acknowledgement", "send_simulated_options"}:
        # Recheck the current source before displaying appointment details.
        result = tools.execute("read_followup_context", binding)
    else:
        result = tools.execute(tool_name, binding)
    with factory.begin() as db:
        run = current_run(db, run_id, token)
        if not run:
            if tool_name == "record_simulated_confirmation":
                stale_step = db.get(AgentStep, step_id)
                if (
                    stale_step
                    and stale_step.run_id == run_id
                    and stale_step.status == "rejected"
                    and stale_step.tool_result is None
                ):
                    stale_step.tool_result = result.model_dump()
                    stale_step.status, stale_step.error_code = (
                        "rejected",
                        "LATE_SIMULATED_WRITE_RESULT",
                    )
            return False
        case = current_case(db, run)
        step = db.get(AgentStep, step_id)
        if case.case_version != version or not has_authority(db, run):
            if tool_name == "record_simulated_confirmation":
                step.tool_result = result.model_dump()
            step.status, step.error_code = "rejected", "STALE_OR_REVOKED_CONTEXT"
            pause(run, "STALE_OR_REVOKED_CONTEXT")
            return False
        if tool_name == "send_simulated_options":
            context = latest_tool(current_tools(db, run), "read_followup_context", "engagement")
            if (
                result.status != "succeeded"
                or result.source_version != context.tool_result["source_version"]
                or not simulation_evidence(db, run)["options_ready"]
            ):
                result = ClinicTools.failure(
                    tool_name, result.error_code or "SOURCE_CONFLICT", result.retryable
                )
            else:
                message = save_options(db, run)
                result = ToolResult(
                    tool_name=tool_name,
                    status="succeeded",
                    source_version=message.source_version,
                    data={
                        "message_id": message.id,
                        "channel": "patient_simulator",
                        "delivery_status": "displayed_in_simulator",
                        "synthetic": True,
                    },
                    error_code=None,
                    retryable=False,
                )
        if tool_name == "send_simulated_acknowledgement":
            receipt = latest_tool(
                current_tools(db, run), "record_simulated_confirmation", "engagement"
            )
            if (
                result.status != "succeeded"
                or not future_scheduled(result.data)
                or result.data.get("episode_version")
                != receipt.tool_result["data"]["episode_version"]
                or result.data.get("scheduled_at") != receipt.tool_result["data"]["scheduled_at"]
                or not simulation_evidence(db, run)["ack_ready"]
            ):
                result = ClinicTools.failure(
                    tool_name, result.error_code or "SOURCE_CONFLICT", result.retryable
                )
            else:
                message = save_acknowledgement(db, run)
                result = ToolResult(
                    tool_name=tool_name,
                    status="succeeded",
                    source_version=message.source_version,
                    data={
                        "message_id": message.id,
                        "channel": "patient_simulator",
                        "delivery_status": "displayed_in_simulator",
                        "synthetic": True,
                    },
                    error_code=None,
                    retryable=False,
                )
        step.tool_result, step.status = result.model_dump(), "completed"
        case.case_version += 1
        if (
            tool_name == "send_simulated_acknowledgement"
            and result.status == "succeeded"
            and run.checkpoint.get("callback")
        ):
            request_handoff(db, run, "PATIENT_QUESTION_CALLBACK", risk="AMBER")
            step.tool_result = {
                **step.tool_result,
                "data": {
                    **step.tool_result["data"],
                    "callback": run.checkpoint["callback"],
                    "handoff_origin": "rule",
                },
            }
        elif tool_name == "send_simulated_options" and result.status == "succeeded":
            if message.evidence.get("selection_changed"):
                request_handoff(db, run, "SLOT_SELECTION_CHANGED", risk="AMBER")
            elif not message.evidence["slots"]:
                request_handoff(db, run, "NO_AVAILABLE_SLOTS", risk="AMBER")
            else:
                run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
                release(run, "waiting")
        else:
            release(run, "queued", delay=settings.agent_min_interval_seconds)
        return True


def process_run(factory, settings, run_id, token, *, model=None, tools=None):
    work = prepare_step(factory, settings, run_id, token)
    if work is None:
        return False
    tools = tools or ClinicTools(
        settings.mock_clinic_url,
        followup_key=(
            settings.mock_clinic_followup_key.get_secret_value()
            if settings.mock_clinic_followup_key
            else None
        ),
    )
    if work["phase"] == "pending":
        provider = model or model_for(settings, work["mode"])
        try:
            reply = provider.decide(work["observation"], repair=work["repair"])
        except ModelError as exc:
            return record_failure(
                factory,
                run_id,
                token,
                work["step_id"],
                exc.code,
                retryable=exc.retryable,
                delay=exc.retry_after,
            )
        tool_name = store_proposal(factory, settings, run_id, token, work["step_id"], reply)
        if tool_name is None:
            return True
    return execute_pending_tool(factory, settings, run_id, token, work["step_id"], tools)
