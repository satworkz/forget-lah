"""Read-only case audit projection over existing evidence and new intake events."""

from datetime import UTC

from fastapi import HTTPException, Request
from sqlalchemy import select

from forget_lah.channel_models import ChannelOutbox
from forget_lah.db import (
    AuditEvent,
    BridgeIntakeBatch,
    BridgeIntakeRecord,
    FollowupCase,
    Patient,
    SecurityEvent,
)
from forget_lah.runtime.models import AgentEvent, AgentStep, StaffAppointmentChange
from forget_lah.security import safe_details


def install_audit_routes(app, factory, authorise):
    @app.get("/api/security/events")
    def security_events(request: Request):
        with factory() as db:
            _, _, clinics = authorise(db, request)
            return [
                {
                    "id": e.id,
                    "actor": e.actor_id,
                    "action": e.action,
                    "decision": e.decision,
                    "details": e.details,
                    "timestamp": e.created_at.isoformat(),
                }
                for e in db.scalars(
                    select(SecurityEvent)
                    .where(SecurityEvent.clinic_id.in_(clinics))
                    .order_by(SecurityEvent.created_at.desc())
                    .limit(100)
                )
            ]

    @app.get("/api/cases/{case_id}/audit")
    def case_audit(case_id: str, request: Request):
        with factory() as db:
            _, _, clinics = authorise(db, request)
            case = db.scalar(
                select(FollowupCase).where(
                    FollowupCase.id == case_id, FollowupCase.clinic_id.in_(clinics)
                )
            )
            if not case:
                raise HTTPException(404, "Case not found")
            output = []

            def add(row, actor, action, source, decision, evidence):
                timestamp = row.created_at
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=UTC)
                output.append(
                    {
                        "id": row.id,
                        "actor": actor or "Not recorded",
                        "action": action,
                        "source": source,
                        "timestamp": timestamp.isoformat(),
                        "decision": decision,
                        "evidence": safe_details(evidence),
                    }
                )

            def scoped(model):
                return db.scalars(
                    select(model)
                    .where(model.clinic_id == case.clinic_id, model.case_id == case.id)
                    .order_by(model.created_at.desc())
                    .limit(200)
                )

            for e in scoped(AuditEvent):
                add(e, "Application", e.event_type, e.decision_origin, "Recorded", e.details)
            for e in scoped(AgentEvent):
                add(
                    e,
                    e.actor_id,
                    e.kind,
                    "staff / patient event",
                    "Accepted by application",
                    {"content": e.content, "old_case_version": e.expected_case_version},
                )
            for e in scoped(AgentStep):
                add(
                    e,
                    e.role,
                    (e.decision or {}).get("tool_name")
                    or (e.decision or {}).get("step_type", "agent_step"),
                    e.origin,
                    e.policy or {"status": e.status},
                    {"result": e.tool_result, "error": e.error_code},
                )
            for e in scoped(StaffAppointmentChange):
                add(
                    e,
                    e.actor_id,
                    "staff_appointment_change",
                    "bridge" if case.source_episode_ref.startswith("bridge:") else "clinic_api",
                    e.status,
                    {"receipt": e.receipt},
                )
            for e in scoped(ChannelOutbox):
                add(
                    e,
                    "Channel worker",
                    "notification",
                    "whatsapp_test",
                    e.status,
                    {"provider_receipt": e.provider_sid, "error": e.error_code},
                )
            # Only this patient's rows: a batch may contain unrelated patients.
            records = list(
                db.scalars(
                    select(BridgeIntakeRecord)
                    .where(
                        BridgeIntakeRecord.clinic_id == case.clinic_id,
                        BridgeIntakeRecord.source_episode_ref == case.source_episode_ref,
                        BridgeIntakeRecord.patient_id == case.patient_id,
                    )
                    .order_by(BridgeIntakeRecord.id.desc())
                    .limit(200)
                )
            )
            batch_ids = {r.batch_id for r in records}
            record_ids = {r.id for r in records}
            for batch_id in batch_ids:
                b = db.scalar(
                    select(BridgeIntakeBatch).where(
                        BridgeIntakeBatch.id == batch_id,
                        BridgeIntakeBatch.clinic_id == case.clinic_id,
                    )
                )
                if b:
                    add(
                        b,
                        b.uploaded_by,
                        "bridge_provenance",
                        "bridge_upload",
                        b.status,
                        {
                            "filename": b.filename,
                            "sha256": b.sha256,
                            "approved_at": b.approved_at.isoformat() if b.approved_at else None,
                        },
                    )
            for e in db.scalars(
                select(SecurityEvent)
                .where(
                    SecurityEvent.clinic_id == case.clinic_id,
                    SecurityEvent.resource_id.in_([case.id, *batch_ids]),
                )
                .order_by(SecurityEvent.created_at.desc())
                .limit(200)
            ):
                if e.action == "bridge_review" and e.details.get("record_id") not in record_ids:
                    continue
                add(e, e.actor_id, e.action, "application", e.decision, e.details)
            patient = db.scalar(
                select(Patient).where(
                    Patient.id == case.patient_id, Patient.clinic_id == case.clinic_id
                )
            )
            return {
                "patient": patient.display_alias if patient else "Patient",
                "events": sorted(output, key=lambda e: e["timestamp"], reverse=True),
                "limit_per_source": 200,
            }
