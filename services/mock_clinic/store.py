"""Source-owned persistence. Never joins or reads forget-lah's application database."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
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


def envelope(db, row):
    slots = list(
        db.scalars(
            select(Slot)
            .where(
                Slot.specialty == row.specialty,
                Slot.available.is_(True),
                Slot.starts_at >= datetime.now(UTC),
            )
            .order_by(Slot.starts_at, Slot.id)
            .limit(11)
        )
    )
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
        json.dumps([row.version, [slot_dict(s) for s in slots]], sort_keys=True).encode()
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
            "can_simulate_booking": row.record_type == "recall"
            and row.source_status == "due"
            and not row.has_future_booking,
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
