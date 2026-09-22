"""The Forget-lah-owned appointment source, scoped to imported follow-up episodes."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from forget_lah.db import BridgeEpisode, BridgeFollowupSlot, FollowupCase, utcnow
from forget_lah.runtime.contracts import ToolResult
from forget_lah.runtime.source_versions import compact_bridge_source_version


def source_version(episode):
    return compact_bridge_source_version(f"bridge:{episode.id}:{episode.version}")


def episode_query(binding):
    return select(BridgeEpisode).where(
        BridgeEpisode.clinic_id == binding["clinic_id"],
        BridgeEpisode.patient_id == binding["patient_id"],
        BridgeEpisode.source_episode_ref == binding["source_episode_ref"],
    )


def as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def slots_for(db, episode):
    return list(
        db.scalars(
            select(BridgeFollowupSlot)
            .where(
                BridgeFollowupSlot.clinic_id == episode.clinic_id,
                BridgeFollowupSlot.episode_id == episode.id,
                BridgeFollowupSlot.status == "available",
                BridgeFollowupSlot.starts_at > utcnow(),
            )
            .order_by(BridgeFollowupSlot.starts_at, BridgeFollowupSlot.id)
            .limit(11)
        )
    )


def slot_payload(slot):
    return {
        "id": slot.id,
        "version": slot.version,
        "starts_at": as_utc(slot.starts_at).isoformat(),
        "ends_at": as_utc(slot.ends_at).isoformat(),
        "doctor": slot.doctor,
    }


def bridge_tool_result(factory, binding: dict, tool_name: str) -> ToolResult:
    from forget_lah.runtime.clinic_tools import ClinicTools
    from forget_lah.runtime.simulation import future_scheduled

    with factory() as db:
        episode = db.scalar(episode_query(binding))
        if not episode:
            return ClinicTools.failure(tool_name, "SOURCE_NOT_FOUND", False)
        data = episode.normalized
        if tool_name == "read_followup_context":
            slots = slots_for(db, episode)
            context = {
                "source_status": data["source_status"],
                "scheduled_at": data.get("appointment_at"),
            }
            payload = {
                **context,
                "specialty": data.get("specialty") or "general",
                "due_at": data.get("due_at"),
                "can_contact_patient": False,
                "can_write_appointments": False,
                "episode_version": episode.version,
                "can_simulate_confirmation": True,
                "can_simulate_booking": data["source_status"] in {"due", "no_show"},
                "can_simulate_rescheduling": future_scheduled(context),
                "available_slots": [slot_payload(slot) for slot in slots[:10]],
                "more_available_slots": len(slots) > 10,
                "source_kind": "bridge_upload",
                "record_owner": "forget_lah",
                "followup_status": episode.followup_status,
            }
        elif tool_name == "get_approved_instructions":
            note = (data.get("doctor_notes") or "").strip()
            payload = {
                "instructions": [
                    {
                        "instruction_id": f"BRIDGE-{episode.record_id}",
                        "version": str(episode.version),
                        "locale": "en-SG",
                        "approved_text": note,
                        "synthetic": False,
                    }
                ]
                if note
                else []
            }
        elif tool_name == "check_prerequisites":
            payload = {"prerequisites": ["NOT_APPLICABLE"]}
        else:
            raise ValueError("Tool not supported")
        return ToolResult(
            tool_name=tool_name,
            status="succeeded",
            source_version=source_version(episode),
            data=payload,
            error_code=None,
            retryable=False,
        )


class BridgeConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    run_id: UUID
    expected_version: int = Field(ge=1)
    expected_source_version: str = Field(min_length=40, max_length=40)
    slot_id: UUID | None = None
    slot_version: int | None = Field(default=None, ge=1)
    reschedule: bool = False


def bridge_confirm(factory, binding: dict, operation: dict) -> ToolResult:
    """Apply the shared policy-approved follow-up operation to the owned source."""
    from forget_lah.runtime.clinic_tools import ClinicTools
    from forget_lah.runtime.models import AgentRun, BridgeConfirmation
    from forget_lah.runtime.policy import has_authority
    from forget_lah.runtime.simulation import (
        booking_choice,
        current_tools,
        future_scheduled,
        latest_tool,
        reply_evidence,
        simulation_evidence,
    )

    name = "record_simulated_confirmation"

    def fail(code):
        return ClinicTools.failure(name, code, False)

    try:
        body = BridgeConfirmationInput.model_validate(operation)
    except ValidationError:
        return fail("SOURCE_INVALID")
    if bool(body.slot_id) != bool(body.slot_version) or (body.reschedule and not body.slot_id):
        return fail("SOURCE_INVALID")
    request_identity = body.model_dump(mode="json")
    with factory.begin() as db:
        case = db.scalar(
            select(FollowupCase)
            .where(
                FollowupCase.clinic_id == binding["clinic_id"],
                FollowupCase.patient_id == binding["patient_id"],
                FollowupCase.source_episode_ref == binding["source_episode_ref"],
                FollowupCase.source_episode_ref.startswith("bridge:"),
            )
            .with_for_update()
        )
        if not case:
            return fail("SOURCE_NOT_FOUND")
        episode = db.scalar(episode_query(binding).with_for_update())
        if not episode:
            return fail("SOURCE_NOT_FOUND")
        version = source_version(episode)
        prior = db.get(BridgeConfirmation, str(body.operation_id))
        if prior:
            if (
                prior.clinic_id != case.clinic_id
                or prior.case_id != case.id
                or prior.run_id != str(body.run_id)
                or prior.record_id != episode.record_id
                or prior.receipt.get("request") != request_identity
                or prior.source_version != version
            ):
                return fail("SOURCE_CONFLICT")
            return ToolResult(
                tool_name=name,
                status="succeeded",
                source_version=prior.source_version,
                data=prior.receipt,
                error_code=None,
                retryable=False,
            )
        if episode.version != body.expected_version or version != body.expected_source_version:
            return fail("SOURCE_CONFLICT")
        context = {
            "source_status": episode.normalized["source_status"],
            "scheduled_at": episode.normalized.get("appointment_at"),
        }
        if body.slot_id:
            if body.reschedule != future_scheduled(context) or (
                not body.reschedule and context["source_status"] not in {"due", "no_show"}
            ):
                return fail("SOURCE_CONFLICT")
        elif not future_scheduled(context):
            return fail("SOURCE_CONFLICT")
        run = db.get(AgentRun, str(body.run_id))
        if (
            not run
            or run.case_id != case.id
            or run.clinic_id != case.clinic_id
            or run.status != "running"
            or run.active_role != "engagement"
            or not has_authority(db, run)
        ):
            return fail("CONFIRMATION_EVIDENCE_REQUIRED")
        reply = reply_evidence(db, run)
        source = latest_tool(current_tools(db, run), "read_followup_context", "engagement")
        choice = booking_choice(db, run)
        if (
            not reply
            or reply.id != str(body.operation_id)
            or not simulation_evidence(db, run)["record_ready"]
            or not source
            or source.tool_result["source_version"] != version
            or bool(choice) != bool(body.slot_id)
            or (
                choice
                and (
                    choice["slot"]["id"] != str(body.slot_id)
                    or choice["slot"]["version"] != body.slot_version
                )
            )
        ):
            return fail("CONFIRMATION_EVIDENCE_REQUIRED")
        action = "CONFIRM_ATTENDANCE"
        if body.slot_id:
            slot = db.scalar(
                select(BridgeFollowupSlot)
                .where(
                    BridgeFollowupSlot.id == str(body.slot_id),
                    BridgeFollowupSlot.clinic_id == case.clinic_id,
                    BridgeFollowupSlot.episode_id == episode.id,
                )
                .with_for_update()
            )
            if (
                not slot
                or slot.version != body.slot_version
                or slot.status != "available"
                or as_utc(slot.starts_at) <= utcnow()
                or (
                    context["scheduled_at"]
                    and as_utc(slot.starts_at) == datetime.fromisoformat(context["scheduled_at"])
                )
            ):
                return fail("SOURCE_CONFLICT")
            # Options are reserved by staff for this episode, never a global clinic calendar.
            for old in db.scalars(
                select(BridgeFollowupSlot)
                .where(
                    BridgeFollowupSlot.clinic_id == case.clinic_id,
                    BridgeFollowupSlot.episode_id == episode.id,
                    BridgeFollowupSlot.status == "booked",
                )
                .with_for_update()
            ):
                old.status = "withdrawn"
                old.version += 1
            slot.status = "booked"
            slot.version += 1
            episode.normalized = {
                **episode.normalized,
                "record_type": "appointment",
                "source_status": "scheduled",
                "appointment_at": as_utc(slot.starts_at).isoformat(),
                "due_at": None,
                "booking_slot_id": slot.id,
            }
            episode.version += 1
            version = source_version(episode)
            action = "RESCHEDULE" if body.reschedule else "BOOK_FOLLOWUP"
        episode.followup_status = "confirmed"
        episode.updated_at = utcnow()
        receipt = {
            "receipt_id": str(body.operation_id),
            "source_episode_ref": case.source_episode_ref,
            "patient_id": case.patient_id,
            "run_id": run.id,
            "episode_version": episode.version,
            "scheduled_at": episode.normalized.get("appointment_at"),
            "confirmed_at": utcnow().isoformat(),
            "synthetic": True,
            "status": "PATIENT_CONFIRMED_ATTENDANCE",
            "booking_slot_id": str(body.slot_id) if body.slot_id else None,
            "source_kind": "bridge_upload",
            "record_owner": "forget_lah",
            "action": action,
            "request": request_identity,
        }
        db.add(
            BridgeConfirmation(
                id=str(body.operation_id),
                clinic_id=case.clinic_id,
                case_id=case.id,
                run_id=run.id,
                record_id=episode.record_id,
                source_version=version,
                receipt=receipt,
            )
        )
        db.flush()
        return ToolResult(
            tool_name=name,
            status="succeeded",
            source_version=version,
            data=receipt,
            error_code=None,
            retryable=False,
        )


def managed_view(db, case):
    episode = db.scalar(
        episode_query(
            {
                "clinic_id": case.clinic_id,
                "patient_id": case.patient_id,
                "source_episode_ref": case.source_episode_ref,
            }
        )
    )
    if not episode:
        return None
    return {
        "version": episode.version,
        "followup_status": episode.followup_status,
        "appointment_at": episode.normalized.get("appointment_at"),
        "options": [slot_payload(slot) for slot in slots_for(db, episode)[:10]],
    }


class FollowupOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    doctor: str = Field(min_length=1, max_length=80)


class WithdrawOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


def install_source_routes(app, factory, authorise, mutation_auth):
    def owned_case(db, case_id, clinics):
        case = db.scalar(
            select(FollowupCase)
            .where(
                FollowupCase.id == case_id,
                FollowupCase.clinic_id.in_(clinics),
                FollowupCase.source_episode_ref.startswith("bridge:"),
            )
            .with_for_update()
        )
        if not case:
            raise HTTPException(404, "Managed follow-up not found")
        episode = db.scalar(
            episode_query(
                {
                    "clinic_id": case.clinic_id,
                    "patient_id": case.patient_id,
                    "source_episode_ref": case.source_episode_ref,
                }
            ).with_for_update()
        )
        if not episode:
            raise HTTPException(404, "Managed follow-up not found")
        return case, episode

    @app.post("/api/bridge/cases/{case_id}/options", status_code=201)
    def add_option(case_id: str, body: FollowupOptionInput, request: Request):
        with factory.begin() as db:
            user, clinics = mutation_auth(db, request)
            case, episode = owned_case(db, case_id, clinics)
            if episode.version != body.expected_version:
                raise HTTPException(409, "Follow-up changed; refresh before adding an option")
            if (
                body.starts_at <= utcnow()
                or body.ends_at <= body.starts_at
                or not body.doctor.strip()
            ):
                raise HTTPException(
                    422, "Provide a future start, later end, and clinic team or doctor"
                )
            if episode.normalized.get(
                "appointment_at"
            ) and body.starts_at == datetime.fromisoformat(episode.normalized["appointment_at"]):
                raise HTTPException(422, "An alternative must differ from the current appointment")
            prior = db.scalar(
                select(BridgeFollowupSlot).where(
                    BridgeFollowupSlot.episode_id == episode.id,
                    BridgeFollowupSlot.starts_at == body.starts_at.astimezone(UTC),
                    BridgeFollowupSlot.doctor == body.doctor.strip(),
                )
            )
            if prior:
                raise HTTPException(409, "This option already exists")
            if len(slots_for(db, episode)) >= 10:
                raise HTTPException(
                    409, "Withdraw an unused option before adding more (maximum 10)"
                )
            db.add(
                BridgeFollowupSlot(
                    clinic_id=case.clinic_id,
                    episode_id=episode.id,
                    starts_at=body.starts_at.astimezone(UTC),
                    ends_at=body.ends_at.astimezone(UTC),
                    doctor=body.doctor.strip(),
                    approved_by=user.id,
                )
            )
            episode.version += 1
            episode.updated_at = utcnow()
            db.flush()
            return managed_view(db, case)

    @app.post("/api/bridge/cases/{case_id}/options/{slot_id}/withdraw")
    def withdraw_option(case_id: str, slot_id: str, body: WithdrawOptionInput, request: Request):
        with factory.begin() as db:
            _, clinics = mutation_auth(db, request)
            case, episode = owned_case(db, case_id, clinics)
            slot = db.scalar(
                select(BridgeFollowupSlot)
                .where(
                    BridgeFollowupSlot.id == slot_id,
                    BridgeFollowupSlot.episode_id == episode.id,
                    BridgeFollowupSlot.clinic_id == case.clinic_id,
                )
                .with_for_update()
            )
            if not slot:
                raise HTTPException(404, "Follow-up option not found")
            if episode.version != body.expected_version or slot.status != "available":
                raise HTTPException(409, "Option changed; refresh before withdrawing")
            slot.status = "withdrawn"
            slot.version += 1
            episode.version += 1
            episode.updated_at = utcnow()
            db.flush()
            return managed_view(db, case)
