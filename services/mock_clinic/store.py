"""Source-owned persistence. Never joins or reads forget-lah's application database."""

import hashlib
import json
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from forget_lah.source import DEMO_CLINIC_ID
from services.mock_clinic.contracts import iso
from services.mock_clinic.fixtures import candidates, followup_context


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "sim_patient"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_alias: Mapped[str] = mapped_column(String(100))


class Episode(Base):
    __tablename__ = "sim_episode"
    ref: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("sim_patient.id"))
    specialty: Mapped[str] = mapped_column(String(20))
    record_type: Mapped[str] = mapped_column(String(20))
    source_status: Mapped[str] = mapped_column(String(20))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_future_booking: Mapped[bool] = mapped_column(Boolean, default=False)
    doctor_note: Mapped[str] = mapped_column(String(400), default="")
    note_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    prerequisite: Mapped[str] = mapped_column(String(30), default="NOT_APPLICABLE")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Slot(Base):
    __tablename__ = "sim_slot"
    __table_args__ = (UniqueConstraint("doctor", "starts_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    specialty: Mapped[str] = mapped_column(String(20))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    doctor: Mapped[str] = mapped_column(String(80))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Confirmation(Base):
    __tablename__ = "sim_confirmation"
    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    episode_ref: Mapped[str] = mapped_column(ForeignKey("sim_episode.ref"))
    patient_id: Mapped[str] = mapped_column(String(36))
    run_id: Mapped[str] = mapped_column(String(36))
    episode_version: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    booking_slot_id: Mapped[str | None] = mapped_column(String(36))
    booking_slot_version: Mapped[int | None] = mapped_column(Integer)
    prior_episode_version: Mapped[int | None] = mapped_column(Integer)


def confirmation_dict(row):
    return {
        "receipt_id": row.operation_id,
        "source_episode_ref": row.episode_ref,
        "patient_id": row.patient_id,
        "run_id": row.run_id,
        "episode_version": row.episode_version,
        "scheduled_at": iso(row.scheduled_at),
        "confirmed_at": iso(row.confirmed_at),
        "synthetic": True,
        "status": "PATIENT_CONFIRMED_ATTENDANCE",
        "booking_slot_id": row.booking_slot_id,
    }


def latest_confirmation(db, row):
    receipt = db.scalar(
        select(Confirmation)
        .where(Confirmation.episode_ref == row.ref, Confirmation.episode_version == row.version)
        .order_by(Confirmation.confirmed_at.desc())
        .limit(1)
    )
    return confirmation_dict(receipt) if receipt else None


def seed(factory):
    # Dates are calculated only on first insertion. Restarts preserve all edits.
    with factory.begin() as db:
        for item in candidates():
            ref = item["source_episode_ref"]
            if db.get(Episode, ref):
                continue
            if not db.get(Patient, item["patient_id"]):
                db.add(Patient(id=item["patient_id"], display_alias=item["display_alias"]))
                db.flush()
            envelope = followup_context(ref)
            fields = {
                k: item[k] for k in ("patient_id", "specialty", "record_type", "source_status")
            }
            for field in ("scheduled_at", "due_at"):
                fields[field] = datetime.fromisoformat(item[field]) if item.get(field) else None
            db.add(
                Episode(
                    ref=ref,
                    **fields,
                    doctor_note=envelope["instructions"][0]["approved_text"],
                    note_approved=True,
                )
            )


def candidate(db, row):
    return {
        "patient_id": row.patient_id,
        "display_alias": db.get(Patient, row.patient_id).display_alias,
        "source_episode_ref": row.ref,
        "specialty": row.specialty,
        "record_type": row.record_type,
        "source_status": row.source_status,
        "scheduled_at": iso(row.scheduled_at),
        "due_at": iso(row.due_at),
        "has_future_booking": row.has_future_booking,
    }


def slot_dict(row):
    return {
        "id": row.id,
        "specialty": row.specialty,
        "starts_at": iso(row.starts_at),
        "ends_at": iso(row.ends_at),
        "doctor": row.doctor,
        "available": row.available,
        "version": row.version,
    }


def can_book_followup(row, now=None):
    """Source capability for a new slot; a past visit cannot be confirmed retroactively."""
    if row.has_future_booking:
        return False
    if row.record_type == "recall" and row.source_status == "due":
        return True
    scheduled = row.scheduled_at
    if scheduled and scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=UTC)
    return bool(
        row.record_type == "appointment"
        and row.source_status == "no_show"
        and scheduled
        and scheduled < (now or datetime.now(UTC))
    )


def envelope(db, row, *, date_from=None, date_to=None):
    slots = list(
        db.scalars(
            select(Slot)
            .where(
                Slot.specialty == row.specialty,
                Slot.available.is_(True),
                Slot.starts_at >= datetime.now(UTC),
            )
            .order_by(Slot.starts_at, Slot.id)
            .limit(500)
        )
    )
    # Version covers all availability, independent of the requested date window.
    version_slots = slots
    if date_from:
        lower = datetime.combine(date_from, time.min, ZoneInfo("Asia/Singapore"))
        slots = [
            s
            for s in slots
            if (s.starts_at.replace(tzinfo=UTC) if s.starts_at.tzinfo is None else s.starts_at)
            >= lower
        ]
    if date_to:
        upper = datetime.combine(date_to + timedelta(days=1), time.min, ZoneInfo("Asia/Singapore"))
        slots = [
            s
            for s in slots
            if (s.starts_at.replace(tzinfo=UTC) if s.starts_at.tzinfo is None else s.starts_at)
            < upper
        ]
    available = [
        {
            k: v
            for k, v in slot_dict(s).items()
            if k in {"id", "starts_at", "ends_at", "doctor", "version"}
        }
        for s in slots[:10]
    ]
    # Availability edits also change source_version; a previous read remains historical evidence.
    digest = hashlib.sha256(
        json.dumps([row.version, [slot_dict(s) for s in version_slots]], sort_keys=True).encode()
    ).hexdigest()[:16]
    return {
        "clinic_id": DEMO_CLINIC_ID,
        "patient_id": row.patient_id,
        "source_episode_ref": row.ref,
        "source_version": f"sim-{digest}",
        "synthetic": True,
        "context": {
            "specialty": row.specialty,
            "source_status": row.source_status,
            "scheduled_at": iso(row.scheduled_at),
            "due_at": iso(row.due_at),
            "can_contact_patient": False,
            "can_write_appointments": False,
            "episode_version": row.version,
            "can_simulate_confirmation": True,
            "can_simulate_booking": can_book_followup(row),
            "can_simulate_rescheduling": row.record_type == "appointment"
            and row.source_status == "scheduled",
            "available_slots": available,
            "more_available_slots": len(slots) > 10,
        },
        "instructions": [
            {
                "instruction_id": f"NOTE-{row.patient_id}",
                "version": str(row.version),
                "locale": "en-SG",
                "approved_text": row.doctor_note,
                "synthetic": True,
            }
        ]
        if row.note_approved and row.doctor_note
        else [],
        "prerequisites": [row.prerequisite],
    }


class StaffChange(Base):
    __tablename__ = "sim_staff_change"
    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    episode_ref: Mapped[str] = mapped_column(ForeignKey("sim_episode.ref"))
    request: Mapped[dict] = mapped_column(JSON)
    receipt: Mapped[dict] = mapped_column(JSON)


def release_owned_slot(db, row):
    """Release capacity only when a receipt proves this episode owns the booked revision."""
    confirmation = db.scalar(
        select(Confirmation)
        .where(
            Confirmation.episode_ref == row.ref,
            Confirmation.episode_version == row.version,
            Confirmation.booking_slot_id.is_not(None),
        )
        .order_by(Confirmation.confirmed_at.desc())
    )
    slot_id = confirmation.booking_slot_id if confirmation else None
    version = confirmation.booking_slot_version if confirmation else None
    scheduled_at = confirmation.scheduled_at if confirmation else None
    if not confirmation:
        for change in db.scalars(select(StaffChange).where(StaffChange.episode_ref == row.ref)):
            if change.receipt.get("episode_version") == row.version:
                slot_id = change.receipt["slot_id"]
                version = change.request["slot_version"]
                scheduled_at = datetime.fromisoformat(change.receipt["scheduled_at"])
                break

    def utc(value):
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value

    slot = db.scalar(select(Slot).where(Slot.id == slot_id).with_for_update()) if slot_id else None
    if (
        slot
        and not slot.available
        and slot.version == version + 1
        and utc(scheduled_at) == utc(row.scheduled_at) == utc(slot.starts_at)
    ):
        slot.available = True
        slot.version += 1
