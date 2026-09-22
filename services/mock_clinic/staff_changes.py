"""Authorized API-backed staff follow-up changes, without attendance confirmation."""

import secrets

from fastapi import HTTPException, Request
from sqlalchemy import select, text

from forget_lah.bridge_source import as_utc
from forget_lah.db import utcnow
from forget_lah.source import DEMO_CLINIC_ID
from forget_lah.staff_change_contract import StaffSourceChange
from services.mock_clinic.store import Episode, Slot, StaffChange, envelope, release_owned_slot


def install_staff_changes(app, factory, settings):
    @app.post("/internal/followup/{episode}/staff-change")
    def change(episode: str, body: StaffSourceChange, request: Request):
        key = settings.mock_clinic_followup_key
        if not key or not secrets.compare_digest(
            request.headers.get("X-Followup-Key", ""), key.get_secret_value()
        ):
            raise HTTPException(403, "Follow-up access denied")
        if str(body.clinic_id) != DEMO_CLINIC_ID:
            raise HTTPException(404, "Appointment not found")
        payload = body.model_dump(mode="json")
        with factory.begin() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(76139003)"))
            row = db.scalar(select(Episode).where(Episode.ref == episode).with_for_update())
            if not row or row.patient_id != str(body.patient_id):
                raise HTTPException(404, "Appointment not found")
            prior = db.get(StaffChange, str(body.operation_id))
            if prior:
                if prior.episode_ref != episode or prior.request != payload:
                    raise HTTPException(409, "Operation already used")
                return prior.receipt
            slot = db.scalar(select(Slot).where(Slot.id == str(body.slot_id)).with_for_update())
            if (
                row.version != body.expected_version
                or envelope(db, row)["source_version"] != body.expected_source_version
                or row.source_status != "scheduled"
                or not row.scheduled_at
                or as_utc(row.scheduled_at) <= utcnow()
                or row.prerequisite != "NOT_APPLICABLE"
                or not slot
                or not slot.available
                or slot.version != body.slot_version
                or slot.specialty != row.specialty
                or as_utc(slot.starts_at) <= utcnow()
                or as_utc(slot.starts_at) == as_utc(row.scheduled_at)
            ):
                raise HTTPException(409, "Appointment or slot changed; refresh availability")
            old = as_utc(row.scheduled_at).isoformat()
            release_owned_slot(db, row)
            slot.available = False
            slot.version += 1
            row.scheduled_at = slot.starts_at
            row.version += 1
            db.flush()
            receipt = {
                "operation_id": str(body.operation_id),
                "patient_id": row.patient_id,
                "source_episode_ref": episode,
                "actor_id": str(body.actor_id),
                "old_scheduled_at": old,
                "scheduled_at": as_utc(row.scheduled_at).isoformat(),
                "slot_id": slot.id,
                "episode_version": row.version,
                "changed_at": utcnow().isoformat(),
                "status": "STAFF_CHANGED_AWAITING_PATIENT",
                "source_version": envelope(db, row)["source_version"],
                "record_owner": "clinic_api",
            }
            db.add(
                StaffChange(
                    operation_id=str(body.operation_id),
                    episode_ref=episode,
                    request=payload,
                    receipt=receipt,
                )
            )
            return receipt
