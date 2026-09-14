"""A narrow synthetic follow-up operation, separate from the human editor API."""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import select, text

from forget_lah.source import DEMO_CLINIC_ID
from services.mock_clinic.contracts import Strict
from services.mock_clinic.store import Confirmation, Episode, confirmation_dict, envelope


class ConfirmInput(Strict):
    operation_id: UUID
    clinic_id: UUID
    patient_id: UUID
    run_id: UUID
    expected_version: int = Field(ge=1)


def install_confirmation_routes(app, factory, settings):
    @app.post("/internal/followup/{episode}/confirm-attendance")
    def confirm(episode: str, body: ConfirmInput, request: Request):
        key = settings.mock_clinic_followup_key
        if (
            not key
            or not key.get_secret_value()
            or not secrets.compare_digest(
                request.headers.get("X-Followup-Key", ""), key.get_secret_value()
            )
        ):
            raise HTTPException(403, "Synthetic follow-up access denied")
        if str(body.clinic_id) != DEMO_CLINIC_ID:
            raise HTTPException(404, "Synthetic appointment not found")
        with factory.begin() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(76139003)"))
            row = db.scalar(select(Episode).where(Episode.ref == episode).with_for_update())
            if not row or row.patient_id != str(body.patient_id):
                raise HTTPException(404, "Synthetic appointment not found")
            prior = db.get(Confirmation, str(body.operation_id))
            if prior:
                if (prior.episode_ref, prior.patient_id, prior.run_id, prior.episode_version) != (
                    episode,
                    str(body.patient_id),
                    str(body.run_id),
                    body.expected_version,
                ):
                    raise HTTPException(409, "Confirmation key belongs to another operation")
            if row.version != body.expected_version:
                raise HTTPException(409, "Appointment or notes changed; read the source again")
            now = datetime.now(UTC)
            scheduled = row.scheduled_at
            if scheduled and scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=UTC)
            if (
                row.record_type != "appointment"
                or row.source_status != "scheduled"
                or not scheduled
                or scheduled <= now
                or row.prerequisite != "NOT_APPLICABLE"
            ):
                raise HTTPException(409, "This appointment requires staff review")
            if not prior:
                prior = Confirmation(
                    operation_id=str(body.operation_id),
                    episode_ref=episode,
                    patient_id=row.patient_id,
                    run_id=str(body.run_id),
                    episode_version=row.version,
                    scheduled_at=scheduled,
                    confirmed_at=now,
                )
                db.add(prior)
                db.flush()
            return {
                "receipt": confirmation_dict(prior),
                "source_version": envelope(db, row)["source_version"],
            }
