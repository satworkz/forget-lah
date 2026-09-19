"""One persisted decision per worker tick. Network calls never hold DB locks."""

import json
from datetime import UTC, timedelta, timezone

from sqlalchemy import and_, or_, select

from forget_lah.db import FollowupCase, uid, utcnow
from forget_lah.runtime.adaptation import preferences_for, remember_reported_exclusions
from forget_lah.runtime.budget import reserve_call
from forget_lah.runtime.clinic_tools import ClinicTools
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
    NeedsDecision,
    ReturnDecision,
    SelectionDecision,
    ToolDecision,
    ToolResult,
    WaitDecision,
    parse_decision,
    tools_for,
)
from forget_lah.runtime.memory import (
    LANGUAGE_QUESTION,
    delivery_block,
    effective_memory,
    language_ack,
    persist_needs,
)
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentRun,
    AgentStep,
    SimulatedMessage,
    StaffHandoff,
    message_order,
)
from forget_lah.runtime.policy import has_authority, policy_for
from forget_lah.runtime.provider import ModelError, model_for
from forget_lah.runtime.questions import question_response
from forget_lah.runtime.responses import (
    appointment_facts,
    defer_response,
    memory_ack,
    patient_message,
)
from forget_lah.runtime.scheduling import normalize_review
from forget_lah.runtime.simulation import (
    booking_choice,
    clarification_allowed,
    clarification_count,
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
from forget_lah.runtime.validation import validation_failure
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
    if run.active_role == "coordinator":
        for tool in tools:
            # Engagement inspects slot details; Coordinator receives the saved count.
            tool["result"].get("data", {}).pop("available_slots", None)
    completed_tools = {t["result"]["tool_name"] for t in eligible}
    conversation = []
    if (
        run.active_role == "coordinator"
        and event.get("kind") == "demo_reply"
        and not run.checkpoint.get("returned_specialists")
        and run.checkpoint.get("barriers", {}).get("reply_event_id")
        != event.get("reply_event_id", event.get("id"))
    ):
        messages = list(
            db.scalars(
                select(SimulatedMessage)
                .where(
                    SimulatedMessage.run_id.in_(
                        [run.id, run.checkpoint.get("reopened_from_run_id", run.id)]
                    ),
                    SimulatedMessage.case_id == run.case_id,
                    SimulatedMessage.clinic_id == run.clinic_id,
                )
                .order_by(SimulatedMessage.created_at.desc(), message_order().desc())
                .limit(1)
            )
        )
        conversation = [{"kind": m.kind, "text": m.body[:450]} for m in reversed(messages)]
    return {
        "request_id": step_id,
        "expected_case_version": case.case_version,
        "role": run.active_role,
        "goal": delegation.goal if delegation else run.goal,
        "case": {"specialty": case.specialty, "trigger": case.trigger},
        "latest_event": event,
        "recent_messages": conversation,
        "today_sgt": utcnow().astimezone(timezone(timedelta(hours=8))).date().isoformat(),
        "clarification_count": clarification_count(db, run),
        "patient_memory": effective_memory(db, case),
        "patient_questions": run.checkpoint.get("patient_questions", []),
        "patient_task_types": run.checkpoint.get("patient_task_types", []),
        "appointment_intent": run.checkpoint.get("appointment_intent", "UNSPECIFIED"),
        "appointment": appointment_facts(db, run)
        if run.active_role == "coordinator" and not run.checkpoint.get("needs_reviewed")
        else None,
        "needs_reviewed": run.checkpoint.get("needs_reviewed")
        == event.get("reply_event_id", event.get("id")),
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
        "barriers": run.checkpoint.get("barriers", {}),
        "preferences": {
            k: v
            for k, v in preferences_for(db, case).items()
            if k in {"earliest_minute", "latest_minute", "excluded_minutes"}
        },
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
            block = delivery_block(db, case, proactive=True, settings=settings)
            if block:
                step.observation["application_rule"].update(
                    name="OUTREACH_SUPPRESSED", explanation=f"No reminder displayed: {block}"
                )
                run.checkpoint = {**run.checkpoint, "wait_reason": block}
                if block == "LANGUAGE_SUPPORT_REQUIRED":
                    request_handoff(db, run, block, risk="AMBER")
                else:
                    release(run, "waiting")
                return True
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


def apply_required_read(db, settings, run, case, step):
    """Execute mandatory specialist reads; Claude still interprets and returns evidence."""
    if not settings.agent_required_reads_enabled or run.active_role not in {
        "engagement",
        "preparation",
    }:
        return False
    obs = step.observation
    attempted = {
        t["result"]["tool_name"]
        for t in obs["tools"]
        if t["role"] == run.active_role and t["sequence"] > obs["delegation_start"]
    }
    read = next(
        (
            name
            for name in obs["return_requirements"]["missing_tools"]
            if name in {"read_followup_context", "get_approved_instructions", "check_prerequisites"}
            and name in obs["allowed_tools"]
            and name not in attempted
        ),
        None,
    )
    # A failed read needs the usual model recovery path before any other work.
    if not read or any(
        t["result"]["status"] != "succeeded"
        for t in obs["tools"]
        if t["role"] == run.active_role and t["sequence"] > obs["delegation_start"]
    ):
        return False
    decision = ToolDecision(
        request_id=step.id,
        expected_case_version=case.case_version,
        step_type="TOOL",
        reason_code="READ_SOURCE",
        tool_name=read,
    )
    step.origin = "rule"
    step.observation = {
        **obs,
        "application_rule": {
            "name": "REQUIRED_SPECIALIST_READ",
            "explanation": "Read evidence required by the delegated role before model review. The policy gateway and source result remain authoritative.",
        },
    }
    step.decision = decision.model_dump()
    step.policy = policy_for(db, run, case, step, decision)
    if step.policy["decision"] != "ALLOW":
        step.status, step.error_code = "rejected", "POLICY_DENIED"
        pause(run, "POLICY_DENIED")
    else:
        step.status = "tool_pending"
    return True


def apply_accepted_handoff(db, settings, run, case, step):
    if (
        run.active_role != "coordinator"
        or run.checkpoint.get("latest_event", {}).get("kind") != "accept_handoff"
    ):
        return False
    if any(
        run.checkpoint.get(key, {}).get("status") not in {None, "resolved"}
        for key in ("callback", "clinical_review")
    ):
        return False
    handoff = db.scalar(
        select(StaffHandoff).where(
            StaffHandoff.run_id == run.id, StaffHandoff.clinic_id == run.clinic_id
        )
    )
    if not handoff or not handoff.accepted_by or not handoff.accepted_at:
        return False
    decision = CompleteDecision(
        request_id=step.id,
        expected_case_version=case.case_version,
        step_type="COMPLETE",
        reason_code="STAFF_HANDOFF_ACCEPTED",
        handoff_id=handoff.id,
    )
    step.origin = "rule"
    step.observation = {
        **step.observation,
        "application_rule": {
            "name": "ACCEPTED_STAFF_HANDOFF",
            "explanation": "Named staff accepted ownership; no unresolved callback or clinical review is auto-closed.",
        },
    }
    step.decision = decision.model_dump()
    step.policy = policy_for(db, run, case, step, decision)
    if step.policy["decision"] == "ALLOW":
        apply_control(db, run, case, step, decision, settings)
    else:
        step.status, step.error_code = "rejected", "POLICY_DENIED"
        pause(run, "POLICY_DENIED")
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
            if (
                run.step_count - run.checkpoint.get("turn_start_step", 0)
                >= settings.agent_max_steps
            ):
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
                and (
                    pending.observation["latest_event"]["kind"] == "started"
                    or run.checkpoint.get("reopened_from_run_id")
                )
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
            elif apply_accepted_handoff(db, settings, run, case, pending):
                return None
            elif apply_initial_demo_wait(db, settings, run, case, pending):
                return None
            elif apply_required_read(db, settings, run, case, pending):
                if pending.status != "tool_pending":
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
            "observation": {
                **pending.observation,
                **(
                    {"validation_errors": pending.validation_failures[-1]["errors"]}
                    if pending.error_code in {"MODEL_SCHEMA_INVALID", "MODEL_EVIDENCE_INVALID"}
                    and pending.validation_failures
                    else {}
                ),
            },
            "repair": pending.error_code in {"MODEL_SCHEMA_INVALID", "MODEL_EVIDENCE_INVALID"},
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
    delay = settings.agent_step_delay_seconds
    if isinstance(decision, NeedsDecision):
        persist_needs(db, case, decision, step.id)
        run.checkpoint = {
            **run.checkpoint,
            "needs_reviewed": decision.reply_event_id,
            "patient_questions": decision.patient_questions + decision.preparation_plans,
            "patient_task_types": ["QUESTION"] * len(decision.patient_questions)
            + ["PLAN"] * len(decision.preparation_plans),
            "appointment_intent": decision.appointment_intent,
        }
        memory = effective_memory(db, case)
        stopped_now = any(
            u.key == "contact_permission" and u.operation == "set" for u in decision.updates
        )
        language = memory.get("preferred_language", "en")
        block = delivery_block(db, case, settings=settings)

        def say(body, kind="needs_acknowledgement", source_message_id=None):
            db.add(
                patient_message(
                    run,
                    clinic_id=case.clinic_id,
                    case_id=case.id,
                    run_id=run.id,
                    event_id=decision.reply_event_id,
                    kind=kind,
                    body=body,
                    source_version="patient-memory-v1",
                    evidence={
                        "decision_step_id": step.id,
                        "reply_event_id": decision.reply_event_id,
                        **({"source_message_id": source_message_id} if source_message_id else {}),
                    },
                )
            )
            db.flush()

        if stopped_now:
            if not block:
                say(
                    "I've stopped automated reminders. Your appointment has not been changed. You can contact the clinic when you need help."
                )
            run.checkpoint = {**run.checkpoint, "wait_reason": "CONTACT_STOPPED"}
            release(run, "waiting")
            return
        if block:
            if language == "und" or (
                language == "en" and "en" in memory.get("excluded_languages", [])
            ):
                say(LANGUAGE_QUESTION, "clarification")
                run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_LANGUAGE_PREFERENCE"}
                release(run, "waiting")
            else:
                if language_ack(language):
                    say(language_ack(language))
                request_handoff(db, run, "LANGUAGE_SUPPORT_REQUIRED", risk="AMBER")
            return
        if decision.appointment_intent == "CANCEL":
            request = {
                "status": "requested",
                "topic": "appointment cancellation",
                "question": decision.appointment_request_quote,
                "reply_event_id": decision.reply_event_id,
                "decision_step_id": step.id,
            }
            run.checkpoint = {
                **run.checkpoint,
                "cancellation_request": request,
                "callback": run.checkpoint.get("callback") or request,
            }
            say(
                "I've asked the clinic team to help cancel your appointment and requested a callback. Your appointment has not been cancelled yet."
            )
            request_handoff(db, run, "CANCELLATION_REQUESTED", risk="AMBER")
            return
        language_changes = [
            u for u in decision.updates if u.key in {"preferred_language", "excluded_languages"}
        ]
        known_language = any(
            u.key == "preferred_language"
            and u.operation == "set"
            and u.value in {"en", "zh", "ms", "ta"}
            for u in language_changes
        )
        if (
            (known_language or decision.comprehension_quote)
            and len(language_changes) == len(decision.updates)
            and not (decision.patient_questions or decision.preparation_plans)
            and decision.appointment_intent == "UNSPECIFIED"
        ):
            from forget_lah.runtime.responses import restatement_content

            body, source_id = restatement_content(db, run)
            if decision.comprehension_quote:
                body = "Sorry for the confusion. " + body
            kind = (
                "comprehension_restatement"
                if decision.comprehension_quote
                else "language_restatement"
            )
            say(body, kind, source_id)
            run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
            release(run, "waiting")
            return
        if decision.concern_quote:
            defer_response(
                run,
                decision.reply_event_id,
                "empathy",
                "I'm sorry for the frustration this has caused.",
                step.id,
            )
        if decision.updates:
            defer_response(
                run, decision.reply_event_id, "memory", memory_ack(decision.updates), step.id
            )
        question = decision.question
        if known_language and len(language_changes) == len(decision.updates):
            question = None
        facts = appointment_facts(db, run)
        restrictions = {u.key for u in decision.updates if u.operation == "set"} & {
            "excluded_weekdays",
            "excluded_minutes",
        }
        if facts and restrictions and decision.appointment_intent == "UNSPECIFIED":
            from forget_lah.runtime.adaptation import matching_slots, preferences_for

            if matching_slots([{"starts_at": facts["scheduled_at"]}], preferences_for(db, case)):
                question = f"Your current appointment is on {facts['local_display']}, which does not conflict with that preference. Would you like to keep it, or choose another time?"
                run.checkpoint = {**run.checkpoint, "appointment_clarification": facts}
        if (
            not question
            and not (decision.patient_questions or decision.preparation_plans)
            and any(u.key == "arrival_support" and u.operation == "set" for u in decision.updates)
        ):
            question = "What would help with the concern you mentioned for this appointment?"
        if decision.appointment_intent == "CHANGE":
            # Persist the complete scheduling constraints before asking for missing
            # details, so a later short answer retains the known date/time context.
            question = None
        if question:
            say(question, "clarification")
            run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
            release(run, "waiting")
        else:
            release(run, "queued", delay=delay)
        return
    if isinstance(decision, (BarrierDecision, ClarifyDecision)) and decision.concern_quote:
        defer_response(
            run,
            decision.reply_event_id,
            "empathy",
            "I'm sorry for the frustration this has caused. Thank you for telling me.",
            step.id,
        )
    if isinstance(decision, (BarrierDecision, ClarifyDecision)) and decision.remember_exclusions:
        remember_reported_exclusions(db, case, decision, step.id)
        times = ", ".join(
            f"{minute // 60:02d}:{minute % 60:02d}" for minute in decision.excluded_minutes
        )
        defer_response(
            run,
            decision.reply_event_id,
            "memory",
            f"I've noted that {times} SGT does not work for you. I'll avoid suggesting those times in future follow-ups.",
            step.id,
        )
    if isinstance(decision, BarrierDecision):
        effective_action = decision.next_action
        if (
            effective_action == "CLARIFY_TIME"
            and decision.clarification_reason == "NONE"
            and decision.preparation_issue == "NONE"
            and run.checkpoint.get("appointment_intent") == "CHANGE"
        ):
            # Availability is a source fact, not a required patient preference.
            # Preserve the model proposal separately from this policy correction.
            effective_action = "SEARCH_SLOTS"
            step.observation = {
                **step.observation,
                "application_rule": "OPTIONAL_PREFERENCES_DO_NOT_BLOCK_SEARCH",
            }
        # Each assessed reply is a complete revised constraint set.
        # Explicit new availability can supersede a previous offer rejection.
        rejected = []
        if decision.rejects_current_offer:
            offer = latest_selection_offer(db, run)
            if offer:
                rejected = list(
                    dict.fromkeys(rejected + [s["id"] for s in offer.evidence.get("slots", [])])
                )[-30:]
        run.checkpoint = {
            **run.checkpoint,
            "barriers": {
                **decision.model_dump(
                    exclude={"request_id", "expected_case_version", "step_type", "reason_code"}
                ),
                "next_action": effective_action,
                "step_id": step.id,
                "rejected_slot_ids": rejected,
            },
        }
        negative_only = (
            decision.next_action == "SEARCH_SLOTS"
            and run.checkpoint.get("appointment_intent") != "CHANGE"
            and (decision.excluded_minutes or decision.rejects_current_offer)
            and decision.earliest_minute is None
            and decision.latest_minute is None
            and not decision.weekdays
            and decision.requested_date is None
            and decision.date_from is None
        )
        if effective_action == "CLARIFY_TIME" or negative_only:
            db.add(
                patient_message(
                    run,
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    event_id=decision.reply_event_id,
                    kind="clarification",
                    body=(
                        decision.clarification_question
                        or "Which dates and times would work for you and anyone accompanying you?"
                    )
                    + (
                        " Your appointment has not been changed."
                        if appointment_facts(db, run)
                        else ""
                    ),
                    source_version="patient-constraints-v1",
                    evidence={
                        "decision_step_id": step.id,
                        "clarification_reason": "AVAILABILITY_NOT_ESTABLISHED",
                    },
                )
            )
            run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
            release(run, "waiting")
        else:
            release(run, "queued", delay=delay)
    elif isinstance(decision, ClinicalReportDecision):
        if decision.contact_stop_quote:
            persist_needs(
                db,
                case,
                NeedsDecision(
                    request_id=decision.request_id,
                    expected_case_version=decision.expected_case_version,
                    step_type="REVIEW_NEEDS",
                    reason_code="PATIENT_NEEDS_REVIEWED",
                    reply_event_id=decision.reply_event_id,
                    updates=[
                        {
                            "key": "contact_permission",
                            "value": "stopped",
                            "scope": "future",
                            "quote": decision.contact_stop_quote,
                        }
                    ],
                ),
                step.id,
            )
        reply = saved_reply(db, run)
        body = "Thank you for letting us know. "
        if decision.attendance_quote:
            body = "Thank you for confirming that you plan to attend. "
        body += (
            "You reported: “"
            + "”; “".join(decision.symptom_quotes)
            + "”. I’ve flagged your message for clinical review and requested that the clinic team call you back as soon as possible."
        )
        if decision.contact_stop_quote:
            body += " Automated reminders have been stopped; this clinical review remains with the clinic."
        message = patient_message(
            run,
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
                patient_message(
                    run,
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
                patient_message(
                    run,
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
        if run.active_role == "preparation":
            run.checkpoint = {
                **run.checkpoint,
                "question_answers": [a.model_dump() for a in decision.question_answers],
                "question_review_step_id": step.id,
                "scheduling_review": normalize_review(
                    [r.model_dump() for r in decision.scheduling_review]
                ),
            }
        delegation.status, delegation.evidence_ids = "returned", decision.evidence_ids
        delegation.result_reason_code = decision.reason_code
        returned = run.checkpoint.get("returned_specialists", []) + [run.active_role]
        run.active_role = "coordinator"
        run.checkpoint = {**run.checkpoint, "returned_specialists": returned, "delegation_start": 0}
        if (
            delegation.target == "preparation"
            and run.checkpoint.get("patient_questions")
            and run.checkpoint.get("appointment_intent") == "UNSPECIFIED"
        ):
            prerequisite = latest_tool(current_tools(db, run), "check_prerequisites", "preparation")
            if prerequisite and prerequisite.tool_result["data"].get("prerequisites") == [
                "NOT_APPLICABLE"
            ]:
                reply = saved_reply(db, run)
                body = question_response(run, reply)
                if not run.checkpoint.get("callback"):
                    body += "\n\nWill you attend your scheduled appointment?"
                db.add(
                    patient_message(
                        run,
                        clinic_id=run.clinic_id,
                        case_id=run.case_id,
                        run_id=run.id,
                        event_id=reply.id,
                        kind="question_answer",
                        body=body,
                        source_version="approved-question-review-v1",
                        evidence={
                            "question_review_step_id": step.id,
                            "scheduling_review": [
                                r.model_dump() for r in decision.scheduling_review
                            ],
                            "question_answers": run.checkpoint["question_answers"],
                        },
                    )
                )
                if run.checkpoint.get("callback"):
                    request_handoff(db, run, "PATIENT_QUESTION_CALLBACK", risk="AMBER")
                else:
                    run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
                    release(run, "waiting")
                return
        barrier = run.checkpoint.get("barriers", {})
        if (
            delegation.target == "preparation"
            and barrier.get("preparation_issue", "NONE") != "NONE"
        ):
            question = "; ".join(barrier["evidence_quotes"])
            db.add(
                patient_message(
                    run,
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    event_id=saved_reply(db, run).id,
                    kind="preparation_callback",
                    body="Thank you for explaining what you need help with. I've requested a clinic callback about your preparation. Your appointment has not been changed. The clinic team will review the outstanding requirement with you.",
                    source_version="patient-constraints-v1",
                    evidence={
                        "barrier_step_id": barrier["step_id"],
                        "preparation_evidence_ids": decision.evidence_ids,
                    },
                )
            )
            run.checkpoint = {
                **run.checkpoint,
                "callback": {
                    "status": "requested",
                    "question": question,
                    "topic": "preparation",
                    "reply_event_id": saved_reply(db, run).id,
                    "decision_step_id": step.id,
                },
            }
            request_handoff(db, run, "PREPARATION_HELP_REQUIRED", risk="AMBER")
            return
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
    elif isinstance(decision, ClarifyDecision) or (
        isinstance(decision, EscalateDecision)
        and decision.reason_code == "AMBIGUOUS_REPLY"
        and clarification_allowed(db, run)
    ):
        reply = saved_reply(db, run)
        question = (
            decision.question
            if isinstance(decision, ClarifyDecision)
            else "Could you explain what you would like us to do about your appointment?"
        )
        db.add(
            patient_message(
                run,
                clinic_id=run.clinic_id,
                case_id=run.case_id,
                run_id=run.id,
                event_id=reply.id,
                kind="clarification",
                body=question,
                source_version="clarification-v1",
                evidence={
                    "general_clarification": True,
                    "decision_step_id": step.id,
                    "reply_event_id": reply.id,
                    "outcome": "WAITING_FOR_CLARIFICATION",
                },
            )
        )
        run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
        release(run, "waiting")
    elif isinstance(decision, EscalateDecision):
        request_handoff(db, run, decision.reason_code, risk=step.policy["risk"])
        reply = saved_reply(db, run)
        if (
            reply
            and run.checkpoint.get("latest_event", {}).get("channel") == "whatsapp_test"
            and not db.scalar(
                select(SimulatedMessage.id).where(
                    SimulatedMessage.run_id == run.id, SimulatedMessage.event_id == reply.id
                )
            )
        ):
            db.add(
                patient_message(
                    run,
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    event_id=reply.id,
                    kind="acknowledgement",
                    body="I've passed your request to the clinic team for help. Your request has not changed or cancelled the appointment.",
                    source_version="staff-handoff-v1",
                    evidence={"decision_step_id": step.id, "reason_code": decision.reason_code},
                )
            )
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
            patient_reply = saved_reply(db, run)
            repairs = []
            decision = parse_decision(
                reply.text,
                step.id,
                case.case_version,
                patient_source=patient_reply.content if patient_reply else None,
                quote_repairs=repairs,
            )
            if repairs:
                step.observation = {**step.observation, "evidence_quote_repairs": repairs}
        except ValueError as exc:
            step.validation_failures = [
                *(step.validation_failures or []),
                validation_failure(reply.text, exc, step.attempts),
            ][-2:]
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
            # Repair only malformed current-reply evidence, never authority,
            # consent, stale versions, role restrictions or tool permissions.
            repairable = {
                "QUESTION_NOT_IN_PATIENT_REPLY",
                "MEMORY_QUOTE_NOT_IN_PATIENT_REPLY",
                "APPOINTMENT_INTENT_QUOTE_NOT_IN_REPLY",
            }
            reasons = step.policy["reason_codes"]
            if isinstance(decision, NeedsDecision) and set(reasons) <= repairable:
                failure = validation_failure(reply.text, ValueError(), step.attempts)
                failure["errors"] = [
                    {
                        "field": "REVIEW_NEEDS",
                        "code": reason,
                        "message": "All evidence quotes and task items must be exact text from latest_event.content only. Use history to interpret the reply, not to copy previous tasks. Reassess this reply and return the complete corrected decision.",
                    }
                    for reason in reasons
                ]
                step.validation_failures = [*(step.validation_failures or []), failure][-2:]
                step.error_code = "MODEL_EVIDENCE_INVALID"
                if step.attempts < 2:
                    release(run, "queued", delay=settings.agent_min_interval_seconds)
                else:
                    step.status = "rejected"
                    pause(run, "MODEL_EVIDENCE_INVALID")
                return None
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
        if simulation_action and delivery_block(db, case, settings=settings):
            step.status, step.error_code = "rejected", "LANGUAGE_SUPPORT_REQUIRED"
            step.policy = {
                **step.policy,
                "decision": "DENY",
                "reason_codes": ["LANGUAGE_SUPPORT_REQUIRED"],
            }
            request_handoff(db, run, "LANGUAGE_SUPPORT_REQUIRED", risk="AMBER")
            return False
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
            tool_name in {"send_simulated_acknowledgement", "send_simulated_options"}
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
            if not message.evidence["slots"] and not message.evidence.get("constraint_mismatch"):
                request_handoff(db, run, "NO_AVAILABLE_SLOTS", risk="AMBER")
            else:
                run.checkpoint = {**run.checkpoint, "wait_reason": "AWAITING_PATIENT_REPLY"}
                release(run, "waiting")
        else:
            release(run, "queued", delay=settings.agent_step_delay_seconds)
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
