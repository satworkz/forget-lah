"""One persisted decision per worker tick. Network calls never hold DB locks."""

import json
from datetime import UTC, timedelta

from sqlalchemy import and_, or_, select

from forget_lah.db import FollowupCase, uid, utcnow
from forget_lah.runtime.budget import reserve_call
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.contracts import (
    REQUIRED_EVIDENCE_BY_ROLE,
    TOOLS_BY_ROLE,
    CompleteDecision,
    DelegateDecision,
    EscalateDecision,
    ReturnDecision,
    ToolDecision,
    WaitDecision,
    parse_decision,
)
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentRun,
    AgentStep,
    StaffHandoff,
)
from forget_lah.runtime.policy import has_authority, policy_for
from forget_lah.runtime.provider import ModelError, model_for


def as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def release(run, status, *, delay=None):
    run.status = status
    run.lease_until = run.lease_token = None
    run.available_at = utcnow() + timedelta(seconds=delay) if delay is not None else None


def pause(run, code):
    run.checkpoint = {**run.checkpoint, "pause_reason": code}
    release(run, "paused")


def abort_delegation(db, run):
    for delegation in db.scalars(
        select(AgentDelegation).where(
            AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
        )
    ):
        delegation.status = "aborted"


def request_handoff(db, run, reason):
    existing = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
    if not existing:
        db.add(
            StaffHandoff(
                id=uid(),
                clinic_id=run.clinic_id,
                case_id=run.case_id,
                run_id=run.id,
                reason_code=reason,
                risk="RED" if reason == "CLINICAL_REVIEW_REQUIRED" else "AMBER",
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
            pause(run, "STAFF_AUTHORITY_REVOKED")
            return None
        if run.status == "waiting":
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
        "allowed_tools": list(TOOLS_BY_ROLE[run.active_role]),
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
                "policy_version": "m2a-read-only-v1",
                "action": "ESCALATE",
            },
        )
    )
    request_handoff(db, run, "CLINICAL_REVIEW_REQUIRED")
    case.case_version += 1


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
            pause(run, "STAFF_AUTHORITY_REVOKED")
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
                    s.observation.get("latest_event", {}).get("id")
                    == run.checkpoint["latest_event"]["id"]
                    if run.active_role == "coordinator"
                    else s.sequence > run.checkpoint.get("delegation_start", 0)
                )
            ]
            if len(active) >= (4 if run.active_role == "coordinator" else 6):
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
    if isinstance(decision, DelegateDecision):
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
        release(run, "waiting", delay=decision.wake_after_seconds or None)
    elif isinstance(decision, EscalateDecision):
        request_handoff(db, run, decision.reason_code)
    elif isinstance(decision, CompleteDecision):
        run.checkpoint = {**run.checkpoint, "outcome": "OWNED_STAFF_HANDOFF"}
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
    result = tools.execute(tool_name, binding)
    with factory.begin() as db:
        run = current_run(db, run_id, token)
        if not run:
            return False
        case = current_case(db, run)
        step = db.get(AgentStep, step_id)
        if case.case_version != version or not has_authority(db, run):
            step.status, step.error_code = "rejected", "STALE_OR_REVOKED_CONTEXT"
            pause(run, "STALE_OR_REVOKED_CONTEXT")
            return False
        step.tool_result, step.status = result.model_dump(), "completed"
        case.case_version += 1
        release(run, "queued", delay=settings.agent_min_interval_seconds)
        return True


def process_run(factory, settings, run_id, token, *, model=None, tools=None):
    work = prepare_step(factory, settings, run_id, token)
    if work is None:
        return False
    tools = tools or ClinicTools(settings.mock_clinic_url)
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
