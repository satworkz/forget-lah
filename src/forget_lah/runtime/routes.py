import secrets
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from forget_lah.agents import StrictModel
from forget_lah.auth import digest
from forget_lah.db import FollowupCase, Principal, uid, utcnow
from forget_lah.runtime.engine import abort_delegation, as_utc, release
from forget_lah.runtime.journey import case_journey
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentEvent,
    AgentRun,
    AgentStep,
    SimulatedMessage,
    StaffHandoff,
)
from forget_lah.runtime.simulation import message_dict, simulation_enabled, simulation_evidence
from forget_lah.runtime.startup import REVIEW_GOAL, SIMULATOR_GOAL, automation_authorised
from forget_lah.source import DEMO_CLINIC_ID


class StartInput(StrictModel):
    expected_case_version: int = Field(ge=1)


class EventInput(StartInput):
    run_id: str = Field(min_length=36, max_length=36)
    kind: Literal[
        "demo_reply",
        "clinical_concern",
        "retry",
        "pause",
        "accept_handoff",
        "resolve_callback",
        "resolve_clinical",
    ]
    content: str = Field(default="", max_length=600)


class StartRunInput(StartInput):
    fresh_simulation: bool = False


def latest_run(db, case_id):
    return db.scalar(
        select(AgentRun)
        .where(AgentRun.case_id == case_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


def idempotency_key(request):
    key = request.headers.get("Idempotency-Key", "")
    if not 8 <= len(key) <= 64 or any(not (c.isalnum() or c in "-_") for c in key):
        raise HTTPException(400, "Provide an Idempotency-Key of 8-64 letters, digits, '-' or '_'")
    return key


def install_routes(app, factory, settings, authorise):
    def identity(db, request):
        user, session, clinics = authorise(db, request)
        if request.method == "POST" and not secrets.compare_digest(
            digest(request.headers.get("X-CSRF-Token", "")), session.csrf_hash
        ):
            raise HTTPException(403, "Invalid CSRF token")
        return user, clinics

    def scoped_case(db, case_id, clinics, *, lock=False):
        query = select(FollowupCase).where(
            FollowupCase.id == case_id, FollowupCase.clinic_id.in_(clinics)
        )
        case = db.scalar(query.with_for_update() if lock else query)
        if case is None:
            raise HTTPException(404, "Case not found")
        return case

    @app.get("/api/cases/{case_id}/agent")
    def agent_view(case_id: str, request: Request):
        with factory() as db:
            _, clinics = identity(db, request)
            case = scoped_case(db, case_id, clinics)
            run = latest_run(db, case.id)
            result = {
                "case_version": case.case_version,
                "auto_start": {
                    "enabled": settings.agent_auto_start_enabled,
                    "authorised": automation_authorised(db, case.clinic_id),
                },
                "run": None,
                "steps": [],
                "delegations": [],
                "events": [],
                "handoff": None,
                "patient_simulator": {
                    "available": settings.simulation_configured
                    and case.clinic_id == DEMO_CLINIC_ID,
                    "enabled": False,
                    "messages": [],
                },
            }
            if not run:
                return result
            result["run"] = {
                "id": run.id,
                "status": run.status,
                "mode": run.mode,
                "active_role": run.active_role,
                "goal": run.goal,
                "step_count": run.step_count,
                "step_limit": settings.agent_max_steps,
                "wait_reason": run.checkpoint.get("wait_reason"),
                "pause_reason": run.checkpoint.get("pause_reason"),
                "outcome": run.checkpoint.get("outcome"),
                "available_at": as_utc(run.available_at).isoformat() if run.available_at else None,
            }
            steps = db.scalars(
                select(AgentStep)
                .where(AgentStep.run_id == run.id)
                .order_by(AgentStep.sequence)
                .limit(50)
            )
            result["steps"] = [
                {
                    "id": step.id,
                    "sequence": step.sequence,
                    "role": step.role,
                    "origin": step.origin,
                    "status": step.status,
                    "attempts": step.attempts,
                    "goal": step.observation.get("goal", run.goal),
                    "event_kind": step.observation.get("latest_event", {}).get("kind"),
                    "decision": step.decision,
                    "policy": step.policy,
                    "tool_result": step.tool_result,
                    "error_code": step.error_code,
                    "input_tokens": step.input_tokens,
                    "output_tokens": step.output_tokens,
                    "latency_ms": step.latency_ms,
                }
                for step in steps
            ]
            result["delegations"] = [
                {
                    "id": d.id,
                    "target": d.target,
                    "goal": d.goal,
                    "status": d.status,
                    "evidence_ids": d.evidence_ids,
                    "result_reason_code": d.result_reason_code,
                }
                for d in db.scalars(
                    select(AgentDelegation)
                    .where(AgentDelegation.run_id == run.id)
                    .order_by(AgentDelegation.start_sequence)
                )
            ]
            result["events"] = [
                {
                    "id": e.id,
                    "kind": e.kind,
                    "content": e.content,
                    "created_at": as_utc(e.created_at).isoformat(),
                }
                for e in db.scalars(
                    select(AgentEvent)
                    .where(AgentEvent.run_id == run.id)
                    .order_by(AgentEvent.created_at, AgentEvent.id)
                )
            ]
            handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
            if handoff:
                owner = db.get(Principal, handoff.accepted_by) if handoff.accepted_by else None
                result["handoff"] = {
                    "id": handoff.id,
                    "reason_code": handoff.reason_code,
                    "risk": handoff.risk,
                    "accepted": bool(handoff.accepted_by),
                    "owner": owner.email if owner else None,
                    "staff_task_status": "resolved"
                    if any(
                        run.checkpoint.get(k, {}).get("status") == "resolved"
                        for k in ("callback", "clinical_review")
                    )
                    else "open",
                    "callback": run.checkpoint.get("callback"),
                    "clinical_review": run.checkpoint.get("clinical_review"),
                }
            result["patient_simulator"] = {
                "available": settings.simulation_configured and case.clinic_id == DEMO_CLINIC_ID,
                "enabled": bool(run and simulation_enabled(run)),
                "messages": [
                    message_dict(m)
                    for m in db.scalars(
                        select(SimulatedMessage)
                        .where(SimulatedMessage.run_id == run.id)
                        .order_by(SimulatedMessage.created_at)
                    )
                ]
                if run
                else [],
            }
            return result

    @app.get("/api/cases/{case_id}/journey")
    def journey_view(case_id: str, request: Request, run_id: str | None = None):
        with factory() as db:
            _, clinics = identity(db, request)
            case = scoped_case(db, case_id, clinics)
            return case_journey(db, case, run_id)

    @app.post("/api/cases/{case_id}/agent/runs", status_code=202)
    def start_run(case_id: str, body: StartRunInput, request: Request):
        key = idempotency_key(request)
        with factory.begin() as db:
            user, clinics = identity(db, request)
            case = scoped_case(db, case_id, clinics, lock=True)
            prior = db.scalar(
                select(AgentRun).where(
                    AgentRun.clinic_id == case.clinic_id, AgentRun.start_key == key
                )
            )
            if prior:
                if (
                    prior.case_id != case.id
                    or prior.started_by != user.id
                    or prior.start_case_version != body.expected_case_version
                ):
                    raise HTTPException(409, "Idempotency key belongs to another request")
                return {"run_id": prior.id, "status": prior.status}
            if case.case_version != body.expected_case_version:
                raise HTTPException(409, "Case changed; refresh before starting")
            active = latest_run(db, case.id)
            if active and active.status != "completed":
                if not (
                    body.fresh_simulation
                    and settings.simulation_configured
                    and case.clinic_id == DEMO_CLINIC_ID
                    and active.status in {"escalated", "paused", "waiting"}
                    and active.available_at is None
                ):
                    raise HTTPException(409, "This case already has an agent run; use its controls")
                if active.status == "waiting":
                    abort_delegation(db, active)
                    active.checkpoint = {
                        **active.checkpoint,
                        "pause_reason": "REPLACED_BY_FRESH_SIMULATION",
                    }
                    release(active, "paused")
            if not settings.model_configured:
                raise HTTPException(
                    503, "Model mode needs private configuration; see CLAUDE_SETUP.md"
                )
            run_id = uid()
            run = AgentRun(
                id=run_id,
                clinic_id=case.clinic_id,
                case_id=case.id,
                start_key=key,
                start_case_version=body.expected_case_version,
                started_by=user.id,
                authorised_by=user.id,
                mode=settings.agent_model_mode,
                goal=SIMULATOR_GOAL if settings.simulation_configured else REVIEW_GOAL,
                checkpoint={
                    "latest_event": {"id": run_id, "kind": "started", "content": ""},
                    "returned_specialists": [],
                    "patient_simulator_enabled": settings.simulation_configured
                    and case.clinic_id == DEMO_CLINIC_ID,
                },
            )
            db.add(run)
            case.case_version += 1
            db.flush()
            return {"run_id": run.id, "status": run.status}

    @app.post("/api/cases/{case_id}/agent/events", status_code=202)
    def add_event(case_id: str, body: EventInput, request: Request):
        key = idempotency_key(request)
        with factory.begin() as db:
            user, clinics = identity(db, request)
            run = db.scalar(
                select(AgentRun)
                .where(
                    AgentRun.id == body.run_id,
                    AgentRun.case_id == case_id,
                    AgentRun.clinic_id.in_(clinics),
                )
                .with_for_update()
            )
            if run is None:
                raise HTTPException(404, "Agent run not found")
            case = scoped_case(db, case_id, clinics, lock=True)
            prior = db.scalar(
                select(AgentEvent).where(AgentEvent.run_id == run.id, AgentEvent.client_key == key)
            )
            if prior:
                if (
                    prior.kind != body.kind
                    or prior.content != body.content
                    or prior.actor_id != user.id
                    or prior.expected_case_version != body.expected_case_version
                ):
                    raise HTTPException(
                        409, "Idempotency key was already used with different content"
                    )
                return {"event_id": prior.id, "status": run.status}
            if case.case_version != body.expected_case_version:
                raise HTTPException(409, "Case changed; refresh and review the latest state")
            newest = latest_run(db, case.id)
            if newest.id != run.id:
                raise HTTPException(409, "This is not the current agent run")
            if body.kind in {"resolve_callback", "resolve_clinical"}:
                handoff = db.scalar(
                    select(StaffHandoff).where(StaffHandoff.run_id == run.id).with_for_update()
                )
                callback = run.checkpoint.get(
                    "clinical_review" if body.kind == "resolve_clinical" else "callback", {}
                )
                if (
                    run.status != "escalated"
                    or callback.get("status") != "accepted"
                    or not handoff
                    or handoff.accepted_by != user.id
                ):
                    raise HTTPException(
                        409, "Only the assigned owner can resolve an accepted review"
                    )
                if not body.content.strip():
                    raise HTTPException(422, "Record the outcome of your patient contact")
            elif body.kind == "accept_handoff":
                handoff = db.scalar(
                    select(StaffHandoff).where(StaffHandoff.run_id == run.id).with_for_update()
                )
                if run.status != "escalated" or not handoff or handoff.accepted_by:
                    raise HTTPException(409, "No unclaimed handoff is available")
                handoff.accepted_by, handoff.accepted_at = user.id, utcnow()
            elif body.kind == "pause":
                if run.status not in {"queued", "running", "waiting"}:
                    raise HTTPException(409, "This run cannot be paused in its current state")
            elif body.kind == "retry":
                if run.status != "paused":
                    raise HTTPException(409, "Only a paused run can be retried")
            elif run.status != "waiting":
                raise HTTPException(409, "Wait until the agent requests a demo reply")
            if body.kind == "demo_reply" and not body.content.strip():
                raise HTTPException(422, "Enter a fictional reply")
            event_id = uid()
            db.add(
                AgentEvent(
                    id=event_id,
                    clinic_id=run.clinic_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    client_key=key,
                    actor_id=user.id,
                    kind=body.kind,
                    content=body.content,
                    expected_case_version=body.expected_case_version,
                )
            )
            if body.kind in {"accept_handoff", "resolve_clinical"} and run.checkpoint.get(
                "clinical_review"
            ):
                review = {**run.checkpoint["clinical_review"]}
                resolved = body.kind == "resolve_clinical"
                review.update(status="resolved" if resolved else "accepted")
                review["resolved_event_id" if resolved else "accepted_event_id"] = event_id
                review["resolved_at" if resolved else "accepted_at"] = utcnow().isoformat()
                review["resolved_by" if resolved else "accepted_by"] = user.id
                if resolved:
                    review["resolution"] = body.content.strip()
                run.checkpoint = {
                    **run.checkpoint,
                    "clinical_review": review,
                    "outcome": "CLINICAL_REVIEW_RESOLVED_BY_STAFF" if resolved else None,
                }
                run.authorised_by = user.id
                case.case_version += 1
                release(run, "completed" if resolved else "escalated")
                return {"event_id": event_id, "status": run.status}
            if body.kind in {"accept_handoff", "resolve_callback"} and run.checkpoint.get(
                "callback"
            ):
                callback = {**run.checkpoint["callback"]}
                callback.update(
                    status="resolved" if body.kind == "resolve_callback" else "accepted"
                )
                callback[
                    "resolved_event_id" if body.kind == "resolve_callback" else "accepted_event_id"
                ] = event_id
                if body.kind == "resolve_callback":
                    callback.update(
                        resolution=body.content.strip(),
                        resolved_by=user.id,
                        resolved_at=utcnow().isoformat(),
                    )
                run.checkpoint = {
                    **run.checkpoint,
                    "callback": callback,
                    "outcome": "SIMULATED_CONFIRMATION_AND_CALLBACK_RESOLVED"
                    if body.kind == "resolve_callback"
                    else None,
                }
                run.authorised_by = user.id
                case.case_version += 1
                release(run, "completed" if body.kind == "resolve_callback" else "escalated")
                return {"event_id": event_id, "status": run.status}
            # Revoke in-flight work before exposing the new event. Late results
            # cannot reuse the old case version or lease token.
            proof = simulation_evidence(db, run)
            if (
                body.kind == "retry"
                and run.checkpoint.get("pause_reason")
                in {"ROLE_BUDGET_EXHAUSTED", "MODEL_REQUEST_TOO_LARGE"}
                and run.active_role == "coordinator"
                and settings.simulation_configured
                and (proof["ack_ready"] or proof["complete_evidence_ids"])
            ):
                # Explicit recovery of a legacy read loop. Keep the original reply,
                # specialist evidence and receipt; the whole-run budget is unchanged.
                run.authorised_by = user.id
                run.checkpoint = {
                    **run.checkpoint,
                    "pause_reason": None,
                    "coordinator_resume_after": run.step_count,
                    "completion_recovery_event_id": event_id,
                }
                case.case_version += 1
                release(run, "queued", delay=0)
                return {"event_id": event_id, "status": run.status}
            for pending in db.scalars(
                select(AgentStep).where(
                    AgentStep.run_id == run.id, AgentStep.status.in_(["pending", "tool_pending"])
                )
            ):
                pending.status, pending.error_code = "rejected", "SUPERSEDED_BY_STAFF_EVENT"
            abort_delegation(db, run)
            run.authorised_by, run.active_role = user.id, "coordinator"
            next_event = {"id": event_id, "kind": body.kind, "content": body.content}
            if body.kind == "demo_reply":
                next_event["reply_event_id"] = event_id
            if body.kind in {"pause", "retry"}:
                next_event = {
                    **run.checkpoint["latest_event"],
                    "id": event_id,
                    "wake_reason": body.kind,
                    "reply_event_id": run.checkpoint["latest_event"].get(
                        "reply_event_id", run.checkpoint["latest_event"]["id"]
                    ),
                }
            run.checkpoint = {
                "latest_event": next_event,
                "returned_specialists": [],
                "delegation_start": 0,
                "patient_simulator_enabled": simulation_enabled(run),
            }
            case.case_version += 1
            if body.kind == "pause":
                run.checkpoint = {**run.checkpoint, "pause_reason": "PAUSED_BY_STAFF"}
                release(run, "paused")
            else:
                release(run, "queued", delay=0)
            return {"event_id": event_id, "status": run.status}
