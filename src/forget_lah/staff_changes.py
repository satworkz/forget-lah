"""Staff initiated follow-up changes and durable grounded notifications."""

import logging
import secrets
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from forget_lah.auth import digest
from forget_lah.bridge_source import as_utc, episode_query, source_version
from forget_lah.channel_models import ChannelOutbox
from forget_lah.db import BridgeFollowupSlot, FollowupCase, Principal, uid, utcnow
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentEvent,
    AgentRun,
    AgentStep,
    SimulatedMessage,
    StaffAppointmentChange,
)
from forget_lah.runtime.responses import patient_message
from forget_lah.runtime.routes import idempotency_key, latest_run
from forget_lah.runtime.scheduling import (
    compatible,
    instruction_gate_clear,
    normalize_review,
    pending_patient_checks,
)
from forget_lah.runtime.startup import SIMULATOR_GOAL


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_case_version: int = Field(ge=1)


class ChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_case_version: int = Field(ge=1)
    expected_version: int = Field(ge=1)
    expected_source_version: str = Field(min_length=1, max_length=40)
    slot_id: UUID
    slot_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=600)


def binding_for(case):
    return {k: getattr(case, k) for k in ("clinic_id", "patient_id", "source_episode_ref")}


def snapshot(db, case, tools):
    binding = binding_for(case)
    results = [
        tools.execute(name, binding)
        for name in ("read_followup_context", "get_approved_instructions", "check_prerequisites")
    ]
    if any(r.status != "succeeded" for r in results):
        raise HTTPException(503, "Appointment source unavailable")
    context, notes, prereq = results
    if len({r.source_version for r in results}) != 1:
        raise HTTPException(409, "Source changed; refresh")
    blocked = None
    if not case.source_episode_ref.startswith("bridge:") and not tools.followup_key:
        blocked = "The clinic source has not authorized appointment changes."
    run = latest_run(db, case.id)
    if run and run.status not in {"waiting", "completed"}:
        blocked = (
            "Finish the active review or resolve the staff handoff before changing the appointment."
        )
    data = context.data
    if (
        data.get("source_status") != "scheduled"
        or not data.get("scheduled_at")
        or as_utc(datetime.fromisoformat(data["scheduled_at"])) <= utcnow()
    ):
        blocked = "Only a current future appointment can be changed here."
    if prereq.data.get("prerequisites") != ["NOT_APPLICABLE"]:
        blocked = "Clinic prerequisites require review."
    instructions = notes.data.get("instructions", [])
    review = [] if not instructions else None
    resolutions = []
    if instructions and run:
        for pointer in ("staff_scheduling_review_step_id", "question_review_step_id"):
            step = db.get(AgentStep, run.checkpoint.get(pointer, ""))
            if (
                step
                and step.run_id == run.id
                and step.clinic_id == case.clinic_id
                and step.role == "preparation"
                and step.status == "completed"
                and (step.policy or {}).get("decision") == "ALLOW"
            ):
                candidate = (step.decision or {}).get("scheduling_review")
                quotes = {(n["instruction_id"], n["approved_text"]) for n in instructions}
                evidence = [
                    db.get(AgentStep, i) for i in (step.decision or {}).get("evidence_ids", [])
                ]
                if (
                    candidate is not None
                    and {(r["instruction_id"], r["quote"]) for r in candidate} == quotes
                    and any(
                        e
                        and e.run_id == run.id
                        and (e.tool_result or {}).get("tool_name") == "get_approved_instructions"
                        and e.tool_result.get("source_version") == notes.source_version
                        for e in evidence
                    )
                ):
                    review = candidate
                    resolutions = run.checkpoint.get("instruction_check_resolutions", [])
                    break
    review_active = bool(run and run.checkpoint.get("staff_review_restore"))
    review_status = (
        "running"
        if review_active and run.status in {"queued", "running"}
        else "failed"
        if review_active
        else "required"
        if review is None
        else "ready"
    )
    can_review = not blocked and review is None
    review = normalize_review(review)
    checks = pending_patient_checks(review, resolutions)
    if not blocked and not instruction_gate_clear(review, resolutions):
        if review is None:
            blocked = "Review the current doctor instructions before choosing a new time."
        elif any(r["effect"] == "CLINIC_REVIEW" for r in review):
            blocked = "The doctor instructions require clinic review. Resolve this with the clinic and update the approved source instructions before reviewing again."
        elif checks:
            blocked = "Patient checks are still required. Complete these through the existing patient follow-up conversation before changing the appointment."
    if review_active:
        blocked = (
            "Reviewing doctor instructions. Your appointment is unchanged."
            if review_status == "running"
            else "The instruction review could not finish. Retry the review or cancel to return to the follow-up."
        )
    slots = compatible(data.get("available_slots", []), review)
    slots = (
        [
            s
            for s in slots
            if as_utc(datetime.fromisoformat(s["starts_at"])) > utcnow()
            and as_utc(datetime.fromisoformat(s["starts_at"]))
            != as_utc(datetime.fromisoformat(data["scheduled_at"]))
        ]
        if data.get("scheduled_at")
        else []
    )
    return {
        "review_status": review_status,
        "can_review": can_review,
        "review_requirements": review or [],
        "patient_checks": checks,
        "case_version": case.case_version,
        "episode_version": data.get("episode_version"),
        "source_version": context.source_version,
        "scheduled_at": data.get("scheduled_at"),
        "slots": slots if not blocked else [],
        "blocked": blocked,
        "more_available_slots": data.get("more_available_slots", False),
    }


