"""Explicitly enabled local demo reset. Never clears identities or usage accounting."""

import secrets
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from forget_lah.auth import digest
from forget_lah.db import AuditEvent, FollowupCase, Job, Patient, utcnow
from forget_lah.detector import save_candidate, trigger_for
from forget_lah.runtime.models import (
    AgentDelegation,
    AgentEvent,
    AgentRun,
    AgentStep,
    PatientMemory,
    PatientPreference,
    SimulatedMessage,
    StaffHandoff,
)
from forget_lah.source import DEMO_CLINIC_ID, read_candidates

DEMO_EPISODES = {
    "DEMO-DENTAL-RECALL-01": "20000000-0000-4000-8000-000000000001",
    "DEMO-MYOPIA-VISIT-01": "20000000-0000-4000-8000-000000000002",
    "DEMO-ANTENATAL-VISIT-01": "20000000-0000-4000-8000-000000000003",
}
RESET_MODELS = (
    SimulatedMessage,
    AgentDelegation,
    AgentEvent,
    StaffHandoff,
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
    expected_case_ids: list[UUID] = Field(max_length=200)


def reset_enabled(settings, clinics):
    return (
        settings.demo_reset_enabled
        and settings.app_env in {"local", "test"}
        and DEMO_CLINIC_ID in clinics
    )


def validate_candidates(candidates):
    refs = {c.source_episode_ref for c in candidates}
    if (
        not set(DEMO_EPISODES).issubset(refs)
        or len(candidates) > 200
        or len(refs) != len(candidates)
    ):
        raise ValueError("Expected a complete, unique local simulator snapshot")
    for c in candidates:
        expected_patient = DEMO_EPISODES.get(c.source_episode_ref)
        if expected_patient is None and c.source_episode_ref.startswith("SIM-"):
            expected_patient = str(UUID(c.source_episode_ref[4:]))
        if str(c.patient_id) != expected_patient or not c.display_alias.endswith("(demo)"):
            raise ValueError("Unexpected synthetic candidate")


def lock_reset_tables(db):
    if db.bind.dialect.name == "postgresql":
        # No network calls while locked. NOWAIT avoids a deadlock with a worker/API
        # transaction; the caller returns a retryable conflict without deleting data.
        tables = ", ".join(model.__tablename__ for model in RESET_MODELS)
        db.execute(text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE NOWAIT"))
    elif db.bind.dialect.name == "sqlite":
        # Test/local SQLite acquires its writer lock before reading the generation.
        db.execute(text("UPDATE followup_case SET case_version = case_version WHERE 0"))
    else:
        raise HTTPException(409, "Demo reset is unavailable for this database")


def reset_demo(db, expected_case_ids, candidates):
    """Caller holds reset locks and commits deletion/recreation together."""
    validate_candidates(candidates)
    cases = list(db.scalars(select(FollowupCase).where(FollowupCase.clinic_id == DEMO_CLINIC_ID)))
    if set(expected_case_ids) != {c.id for c in cases} or len(set(expected_case_ids)) != len(
        expected_case_ids
    ):
        raise HTTPException(
            409, "Demo cases changed. Refresh the dashboard before resetting again."
        )
    patients = list(db.scalars(select(Patient).where(Patient.clinic_id == DEMO_CLINIC_ID)))
    source_patients = {c.source_episode_ref: str(c.patient_id) for c in candidates}
    if any(
        c.source_episode_ref not in source_patients
        or c.patient_id != source_patients[c.source_episode_ref]
        for c in cases
    ) or any(
        p.id not in source_patients.values() or not p.display_alias.endswith("(demo)")
        for p in patients
    ):
        raise HTTPException(409, "Unexpected records found in the demo clinic. Nothing was reset.")
    if db.scalar(
        select(AgentRun.id)
        .where(AgentRun.clinic_id == DEMO_CLINIC_ID, AgentRun.status.in_(["queued", "running"]))
        .limit(1)
    ):
        raise HTTPException(
            409, "A review is queued or processing. Pause active reviews, then reset."
        )
    deleted = {}
    for model in RESET_MODELS:
        deleted[model.__tablename__] = db.execute(
            delete(model).where(model.clinic_id == DEMO_CLINIC_ID),
            execution_options={"synchronize_session": False},
        ).rowcount
    db.expunge_all()
    now = utcnow()
    new_ids = [
        save_candidate(db, DEMO_CLINIC_ID, c, trigger).id
        for c in candidates
        if (trigger := trigger_for(c, now))
    ]
    return {"status": "reset", "case_ids": new_ids, "deleted": deleted}


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
                result = reset_demo(db, [str(i) for i in body.expected_case_ids], candidates)
            return result
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "55P03":
                raise HTTPException(
                    503, "Could not confirm the reset. Refresh the dashboard before retrying."
                ) from exc
            raise HTTPException(
                409, "The demo database is busy. Nothing was reset; try again shortly."
            ) from exc
