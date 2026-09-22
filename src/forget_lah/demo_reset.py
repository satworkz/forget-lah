"""Explicitly enabled synthetic demo reset. Preserves identities and usage accounting."""

import secrets
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from forget_lah.auth import digest
from forget_lah.channel_models import (
    ChannelBinding,
    ChannelInbox,
    ChannelOutbox,
    ChannelRoutingState,
)
from forget_lah.db import (
    AuditEvent,
    BridgeEpisode,
    BridgeFollowupSlot,
    BridgeImportProfile,
    BridgeIntakeBatch,
    BridgeIntakeRecord,
    FollowupCase,
    Job,
    Patient,
    utcnow,
)
from forget_lah.detector import save_candidate, trigger_for
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentEvent,
    AgentRun,
    AgentStep,
    BridgeConfirmation,
    PatientMemory,
    PatientPreference,
    SimulatedMessage,
    StaffAppointmentChange,
    StaffHandoff,
)
from forget_lah.source import DEMO_CLINIC_ID, read_candidates

DEMO_EPISODES = {
    "DEMO-DENTAL-RECALL-01": "20000000-0000-4000-8000-000000000001",
    "DEMO-MYOPIA-VISIT-01": "20000000-0000-4000-8000-000000000002",
    "DEMO-ANTENATAL-VISIT-01": "20000000-0000-4000-8000-000000000003",
}
RESET_MODELS = (
    StaffAppointmentChange,
    ChannelRoutingState,
    SimulatedMessage,
    AgentDelegation,
    AgentEvent,
    StaffHandoff,
    StaffAppointmentChange,
    AgentStep,
    AgentRun,
    AuditEvent,
    Job,
    FollowupCase,
    PatientMemory,
    PatientPreference,
    Patient,
)


class ResetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["RESET"]
    expected_case_ids: list[UUID] = Field(max_length=2000)
    include_intake: bool = False
    expected_intake_batch_ids: list[UUID] = Field(default_factory=list, max_length=2000)


def reset_enabled(settings, clinics):
    return (
        settings.demo_reset_enabled
        and settings.app_env in {"local", "test", "demo"}
        and DEMO_CLINIC_ID in clinics
    )


def demo_reset_cases(db, *, include_intake=False):
    """Exclude imported cases only when their clinic/patient/episode provenance matches."""
    if include_intake:
        return list(
            db.scalars(select(FollowupCase).where(FollowupCase.clinic_id == DEMO_CLINIC_ID))
        )
    imported = (
        select(BridgeIntakeRecord.id)
        .where(
            BridgeIntakeRecord.clinic_id == FollowupCase.clinic_id,
            BridgeIntakeRecord.patient_id == FollowupCase.patient_id,
            BridgeIntakeRecord.source_episode_ref == FollowupCase.source_episode_ref,
            BridgeIntakeRecord.status == "IMPORTED",
            FollowupCase.source_episode_ref.startswith("bridge:"),
        )
        .exists()
    )
    return list(
        db.scalars(select(FollowupCase).where(FollowupCase.clinic_id == DEMO_CLINIC_ID, ~imported))
    )


def validate_candidates(candidates):
    refs = {c.source_episode_ref for c in candidates}
    if (
        not set(DEMO_EPISODES).issubset(refs)
        or len(candidates) > 200
        or len(refs) != len(candidates)
    ):
        raise ValueError("Expected a complete, unique local simulator snapshot")
    synthetic_patients = set(DEMO_EPISODES.values())
    for c in candidates:
        if c.source_episode_ref.startswith("SIM-"):
            original_patient = str(UUID(c.source_episode_ref[4:]))
            if str(c.patient_id) == original_patient:
                synthetic_patients.add(original_patient)
    for c in candidates:
        expected_patient = DEMO_EPISODES.get(c.source_episode_ref)
        if expected_patient is None and c.source_episode_ref.startswith("SIM-"):
            UUID(c.source_episode_ref[4:])
            if str(c.patient_id) in synthetic_patients:
                expected_patient = str(c.patient_id)
        if str(c.patient_id) != expected_patient or not c.display_alias.endswith("(demo)"):
            raise ValueError("Unexpected synthetic candidate")


