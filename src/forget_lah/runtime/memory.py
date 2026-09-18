"""Typed, source-attributed operational memory. No model training or clinical inference."""

from sqlalchemy import select

from forget_lah.db import AuditEvent, Patient
from forget_lah.runtime.models import PatientMemory


def records_for(db, case):
    return list(
        db.scalars(
            select(PatientMemory)
            .where(
                PatientMemory.clinic_id == case.clinic_id,
                PatientMemory.patient_id == case.patient_id,
                PatientMemory.status.in_(["active", "pending"]),
                (PatientMemory.scope == "future")
                | (PatientMemory.case_id == getattr(case, "id", None)),
            )
            .order_by(PatientMemory.created_at, PatientMemory.id)
        )
    )


def memory_view(db, case):
    return [
        {
            "id": r.id,
            "key": r.key,
            "value": r.value["value"],
            "scope": r.scope,
            "status": r.status,
            "quote": r.quote,
            "message_id": r.message_id,
            "supersedes": r.supersedes,
            "created_at": r.created_at.isoformat(),
        }
        for r in records_for(db, case)
    ]


def effective_memory(db, case):
    rows = records_for(db, case)
    result = {}
    for scope in ("future", "visit"):
        for row in rows:
            if row.scope == scope and row.key != "other_concern":
                result[row.key] = row.value["value"]
    return result


def persist_needs(db, case, decision, step_id):
    db.scalar(
        select(Patient)
        .where(Patient.id == case.patient_id, Patient.clinic_id == case.clinic_id)
        .with_for_update()
    )
    for change in decision.updates:
        old = [r for r in records_for(db, case) if r.key == change.key and r.scope == change.scope]
        for row in old:
            row.status = "superseded" if change.operation == "set" else "retracted"
        value = change.value
        if change.key in {"excluded_minutes", "excluded_weekdays"} and change.operation == "set":
            value = sorted(set(int(v.strip()) for v in value.split(",")))
        if change.key == "excluded_languages" and change.operation == "set":
            value = change.value.split(",")
        row = PatientMemory(
            clinic_id=case.clinic_id,
            patient_id=case.patient_id,
            case_id=case.id,
            key=change.key,
            value={"value": value},
            scope=change.scope,
            status="retracted"
            if change.operation == "remove"
            else "pending"
            if change.key in {"arrival_support", "other_concern"} or value == "und"
            else "active",
            quote=change.quote,
            message_id=decision.reply_event_id,
            step_id=step_id,
            supersedes=old[-1].id if old else None,
        )
        db.add(row)
    db.flush()
    if decision.updates:
        db.add(
            AuditEvent(
                clinic_id=case.clinic_id,
                case_id=case.id,
                event_type=f"PATIENT_MEMORY_UPDATED:{step_id}",
                details={
                    "step_id": step_id,
                    "message_id": decision.reply_event_id,
                    "keys": [u.key for u in decision.updates],
                    "source": "staff_operated_simulator",
                },
            )
        )


def delivery_block(db, case, *, proactive=False, settings=None):
    memory = effective_memory(db, case)
    if proactive and memory.get("contact_permission") == "stopped":
        return "CONTACT_STOPPED"
    language = memory.get("preferred_language", "en")
    supported = {"en", "zh", "ms", "ta"} if settings and settings.translation_configured else {"en"}
    if language not in supported or language in memory.get("excluded_languages", []):
        return "LANGUAGE_SUPPORT_REQUIRED"
    return None


def language_ack(language):
    # Administrative acknowledgement only; no generated translation of doctor notes.
    return {
        "zh": "已记录您的语言偏好。我们已请诊所工作人员使用您偏好的语言协助您。预约尚未更改。",
        "ms": "Pilihan bahasa anda telah direkodkan. Kami telah meminta kakitangan klinik membantu dalam bahasa pilihan anda. Janji temu anda belum diubah.",
        "ta": "உங்கள் மொழி விருப்பம் பதிவு செய்யப்பட்டுள்ளது. நீங்கள் விரும்பும் மொழியில் உதவ மருத்துவமனை ஊழியர்களிடம் கோரியுள்ளோம். உங்கள் சந்திப்பு மாற்றப்படவில்லை.",
    }.get(language)


LANGUAGE_QUESTION = (
    "您希望使用哪种语言？ / Bahasa manakah yang anda pilih? / நீங்கள் எந்த மொழியை விரும்புகிறீர்கள்?"
)
