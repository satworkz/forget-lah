import secrets
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from forget_lah.agents import StrictModel
from forget_lah.auth import digest
from forget_lah.db import FollowupCase, Principal, uid, utcnow
from forget_lah.runtime.engine import abort_delegation, as_utc, release
from forget_lah.runtime.models import AgentDelegation, AgentEvent, AgentRun, AgentStep, StaffHandoff


class StartInput(StrictModel):
    expected_case_version: int = Field(ge=1)


class EventInput(StartInput):
    run_id: str = Field(min_length=36, max_length=36)
    kind: Literal["demo_reply", "clinical_concern", "retry", "pause", "accept_handoff"]
    content: str = Field(default="", max_length=600)


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
                "run": None,
                "steps": [],
                "delegations": [],
                "events": [],
                "handoff": None,
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
                {"id": e.id, "kind": e.kind, "content": e.content}
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
                    "staff_task_status": "open",  # Acceptance never claims clinical resolution.
                }
            return result

    @app.post("/api/cases/{case_id}/agent/runs", status_code=202)
    def start_run(case_id: str, body: StartInput, request: Request):
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
                raise HTTPException(409, "This case already has an agent run; use its controls")
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
                goal="Review source evidence and the demo reply; pause or reach an owned staff handoff.",
                checkpoint={
                    "latest_event": {"id": run_id, "kind": "started", "content": ""},
                    "returned_specialists": [],
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
            if body.kind == "accept_handoff":
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
            # Revoke in-flight work before exposing the new event. Late results
            # cannot reuse the old case version or lease token.
            for pending in db.scalars(
                select(AgentStep).where(
                    AgentStep.run_id == run.id, AgentStep.status.in_(["pending", "tool_pending"])
                )
            ):
                pending.status, pending.error_code = "rejected", "SUPERSEDED_BY_STAFF_EVENT"
            abort_delegation(db, run)
            run.authorised_by, run.active_role = user.id, "coordinator"
            next_event = {"id": event_id, "kind": body.kind, "content": body.content}
            if body.kind in {"pause", "retry"}:
                next_event = {
                    **run.checkpoint["latest_event"],
                    "id": event_id,
                    "wake_reason": body.kind,
                }
            run.checkpoint = {
                "latest_event": next_event,
                "returned_specialists": [],
                "delegation_start": 0,
            }
            case.case_version += 1
            if body.kind == "pause":
                run.checkpoint = {**run.checkpoint, "pause_reason": "PAUSED_BY_STAFF"}
                release(run, "paused")
            else:
                release(run, "queued", delay=0)
            return {"event_id": event_id, "status": run.status}