def lock_reset_tables(db):
    if db.bind.dialect.name == "postgresql":
        # No network calls while locked. NOWAIT avoids a deadlock with a worker/API
        # transaction; the caller returns a retryable conflict without deleting data.
        tables = ", ".join(
            model.__tablename__
            for model in (
                ChannelBinding,
                ChannelInbox,
                ChannelOutbox,
                ChannelRoutingState,
                BridgeIntakeRecord,
                BridgeIntakeBatch,
                BridgeImportProfile,
                BridgeEpisode,
                BridgeFollowupSlot,
                BridgeConfirmation,
                *RESET_MODELS,
            )
        )
        db.execute(text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE NOWAIT"))
    elif db.bind.dialect.name == "sqlite":
        # Test/local SQLite acquires its writer lock before reading the generation.
        db.execute(text("UPDATE followup_case SET case_version = case_version WHERE 0"))
    else:
        raise HTTPException(409, "Demo reset is unavailable for this database")


def reset_demo(
    db, expected_case_ids, candidates, *, include_intake=False, expected_intake_batch_ids=()
):
    """Caller holds reset locks and commits deletion/recreation together."""
    validate_candidates(candidates)
    if include_intake:
        batch_ids = set(
            db.scalars(
                select(BridgeIntakeBatch.id).where(BridgeIntakeBatch.clinic_id == DEMO_CLINIC_ID)
            )
        )
        if set(expected_intake_batch_ids) != batch_ids:
            raise HTTPException(409, "Intelligent Intake changed. Refresh before resetting.")
    cases = demo_reset_cases(db, include_intake=include_intake)
    if db.scalar(
        select(StaffAppointmentChange.id).where(
            StaffAppointmentChange.case_id.in_([case.id for case in cases]),
            StaffAppointmentChange.status == "pending",
        )
    ):
        raise HTTPException(409, "Recover pending appointment changes before reset")
    if set(expected_case_ids) != {c.id for c in cases} or len(set(expected_case_ids)) != len(
        expected_case_ids
    ):
        raise HTTPException(
            409, "Demo cases changed. Refresh the dashboard before resetting again."
        )
    case_ids = {case.id for case in cases}
    imported_patient_ids = set(
        db.scalars(
            select(BridgeIntakeRecord.patient_id).where(
                BridgeIntakeRecord.clinic_id == DEMO_CLINIC_ID,
                BridgeIntakeRecord.status == "IMPORTED",
                BridgeIntakeRecord.patient_id.is_not(None),
            )
        )
    )
    patients = list(
        db.scalars(
            select(Patient).where(
                Patient.clinic_id == DEMO_CLINIC_ID,
                Patient.id.not_in(imported_patient_ids) if not include_intake else True,
            )
        )
    )
    patient_ids = {patient.id for patient in patients}
    source_patients = {c.source_episode_ref: str(c.patient_id) for c in candidates}
    imported_pairs = set(
        db.execute(
            select(BridgeIntakeRecord.patient_id, BridgeIntakeRecord.source_episode_ref).where(
                BridgeIntakeRecord.clinic_id == DEMO_CLINIC_ID,
                BridgeIntakeRecord.status == "IMPORTED",
            )
        )
    )
    if (
        imported_patient_ids.intersection(source_patients.values())
        or any(
            (
                c.source_episode_ref not in source_patients
                or c.patient_id != source_patients[c.source_episode_ref]
            )
            and not (
                include_intake
                and c.source_episode_ref.startswith("bridge:")
                and (c.patient_id, c.source_episode_ref) in imported_pairs
            )
            for c in cases
        )
        or any(
            (p.id not in source_patients.values() or not p.display_alias.endswith("(demo)"))
            and not (include_intake and p.id in imported_patient_ids)
            for p in patients
        )
    ):
        raise HTTPException(409, "Unexpected records found in the demo clinic. Nothing was reset.")
    if db.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.clinic_id == DEMO_CLINIC_ID,
            AgentRun.case_id.in_(case_ids),
            AgentRun.status.in_(["queued", "running"]),
        )
        .limit(1)
    ):
        raise HTTPException(
            409, "A review is queued or processing. Pause active reviews, then reset."
        )
    if db.scalar(
        select(ChannelOutbox.id)
        .where(
            ChannelOutbox.clinic_id == DEMO_CLINIC_ID,
            ChannelOutbox.case_id.in_(case_ids),
            ChannelOutbox.status == "sending",
        )
        .limit(1)
    ):
        raise HTTPException(409, "A WhatsApp dispatch is in progress. Wait before resetting.")
    # Preserve explicit patient enrollment, never infer it from a name or phone.
    enrolled = []
    routing_ids = []
    by_id = {case.id: case for case in cases}
    for binding in db.scalars(
        select(ChannelBinding).where(
            ChannelBinding.clinic_id == DEMO_CLINIC_ID, ChannelBinding.case_id.in_(case_ids)
        )
    ):
        routing_ids.append(binding.id)
        anchor = by_id.get(binding.case_id)
        if binding.enabled and anchor:
            enrolled.append((binding.id, anchor.patient_id, anchor.source_episode_ref))
        binding.enabled = False
    for message in db.scalars(
        select(ChannelOutbox).where(
            ChannelOutbox.clinic_id == DEMO_CLINIC_ID, ChannelOutbox.case_id.in_(case_ids)
        )
    ):
        message.body = ""
        if message.status == "queued":
            message.status = "canceled"
    for incoming in db.scalars(
        select(ChannelInbox).where(
            ChannelInbox.clinic_id == DEMO_CLINIC_ID, ChannelInbox.case_id.in_(case_ids)
        )
    ):
        routing_ids.append(incoming.sid)
        incoming.body = ""
        if incoming.status == "queued":
            incoming.status = "reset"
    # Provider SID tombstones remain to reject redelivery after reset. Old case IDs
    # remain historical; only the binding moves to the same patient in the new generation.
    deleted = {}
    if include_intake:
        for model in (
            BridgeConfirmation,
            BridgeFollowupSlot,
            BridgeEpisode,
            BridgeIntakeRecord,
            BridgeImportProfile,
            BridgeIntakeBatch,
        ):
            deleted[model.__tablename__] = db.execute(
                delete(model).where(model.clinic_id == DEMO_CLINIC_ID),
                execution_options={"synchronize_session": False},
            ).rowcount
    for model in RESET_MODELS:
        if model is ChannelRoutingState:
            scope = model.id.in_(routing_ids)
        elif model is Patient:
            scope = model.id.in_(patient_ids)
        elif model in (PatientMemory, PatientPreference):
            scope = model.patient_id.in_(patient_ids)
        else:
            scope = (
                model.case_id.in_(case_ids) if model is not FollowupCase else model.id.in_(case_ids)
            )
        deleted[model.__tablename__] = db.execute(
            delete(model).where(model.clinic_id == DEMO_CLINIC_ID, scope),
            execution_options={"synchronize_session": False},
        ).rowcount
    db.expunge_all()
    now = utcnow()
    new_ids = [
        save_candidate(db, DEMO_CLINIC_ID, c, trigger).id
        for c in candidates
        if (trigger := trigger_for(c, now))
    ]
    restored = []
    for binding_id, patient_id, episode_ref in enrolled:
        matches = list(
            db.scalars(
                select(FollowupCase)
                .where(
                    FollowupCase.clinic_id == DEMO_CLINIC_ID,
                    FollowupCase.patient_id == patient_id,
                    FollowupCase.id.in_(new_ids),
                )
                .order_by(FollowupCase.created_at, FollowupCase.id)
            )
        )
        if not matches:
            continue  # Never connect a different patient if this one is no longer eligible.
        anchor = next(
            (case for case in matches if case.source_episode_ref == episode_ref), matches[0]
        )
        binding = db.get(ChannelBinding, binding_id)
        binding.case_id, binding.enabled, binding.created_at = anchor.id, True, now
        # inbound_at is real channel evidence, not reset time; preserve its expiry.
        restored.append(anchor.id)
    return {
        "status": "reset",
        "case_ids": new_ids,
        "deleted": deleted,
        "whatsapp_case_ids": restored,
    }


