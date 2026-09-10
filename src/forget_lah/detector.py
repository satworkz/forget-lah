from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from forget_lah.db import AuditEvent, FollowupCase, Job, Patient
from forget_lah.source import Candidate


def trigger_for(candidate: Candidate, now: datetime) -> str | None:
    if candidate.source_status in {"cancelled", "completed"}:
        return None
    if candidate.record_type == "appointment" and candidate.source_status == "no_show":
        return "MISSED"
    if candidate.record_type == "appointment" and candidate.source_status == "scheduled":
        when = candidate.scheduled_at
        if when and when.tzinfo and now <= when <= now + timedelta(days=7):
            return "UPCOMING"
    if candidate.record_type == "recall" and candidate.source_status == "due":
        due = candidate.due_at
        if due and due.tzinfo and due <= now and not candidate.has_future_booking:
            return "RECALL_OVERDUE"
    return None


def detect(
    factory, clinic_id: str, candidates: list[Candidate], now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    created = 0
    for candidate in candidates:
        trigger = trigger_for(candidate, now)
        if not trigger:
            continue
        with factory() as db:
            if db.scalar(
                select(FollowupCase.id).where(
                    FollowupCase.clinic_id == clinic_id,
                    FollowupCase.source_episode_ref == candidate.source_episode_ref,
                )
            ):
                continue
            try:
                patient_id = str(candidate.patient_id)
                patient = db.get(Patient, patient_id)
                if patient and patient.clinic_id != clinic_id:
                    raise ValueError("Source patient belongs to a different clinic")
                if not patient:
                    db.add(
                        Patient(
                            id=patient_id,
                            clinic_id=clinic_id,
                            display_alias=candidate.display_alias,
                        )
                    )
                    db.flush()
                case = FollowupCase(
                    clinic_id=clinic_id,
                    patient_id=patient_id,
                    source_episode_ref=candidate.source_episode_ref,
                    specialty=candidate.specialty,
                    trigger=trigger,
                )
                db.add(case)
                db.flush()
                db.add(Job(clinic_id=clinic_id, case_id=case.id))
                db.add(
                    AuditEvent(
                        clinic_id=clinic_id,
                        case_id=case.id,
                        event_type="CASE_IDENTIFIED",
                        details={
                            "source_episode_ref": candidate.source_episode_ref,
                            "trigger": trigger,
                        },
                    )
                )
                db.commit()
                created += 1
            except IntegrityError:
                db.rollback()
                # Only a duplicate episode is benign; propagate all other integrity failures.
                if not db.scalar(
                    select(FollowupCase.id).where(
                        FollowupCase.clinic_id == clinic_id,
                        FollowupCase.source_episode_ref == candidate.source_episode_ref,
                    )
                ):
                    raise
    return created
