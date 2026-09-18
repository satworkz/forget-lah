"""Evidence-bound practical constraints; no generated clinical instructions."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from forget_lah.db import AuditEvent, Patient, utcnow
from forget_lah.runtime.models import PatientPreference


def preferences_for(db, case):
    patient = db.scalar(
        select(PatientPreference).where(
            PatientPreference.patient_id == case.patient_id,
            PatientPreference.clinic_id == case.clinic_id,
        )
    )
    from forget_lah.runtime.memory import effective_memory

    memory = effective_memory(db, case)
    return {
        **((patient.preferences or {}) if patient else {}),
        **{k: v for k, v in memory.items() if k in {"excluded_weekdays", "excluded_minutes"}},
    }


def effective_constraints(run, preferences):
    # An explicit per-visit request overrides saved preferences, including removal.
    barrier = run.checkpoint.get("barriers")
    if not barrier:
        return preferences
    result = {**preferences, **barrier}
    # An omitted/default empty list is not a retraction of a saved restriction.
    result["excluded_minutes"] = sorted(
        set(preferences.get("excluded_minutes", [])) | set(barrier.get("excluded_minutes", []))
    )
    return result


def matching_slots(slots, constraints):
    result = []
    for slot in slots:
        local = datetime.fromisoformat(slot["starts_at"]).astimezone(timezone(timedelta(hours=8)))
        minute = local.hour * 60 + local.minute
        if local.weekday() in constraints.get("excluded_weekdays", []):
            continue
        if minute in constraints.get("excluded_minutes", []):
            continue
        if slot.get("id") in constraints.get("rejected_slot_ids", []):
            continue
        if (
            constraints.get("earliest_minute") is not None
            and minute < constraints["earliest_minute"]
        ):
            continue
        if constraints.get("latest_minute") is not None and minute > constraints["latest_minute"]:
            continue
        if constraints.get("weekdays") and local.weekday() not in constraints["weekdays"]:
            continue
        if (
            constraints.get("requested_date")
            and local.date().isoformat() != constraints["requested_date"]
        ):
            continue
        if constraints.get("date_from") and local.date().isoformat() < constraints["date_from"]:
            continue
        if constraints.get("date_to") and local.date().isoformat() > constraints["date_to"]:
            continue
        result.append(slot)
    return result


def plan_summary(run, steps):
    barrier = run.checkpoint.get("barriers") or {}
    receipt = next(
        (
            s
            for s in reversed(steps)
            if s["tool_result"]
            and s["tool_result"]["tool_name"] == "record_simulated_confirmation"
            and s["tool_result"]["status"] == "succeeded"
        ),
        None,
    )
    instructions = next(
        (
            s
            for s in reversed(steps)
            if s["tool_result"]
            and s["tool_result"]["tool_name"] == "get_approved_instructions"
            and s["tool_result"]["status"] == "succeeded"
        ),
        None,
    )
    callback = run.checkpoint.get("callback") or {}
    prerequisite = next(
        (
            s
            for s in reversed(steps)
            if s["tool_result"]
            and s["tool_result"]["tool_name"] == "check_prerequisites"
            and s["tool_result"]["status"] == "succeeded"
        ),
        None,
    )
    return {
        "goal": "Find a suitable follow-up and identify unresolved preparation needs",
        "learned": barrier.get("evidence_quotes", []),
        "constraint_source": "This visit" if barrier else "Saved preferences or no restrictions",
        "next_action": (
            "Staff review"
            if run.status == "escalated"
            else "Patient reply"
            if run.status == "waiting"
            else "Review finished"
            if run.status == "completed"
            else run.active_role
        ),
        "attendance": "Source confirmed" if receipt else "Not confirmed by source",
        "instructions": "Retrieved from clinic" if instructions else "Not yet retrieved",
        "preparation": (
            "Staff review resolved; see outcome"
            if callback.get("status") == "resolved"
            and barrier.get("preparation_issue", "NONE") != "NONE"
            else "Patient reported an unresolved need"
            if barrier.get("preparation_issue", "NONE") != "NONE"
            else "No patient-reported issue recorded; readiness is not certified"
        ),
        "decision_step_id": barrier.get("step_id"),
        "source_prerequisites": (
            prerequisite["tool_result"]["data"].get("prerequisites", []) if prerequisite else []
        ),
    }


def remember_reported_exclusions(db, case, decision, step_id):
    # Operational memory from a saved simulator statement, not inferred consent.
    db.scalar(
        select(Patient)
        .where(Patient.id == case.patient_id, Patient.clinic_id == case.clinic_id)
        .with_for_update()
    )
    row = db.get(PatientPreference, (case.clinic_id, case.patient_id))
    if row is None:
        row = PatientPreference(
            clinic_id=case.clinic_id, patient_id=case.patient_id, preferences={}
        )
        db.add(row)
    row.preferences = {
        **(row.preferences or {}),
        "excluded_minutes": sorted(
            set((row.preferences or {}).get("excluded_minutes", []) + decision.excluded_minutes)
        ),
        "reported_concern": {
            "quote": "; ".join(decision.evidence_quotes),
            "reply_event_id": decision.reply_event_id,
            "decision_step_id": step_id,
            "source": "staff_operated_patient_simulator",
        },
        "updated_at": utcnow().isoformat(),
    }
    db.add(
        AuditEvent(
            clinic_id=case.clinic_id,
            case_id=case.id,
            event_type="PATIENT_CONCERN_RECORDED:" + step_id.replace("-", ""),
            details={
                "reply_event_id": decision.reply_event_id,
                "decision_step_id": step_id,
                "excluded_minutes": decision.excluded_minutes,
                "note": "Reported recurring scheduling restriction; not identity or consent verification",
            },
        )
    )