def install_demo_routes(app, factory, settings, authorise):
    def authorised(db, request):
        _, session, clinics = authorise(db, request)
        if not reset_enabled(settings, clinics):
            raise HTTPException(403, "Demo reset is disabled or unavailable for your clinic")
        if not secrets.compare_digest(
            digest(request.headers.get("X-CSRF-Token", "")), session.csrf_hash
        ):
            raise HTTPException(403, "Invalid CSRF token")

    @app.post("/api/demo/reset")
    def reset(body: ResetInput, request: Request):
        with factory() as db:
            authorised(db, request)
        try:
            candidates = read_candidates(settings.mock_clinic_url)
            validate_candidates(candidates)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                503, "Fresh demo source is unavailable or invalid. Nothing was reset."
            ) from exc
        try:
            with factory.begin() as db:
                lock_reset_tables(db)
                authorised(db, request)
                result = reset_demo(
                    db,
                    [str(i) for i in body.expected_case_ids],
                    candidates,
                    include_intake=body.include_intake,
                    expected_intake_batch_ids=[str(i) for i in body.expected_intake_batch_ids],
                )
            return result
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "55P03":
                raise HTTPException(
                    503, "Could not confirm the reset. Refresh the dashboard before retrying."
                ) from exc
            raise HTTPException(
                409, "The demo database is busy. Nothing was reset; try again shortly."
            ) from exc