def commit_bridge(db, case, change):
    body = change.request["source_operation"]
    episode = db.scalar(episode_query(binding_for(case)).with_for_update())
    slot = (
        db.scalar(
            select(BridgeFollowupSlot)
            .where(
                BridgeFollowupSlot.id == body["slot_id"],
                BridgeFollowupSlot.clinic_id == case.clinic_id,
                BridgeFollowupSlot.episode_id == episode.id,
            )
            .with_for_update()
        )
        if episode
        else None
    )
    if (
        not episode
        or episode.version != body["expected_version"]
        or source_version(episode) != body["expected_source_version"]
        or not slot
        or slot.version != body["slot_version"]
        or slot.status != "available"
        or as_utc(slot.starts_at) <= utcnow()
    ):
        raise HTTPException(409, "Appointment or slot changed; refresh")
    old = episode.normalized.get("appointment_at")
    for previous in db.scalars(
        select(BridgeFollowupSlot)
        .where(BridgeFollowupSlot.episode_id == episode.id, BridgeFollowupSlot.status == "booked")
        .with_for_update()
    ):
        previous.status = "withdrawn"
        previous.version += 1
    slot.status = "booked"
    slot.version += 1
    episode.normalized = {
        **episode.normalized,
        "appointment_at": as_utc(slot.starts_at).isoformat(),
        "booking_slot_id": slot.id,
    }
    episode.version += 1
    episode.followup_status = "awaiting_reply"
    episode.updated_at = utcnow()
    return {
        "operation_id": change.id,
        "patient_id": case.patient_id,
        "source_episode_ref": case.source_episode_ref,
        "actor_id": change.actor_id,
        "old_scheduled_at": old,
        "scheduled_at": as_utc(slot.starts_at).isoformat(),
        "slot_id": slot.id,
        "episode_version": episode.version,
        "changed_at": utcnow().isoformat(),
        "status": "STAFF_CHANGED_AWAITING_PATIENT",
        "source_version": source_version(episode),
        "record_owner": "forget_lah",
    }


def notification(db, change):
    message = db.scalar(
        select(SimulatedMessage).where(
            SimulatedMessage.event_id == change.id,
            SimulatedMessage.kind == "staff_appointment_change",
        )
    )
    outbox = (
        db.scalar(select(ChannelOutbox).where(ChannelOutbox.message_id == message.id))
        if message
        else None
    )
    delivery_status = outbox.status if outbox else "simulated" if message else "pending"
    if message and message.translation and message.translation.get("status") != "ready":
        delivery_status = "failed" if message.translation.get("status") == "failed" else "pending"
    if change.status in {"rejected", "superseded"}:
        delivery_status = "not_required"
    return {
        "id": change.id,
        "status": change.status,
        "receipt": change.receipt,
        "reason": change.request["input"]["reason"],
        "actor_id": change.actor_id,
        "actor_name": db.get(Principal, change.actor_id).email,
        "created_at": as_utc(change.created_at).isoformat(),
        "notification_status": delivery_status,
    }


def ensure_notification(factory, change_id):
    with factory.begin() as db:
        change = db.scalar(
            select(StaffAppointmentChange)
            .where(StaffAppointmentChange.id == change_id)
            .with_for_update()
        )
        if not change or change.status != "committed":
            return
        if db.scalar(
            select(SimulatedMessage.id).where(
                SimulatedMessage.event_id == change.id,
                SimulatedMessage.kind == "staff_appointment_change",
            )
        ):
            return
        run = db.get(AgentRun, change.run_id)
        receipt = change.receipt
        local = datetime.fromisoformat(receipt["scheduled_at"]).astimezone(
            ZoneInfo("Asia/Singapore")
        )
        body = f"Your appointment has been changed by the clinic to {local.strftime('%d %B %Y at %I:%M %p SGT')}. Please confirm if this works for you."
        db.add(
            patient_message(
                run,
                clinic_id=change.clinic_id,
                case_id=change.case_id,
                run_id=change.run_id,
                event_id=change.id,
                kind="staff_appointment_change",
                body=body,
                source_version=receipt["source_version"],
                evidence={"staff_change_receipt": receipt},
            )
        )


def install_staff_change_routes(app, factory, settings, authorise):
    tools = ClinicTools(
        settings.mock_clinic_url,
        factory=factory,
        followup_key=settings.mock_clinic_followup_key.get_secret_value()
        if settings.mock_clinic_followup_key
        else None,
    )
    app.state.staff_change_tools = tools

    def access(db, request, case_id, lock=False, *, lock_run=False):
        user, session, clinics = authorise(db, request)
        if request.method == "POST" and not secrets.compare_digest(
            digest(request.headers.get("X-CSRF-Token", "")), session.csrf_hash
        ):
            raise HTTPException(403, "Invalid CSRF token")
        if lock_run:
            # Worker takes run then case locks. Use the same order for cancellation
            # and retry so an in-flight model result cannot overwrite restoration.
            db.scalar(
                select(AgentRun)
                .where(AgentRun.case_id == case_id, AgentRun.clinic_id.in_(clinics))
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(1)
                .with_for_update()
            )
        query = select(FollowupCase).where(
            FollowupCase.id == case_id, FollowupCase.clinic_id.in_(clinics)
        )
        case = db.scalar(query.with_for_update() if lock else query)
        if not case:
            raise HTTPException(404, "Case not found")
        return user, case

    def finish(change_id):
        with factory.begin() as db:
            change = db.scalar(
                select(StaffAppointmentChange)
                .where(StaffAppointmentChange.id == change_id)
                .with_for_update()
            )
            if change.status == "pending":
                case = db.get(FollowupCase, change.case_id)
                try:
                    receipt = app.state.staff_change_tools.staff_change(
                        binding_for(case), change.request["source_operation"]
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in {403, 404, 409, 422}:
                        change.status = "rejected"
                        attempt_run = db.get(AgentRun, change.run_id)
                        prior = change.request.get("prior_run")
                        if prior:
                            original = db.get(AgentRun, prior["id"])
                            original.status, original.checkpoint = (
                                prior["status"],
                                prior["checkpoint"],
                            )
                            change.run_id = original.id
                            db.flush()
                            db.delete(attempt_run)
                        else:
                            attempt_run.status = "completed"
                    return
                except (httpx.HTTPError, ValueError):
                    return  # Unknown source outcome: recover with the identical operation ID.
                if as_utc(datetime.fromisoformat(receipt["scheduled_at"])) != as_utc(
                    datetime.fromisoformat(change.request["new_slot"]["starts_at"])
                ) or as_utc(datetime.fromisoformat(receipt["old_scheduled_at"])) != as_utc(
                    datetime.fromisoformat(change.request["old_scheduled_at"])
                ):
                    return
                current = app.state.staff_change_tools.execute(
                    "read_followup_context", binding_for(case)
                )
                if current.status != "succeeded":
                    return
                change.receipt = receipt
                superseded = (
                    current.data.get("episode_version") != receipt["episode_version"]
                    or current.data.get("scheduled_at") != receipt["scheduled_at"]
                )
                change.status = "superseded" if superseded else "committed"
                run = db.get(AgentRun, change.run_id)
                run.status = "completed" if superseded else "waiting"
                run.available_at = None
        try:
            ensure_notification(factory, change_id)
        except Exception as exc:
            # Source receipt remains committed; retry only the grounded notification.
            logging.getLogger(__name__).warning(
                "staff_change_notification_pending error_type=%s", type(exc).__name__
            )
            return

    @app.get("/api/cases/{case_id}/doctor-notes")
    def doctor_notes(case_id: str, request: Request):
        with factory() as db:
            _, case = access(db, request, case_id)
            result = app.state.staff_change_tools.execute(
                "get_approved_instructions", binding_for(case)
            )
            if result.status != "succeeded":
                raise HTTPException(503, "Doctor notes could not be loaded from the clinic source")
            return {
                "instructions": result.data.get("instructions", []),
                "source": "Imported clinic record"
                if case.source_episode_ref.startswith("bridge:")
                else "Clinic source",
            }

    @app.get("/api/cases/{case_id}/appointment-change")
    def view(case_id: str, request: Request):
        with factory() as db:
            _, case = access(db, request, case_id)
            changes = list(
                db.scalars(
                    select(StaffAppointmentChange)
                    .where(StaffAppointmentChange.case_id == case.id)
                    .order_by(StaffAppointmentChange.created_at.desc())
                )
            )
            try:
                result = snapshot(db, case, app.state.staff_change_tools)
            except HTTPException as exc:
                result = {
                    "case_version": case.case_version,
                    "episode_version": None,
                    "source_version": None,
                    "scheduled_at": None,
                    "slots": [],
                    "blocked": exc.detail,
                    "more_available_slots": False,
                    "review_status": "failed"
                    if (
                        latest_run(db, case.id)
                        and latest_run(db, case.id).checkpoint.get("staff_review_restore")
                    )
                    else "unavailable",
                    "can_review": False,
                    "review_requirements": [],
                    "patient_checks": [],
                }
            result["changes"] = [notification(db, c) for c in changes]
            return result

    @app.post("/api/cases/{case_id}/appointment-change/review")
    def review_instructions(case_id: str, body: ReviewInput, request: Request):
        from forget_lah.runtime.engine import abort_delegation
        from forget_lah.staff_review import KEY, restore_review

        key = idempotency_key(request)
        with factory.begin() as db:
            user, case = access(db, request, case_id, True, lock_run=True)
            run = latest_run(db, case.id)
            prior = (
                db.scalar(
                    select(AgentEvent).where(
                        AgentEvent.run_id == run.id, AgentEvent.client_key == key
                    )
                )
                if run
                else None
            )
            if prior:
                if (
                    prior.kind != "staff_scheduling_review"
                    or prior.actor_id != user.id
                    or prior.expected_case_version != body.expected_case_version
                ):
                    raise HTTPException(409, "Review key already used")
                return {"status": "accepted"}
            if case.case_version != body.expected_case_version:
                raise HTTPException(409, "Follow-up changed; refresh before reviewing")
            if run and run.checkpoint.get(KEY):
                if run.status in {"queued", "running"}:
                    return {"status": "accepted"}
                abort_delegation(db, run)
                for step in db.scalars(
                    select(AgentStep).where(
                        AgentStep.run_id == run.id,
                        AgentStep.status.in_(["pending", "tool_pending"]),
                    )
                ):
                    step.status, step.error_code = "rejected", "STAFF_REVIEW_RETRIED"
                restore_review(run)
            state = snapshot(db, case, app.state.staff_change_tools)
            if not state["can_review"]:
                raise HTTPException(
                    409, state["blocked"] or "Current instructions already reviewed"
                )
            if db.scalar(
                select(StaffAppointmentChange.id).where(
                    StaffAppointmentChange.case_id == case.id,
                    StaffAppointmentChange.status == "pending",
                )
            ):
                raise HTTPException(409, "Recover the pending appointment change first")
            if not run:
                run = AgentRun(
                    id=uid(),
                    clinic_id=case.clinic_id,
                    case_id=case.id,
                    start_key="staff-review-" + uid(),
                    start_case_version=case.case_version,
                    started_by=user.id,
                    authorised_by=user.id,
                    mode=settings.agent_model_mode,
                    status="completed",
                    goal=SIMULATOR_GOAL,
                    checkpoint={},
                )
                db.add(run)
                db.flush()
            saved = {
                "checkpoint": run.checkpoint,
                "status": run.status,
                "active_role": run.active_role,
                "authorised_by": run.authorised_by,
                "available_at": run.available_at.isoformat() if run.available_at else None,
            }
            delegations = list(
                db.scalars(
                    select(AgentDelegation).where(
                        AgentDelegation.run_id == run.id, AgentDelegation.status == "active"
                    )
                )
            )
            saved["delegation_ids"] = [d.id for d in delegations]
            for delegation in delegations:
                delegation.status = "aborted"
            event_id = uid()
            db.add(
                AgentEvent(
                    case_id=case.id,
                    id=event_id,
                    clinic_id=case.clinic_id,
                    run_id=run.id,
                    client_key=key,
                    actor_id=user.id,
                    expected_case_version=case.case_version,
                    kind="staff_scheduling_review",
                    content="",
                )
            )
            run.checkpoint = {
                KEY: saved,
                "latest_event": {"id": event_id, "kind": "staff_scheduling_review", "content": ""},
                "patient_simulator_enabled": False,
                "returned_specialists": [],
                "turn_start_step": run.step_count,
                "delegation_start": 0,
            }
            run.active_role, run.status, run.authorised_by = "coordinator", "queued", user.id
            run.available_at = utcnow()
            run.lease_token = run.lease_until = None
            case.case_version += 1
            return {"status": "accepted"}

    @app.post("/api/cases/{case_id}/appointment-change/review/cancel")
    def cancel_review(case_id: str, body: ReviewInput, request: Request):
        from forget_lah.runtime.engine import abort_delegation
        from forget_lah.staff_review import KEY, restore_review

        with factory.begin() as db:
            user, case = access(db, request, case_id, True, lock_run=True)
            run = latest_run(db, case.id)
            if case.case_version != body.expected_case_version:
                raise HTTPException(409, "Follow-up changed; refresh before cancelling")
            if not run or not run.checkpoint.get(KEY):
                raise HTTPException(409, "No instruction review is in progress")
            db.add(
                AgentEvent(
                    case_id=case.id,
                    id=uid(),
                    clinic_id=case.clinic_id,
                    run_id=run.id,
                    client_key=idempotency_key(request),
                    actor_id=user.id,
                    expected_case_version=case.case_version,
                    kind="staff_review_cancelled",
                    content="",
                )
            )
            abort_delegation(db, run)
            for step in db.scalars(
                select(AgentStep).where(
                    AgentStep.run_id == run.id, AgentStep.status.in_(["pending", "tool_pending"])
                )
            ):
                step.status, step.error_code = "rejected", "STAFF_REVIEW_CANCELLED"
            restore_review(run)
            case.case_version += 1
            return {"status": "cancelled"}

    @app.post("/api/cases/{case_id}/appointment-change")
    def change(case_id: str, body: ChangeInput, request: Request):
        key = idempotency_key(request)
        with factory.begin() as db:
            user, case = access(db, request, case_id, True)
            prior = db.scalar(
                select(StaffAppointmentChange).where(
                    StaffAppointmentChange.clinic_id == case.clinic_id,
                    StaffAppointmentChange.client_key == key,
                )
            )
            if prior:
                if (
                    prior.case_id != case.id
                    or prior.actor_id != user.id
                    or prior.request["input"] != body.model_dump(mode="json")
                ):
                    raise HTTPException(409, "Operation key already used")
                change_id = prior.id
            else:
                state = snapshot(db, case, app.state.staff_change_tools)
                slot = next(
                    (
                        s
                        for s in state["slots"]
                        if s["id"] == str(body.slot_id) and s["version"] == body.slot_version
                    ),
                    None,
                )
                if (
                    state["blocked"]
                    or state["case_version"] != body.expected_case_version
                    or state["episode_version"] != body.expected_version
                    or state["source_version"] != body.expected_source_version
                    or not slot
                ):
                    raise HTTPException(
                        409, state["blocked"] or "Appointment, constraints or slot changed; refresh"
                    )
                old = latest_run(db, case.id)
                prior_run = (
                    {"id": old.id, "status": old.status, "checkpoint": old.checkpoint}
                    if old
                    else None
                )
                change_id, run_id = uid(), uid()
                if old and old.status == "waiting":
                    old.status = "paused"
                    old.checkpoint = {
                        **old.checkpoint,
                        "pause_reason": "SUPERSEDED_BY_STAFF_CHANGE",
                        "superseded_by": change_id,
                    }
                run = AgentRun(
                    id=run_id,
                    clinic_id=case.clinic_id,
                    case_id=case.id,
                    start_key="staff-change-" + change_id,
                    start_case_version=case.case_version,
                    started_by=user.id,
                    authorised_by=user.id,
                    mode=settings.agent_model_mode,
                    status="paused",
                    goal=SIMULATOR_GOAL,
                    checkpoint={
                        "latest_event": {
                            "id": change_id,
                            "kind": "staff_appointment_change",
                            "content": "",
                        },
                        "patient_simulator_enabled": settings.conversation_configured_for(case),
                        "returned_specialists": [],
                        "staff_change_id": change_id,
                        "wait_reason": "AWAITING_PATIENT_REPLY",
                    },
                )
                db.add(run)
                db.flush()
                # AgentRun defaults available_at to now on INSERT. A staff-change
                # notice must wait for a real patient reply, never a timer tick.
                run.available_at = None
                operation = {
                    k: v
                    for k, v in body.model_dump(mode="json").items()
                    if k not in {"reason", "expected_case_version"}
                }
                operation.update(
                    operation_id=change_id,
                    clinic_id=case.clinic_id,
                    patient_id=case.patient_id,
                    actor_id=user.id,
                )
                saved = StaffAppointmentChange(
                    id=change_id,
                    clinic_id=case.clinic_id,
                    case_id=case.id,
                    run_id=run_id,
                    client_key=key,
                    actor_id=user.id,
                    request={
                        "input": body.model_dump(mode="json"),
                        "source_operation": operation,
                        "old_scheduled_at": state["scheduled_at"],
                        "new_slot": slot,
                        "prior_run": prior_run,
                    },
                    status="pending",
                )
                db.add(saved)
                case.case_version += 1
                if case.source_episode_ref.startswith("bridge:"):
                    saved.receipt = commit_bridge(db, case, saved)
                    saved.status = "committed"
                    run.status = "waiting"
        finish(change_id)
        with factory() as db:
            return notification(db, db.get(StaffAppointmentChange, change_id))

    @app.post("/api/cases/{case_id}/appointment-change/{change_id}/retry")
    def retry(case_id: str, change_id: str, request: Request):
        with factory.begin() as db:
            user, case = access(db, request, case_id, True)
            change = db.scalar(
                select(StaffAppointmentChange)
                .where(
                    StaffAppointmentChange.id == change_id,
                    StaffAppointmentChange.case_id == case.id,
                )
                .with_for_update()
            )
            if not change:
                raise HTTPException(404, "Change not found")
            from forget_lah.security import record_action

            record_action(
                db,
                clinic_id=case.clinic_id,
                actor_id=user.id,
                resource_id=case.id,
                action="notification_retry_requested",
                details={"change_id": change.id, "status": change.status},
            )
            if latest_run(db, case.id).id != change.run_id:
                raise HTTPException(
                    409, "A newer review exists; do not resend this old appointment"
                )
            if change.status == "committed":
                current = app.state.staff_change_tools.execute(
                    "read_followup_context", binding_for(case)
                )
                if (
                    current.status != "succeeded"
                    or current.data.get("episode_version") != change.receipt["episode_version"]
                    or current.data.get("scheduled_at") != change.receipt["scheduled_at"]
                ):
                    raise HTTPException(
                        409, "Appointment changed or source unavailable; do not resend old details"
                    )
            message = db.scalar(
                select(SimulatedMessage).where(SimulatedMessage.event_id == change.id)
            )
            outbox = (
                db.scalar(
                    select(ChannelOutbox)
                    .where(ChannelOutbox.message_id == message.id)
                    .with_for_update()
                )
                if message
                else None
            )
            if message and message.translation and message.translation.get("status") == "failed":
                message.translation = {
                    "language": message.translation["language"],
                    "status": "pending",
                }
            if outbox and outbox.status in {"failed", "undelivered"}:
                outbox.status, outbox.error_code, outbox.provider_sid = "queued", None, None
        finish(change_id)
        with factory() as db:
            return notification(db, db.get(StaffAppointmentChange, change_id))


def recover_unanswered_staff_timer(db, change_id, tools):
    """Explicit operator repair for the pre-fix timer defect; no source write or send.

    Preserve the erroneous run/handoff, move only the existing notice and operation
    to a new waiting conversation, and record the repair under the service identity.
    Refuse any patient activity, changed source, accepted handoff or different trace.
    Caller must stop workers and hold a transaction; this is not an automatic retry.
    """
    from forget_lah.channel_models import ChannelInbox
    from forget_lah.runtime.models import StaffHandoff
    from forget_lah.service_identity import AUTOMATION_PRINCIPAL_ID

    change = db.get(StaffAppointmentChange, change_id)
    if not change or change.status != "committed":
        raise ValueError("A committed staff change is required")
    run = db.get(AgentRun, change.run_id)
    case = db.get(FollowupCase, change.case_id)
    handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
    steps = list(
        db.scalars(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.sequence))
    )
    messages = list(db.scalars(select(SimulatedMessage).where(SimulatedMessage.run_id == run.id)))
    if not (
        latest_run(db, case.id).id == run.id
        and run.status == "escalated"
        and run.checkpoint.get("staff_change_id") == change.id
        and run.checkpoint.get("latest_event", {}).get("kind") == "staff_appointment_change"
        and run.checkpoint["latest_event"].get("wake_reason") == "timer"
        and handoff
        and handoff.reason_code == "CAPABILITY_UNAVAILABLE"
        and handoff.risk == "AMBER"
        and not handoff.accepted_by
        and len(steps) == 2
        and steps[0].role == steps[1].role == "coordinator"
        and (steps[0].decision or {}).get("tool_name") == "read_followup_context"
        and (steps[0].tool_result or {}).get("status") == "succeeded"
        and (steps[1].decision or {}).get("step_type") == "ESCALATE"
        and (steps[1].decision or {}).get("reason_code") == "CAPABILITY_UNAVAILABLE"
        and len(messages) == 1
        and messages[0].event_id == change.id
        and messages[0].kind == "staff_appointment_change"
        and not db.scalar(select(AgentEvent.id).where(AgentEvent.run_id == run.id))
        and not db.scalar(
            select(ChannelInbox.sid).where(
                ChannelInbox.case_id == case.id, ChannelInbox.created_at >= change.created_at
            )
        )
    ):
        raise ValueError("Case does not match the untouched staff timer defect")
    context = tools.execute("read_followup_context", binding_for(case))
    if (
        context.status != "succeeded"
        or context.data.get("episode_version") != change.receipt["episode_version"]
        or context.data.get("scheduled_at") != change.receipt["scheduled_at"]
    ):
        raise ValueError("Source changed or is unavailable; repair refused")
    new_id, event_id = uid(), uid()
    new = AgentRun(
        id=new_id,
        clinic_id=case.clinic_id,
        case_id=case.id,
        start_key="timer-recovery-" + change.id,
        start_case_version=case.case_version,
        started_by=AUTOMATION_PRINCIPAL_ID,
        authorised_by=run.authorised_by,
        mode=run.mode,
        status="waiting",
        goal=run.goal,
        checkpoint={
            "latest_event": {"id": change.id, "kind": "staff_appointment_change", "content": ""},
            "staff_change_id": change.id,
            "patient_simulator_enabled": run.checkpoint.get("patient_simulator_enabled", False),
            "wait_reason": "AWAITING_PATIENT_REPLY",
            "returned_specialists": [],
            "recovered_from_run_id": run.id,
        },
    )
    db.add(new)
    db.flush()
    new.available_at = None
    run.status, run.available_at = "paused", None
    run.lease_token = run.lease_until = None
    run.checkpoint = {
        **run.checkpoint,
        "pause_reason": "STAFF_TIMER_ERROR_SUPERSEDED",
        "recovered_by_run_id": new_id,
    }
    change.run_id = new_id
    change.request = {
        **change.request,
        "timer_recovery": {"previous_run_id": run.id, "recovered_at": utcnow().isoformat()},
    }
    messages[0].run_id = new_id
    db.add(
        AgentEvent(
            id=event_id,
            clinic_id=case.clinic_id,
            case_id=case.id,
            run_id=new_id,
            client_key="timer-recovery-" + change.id,
            actor_id=AUTOMATION_PRINCIPAL_ID,
            expected_case_version=case.case_version,
            kind="staff_change_timer_repaired",
            content=f"Restored waiting after erroneous automatic timer escalation. Prior run {run.id} and handoff retained. Appointment and notification contents unchanged; no resend.",
        )
    )
    case.case_version += 1
    if case.source_episode_ref.startswith("bridge:"):
        episode = db.scalar(episode_query(binding_for(case)))
        episode.followup_status = "awaiting_reply"
    return new_id
