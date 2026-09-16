"""Read-only journey assembled from persisted evidence, never invented wire logs."""

from datetime import UTC

from fastapi import HTTPException
from sqlalchemy import select

from forget_lah.db import AuditEvent, Patient, Principal, utcnow
from forget_lah.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    SimulatedMessage,
    StaffHandoff,
)
from forget_lah.runtime.simulation import message_dict
from forget_lah.service_identity import AUTOMATION_PRINCIPAL_ID


def stamp(value):
    return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()


def decision_summary(step):
    decision = step.decision or {}
    kind = decision.get("step_type")
    role = step.role.title()
    if not kind:
        return "No validated decision is saved yet. Check the recorded outcome for pending work or an error."
    if (step.policy or {}).get("decision") == "DENY":
        return f"{role} proposed {kind}, but the gateway blocked it. The action was not executed."
    if step.status != "completed" or (step.policy or {}).get("decision") != "ALLOW":
        return f"{role} proposed {kind}. Execution is not recorded as complete; check the outcome below."
    if step.origin == "rule":
        if kind == "TOOL":
            if step.observation.get("application_rule", {}).get("name") in {
                "SIMULATED_SOURCE_RETRY",
                "EXPLICIT_SIMULATED_CONFIRMATION",
            }:
                return step.observation["application_rule"]["explanation"]
            return (
                "The worker requested the required initial clinic context through the gateway. "
                "No Claude call was needed. Check the actual source result below."
            )
        if kind == "WAIT":
            if step.observation.get("application_rule", {}).get("simulated_message_id"):
                return "The worker displayed a reminder in the patient simulator and saved a waiting checkpoint. No Claude call or real patient contact was needed."
            return (
                "The worker saved a waiting checkpoint for Engagement because demo outreach is disabled. "
                "No Claude call or patient message was made. A staff-entered demo reply resumes the review."
            )
        return (
            "An application rule escalated the staff-flagged concern. This did not require Claude."
        )
    descriptions = {
        "REPORT_SYMPTOMS": "Coordinator identified a current patient symptom report. The gateway checked quoted evidence; the worker acknowledged the report and created a clinical callback task. Attendance intention is separate from a source confirmation.",
        "INTERPRET_ATTENDANCE": "Engagement interpreted acceptance of the existing appointment; the source API must still record confirmation."
        if decision.get("confirmed")
        else "Engagement requested clarification about attendance for the existing appointment. No confirmation was recorded.",
        "INTERPRET_SELECTION": f"Engagement interpreted the reply as option {decision.get('option_number')}. The gateway checked the saved offer and reply; a separate source call must confirm the booking."
        if decision.get("option_number") is not None
        else "Engagement could not identify a clear choice and asked the patient to clarify. No booking was changed.",
        "TOOL": f"{role} requested {decision.get('tool_name')}. Check the tool result separately from permission.",
        "DELEGATE": f"{role} assigned a task to {decision.get('target', '').title()}. The worker runs that role next.",
        "RETURN": f"{role} returned {decision.get('reason_code', '').replace('_', ' ').lower()} with evidence references.",
        "WAIT": "The agent chose to wait. Saved progress allows the review to resume later.",
        "ESCALATE": "The agent requested staff help. A handoff still needs a named owner.",
        "COMPLETE": "The Coordinator proposed finishing automation after staff acceptance. This does not book an appointment.",
        "COMPLETE_SIMULATED_CONFIRMATION": "The Coordinator completed the simulated follow-up after checking the source confirmation receipt and displayed acknowledgement. No staff handoff was needed.",
    }
    if (
        decision.get("tool_name") == "send_simulated_options"
        and (step.tool_result or {}).get("status") == "succeeded"
    ):
        return "The Coordinator displayed source-owned slots and approved clinic notes, then saved a waiting checkpoint for the patient's explicit slot selection. Nothing is booked yet."
    return descriptions.get(kind, "Recorded agent action")


def case_journey(db, case, run_id=None):
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.case_id == case.id, AgentRun.clinic_id == case.clinic_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        )
    )
    run = next((r for r in runs if r.id == run_id), None) if run_id else next(iter(runs), None)
    if run_id and run is None:
        raise HTTPException(404, "Review not found for this case")
    entries = []

    def add(id, at, title, stages, summary, kind="event", **metadata):
        entries.append(
            {
                "id": id,
                "at": stamp(at),
                "title": title,
                "stages": stages,
                "summary": summary,
                "kind": kind,
                **metadata,
            }
        )

    def stage(component, title, input, output, basis="Saved evidence"):
        return dict(component=component, title=title, input=input, output=output, basis=basis)

    handoff_corrections = []
    for audit in db.scalars(
        select(AuditEvent)
        .where(AuditEvent.case_id == case.id, AuditEvent.clinic_id == case.clinic_id)
        .order_by(AuditEvent.created_at, AuditEvent.id)
    ):
        if audit.event_type == "HANDOFF_CLASSIFICATION_CORRECTED":
            if not run or audit.details.get("run_id") != run.id:
                continue
            handoff_corrections.append(audit.details)
            add(
                audit.id,
                audit.created_at,
                "Staff handoff classification corrected",
                [
                    stage(
                        "Application maintenance → PostgreSQL",
                        "Recorded correction to the current handoff",
                        {
                            "previous": audit.details.get("previous"),
                            "original_step_id": audit.details.get("original_step_id"),
                        },
                        {
                            "current": audit.details.get("current"),
                            "evidence_ids": audit.details.get("evidence_ids", []),
                        },
                        "Explicit maintenance correction; the original model decision and policy verdict are preserved",
                    )
                ],
                audit.details.get(
                    "note", "The current handoff was corrected; earlier evidence is unchanged."
                ),
                origin="rule",
            )
            continue
        detected = audit.event_type == "CASE_IDENTIFIED"
        add(
            audit.id,
            audit.created_at,
            audit.event_type.replace("_", " ").title(),
            [
                stage(
                    "Candidate detector → PostgreSQL"
                    if detected
                    else "Foundation worker → PostgreSQL",
                    "Case processing record",
                    audit.details.get(
                        "source_candidate",
                        {
                            "source_episode_ref": case.source_episode_ref,
                            "capture_note": "Original candidate payload was not retained for this older case",
                        },
                    )
                    if detected
                    else {"case_id": case.id},
                    {
                        "event_type": audit.event_type,
                        "origin": audit.decision_origin,
                        "details": audit.details,
                    },
                )
            ],
            "The detector saved this source-defined follow-up case. No model call was needed."
            if detected
            else "The foundation worker finished case processing. This record alone does not prove an agent review started; check the review creation event below.",
            origin="rule",
        )
    if run:
        automatic = run.started_by == AUTOMATION_PRINCIPAL_ID and run.start_key.startswith(
            "automatic:"
        )
        add(
            run.id,
            run.created_at,
            "Worker automatically queued this review" if automatic else "Staff started this review",
            [
                stage(
                    "Worker → PostgreSQL" if automatic else "Staff UI → FastAPI → PostgreSQL",
                    "Automatic review registration" if automatic else "Review created and queued",
                    {"expected_case_version": run.start_case_version},
                    {
                        "run_id": run.id,
                        "mode": run.mode,
                        "assigned_goal": run.goal,
                        "start_origin": "automatic" if automatic else "staff",
                        "started_by": "Clinic worker service" if automatic else "Signed-in staff",
                    },
                    "Saved run record; transport headers are not recorded",
                )
            ],
            "The worker registered this ready case under the clinic service identity. No staff click or Claude call was required; check the current status for progress or a configuration pause."
            if automatic
            else "Staff requested a review. FastAPI saved it for the worker; this API request is not a model decision.",
            origin="rule" if automatic else None,
        )
        for event in db.scalars(select(AgentEvent).where(AgentEvent.run_id == run.id)):
            add(
                event.id,
                event.created_at,
                "Staff: " + event.kind.replace("_", " "),
                [
                    stage(
                        "Staff UI → FastAPI → PostgreSQL",
                        "Staff event accepted",
                        {
                            "kind": event.kind,
                            "content": event.content,
                            "expected_case_version": event.expected_case_version,
                        },
                        {"event_id": event.id, "actor_id": event.actor_id},
                    )
                ],
                "Fictional reply: " + event.content
                if event.kind == "demo_reply"
                else "A signed-in staff member submitted this control event. See its saved input below.",
            )
        for step in db.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.sequence)
        ):
            role = step.role.title()
            model = (
                "Claude adapter"
                if step.origin == "model"
                else "Simulation"
                if step.origin == "mock"
                else "Application rule"
            )
            stages = [
                stage(
                    "PostgreSQL → Worker / Application rule"
                    if step.origin == "rule"
                    else f"PostgreSQL → Worker → {role} / {model}",
                    "Saved context for this application rule"
                    if step.origin == "rule"
                    else "Saved context for this decision",
                    {"step_id": step.id, "role": step.role, "origin": step.origin},
                    step.observation,
                    "Saved application context; no model request was needed."
                    if step.origin == "rule"
                    else "Saved observation; exact prompt and individual HTTP attempts are not retained. "
                    "A prepared context alone does not prove a model call was made; check the attempt count.",
                )
            ]
            if step.decision:
                stages.append(
                    stage(
                        "Worker / Application rule"
                        if step.origin == "rule"
                        else f"{role} / {model} → Worker",
                        "Rule-selected action" if step.origin == "rule" else "Proposed decision",
                        {"request_id": step.id},
                        step.decision,
                    )
                )
            if step.policy:
                stages.append(
                    stage(
                        "Worker → Policy gateway",
                        "Permission check before execution",
                        step.decision,
                        step.policy,
                    )
                )
            if step.tool_result:
                stages.append(
                    stage(
                        "Worker → Clinic adapter → Patient simulator → PostgreSQL"
                        if step.tool_result["tool_name"]
                        in {"send_simulated_acknowledgement", "send_simulated_options"}
                        else "Worker → Clinic adapter → Synthetic clinic API → Worker",
                        "Actual tool result",
                        {
                            "tool_name": step.tool_result["tool_name"],
                            "source_episode_ref": case.source_episode_ref,
                        },
                        step.tool_result,
                    )
                )
            action = (step.decision or {}).get("step_type")
            if (
                step.status == "completed"
                and (step.policy or {}).get("decision") == "ALLOW"
                and action != "TOOL"
            ):
                descriptions = {
                    "DELEGATE": f"Assigned work to {(step.decision or {}).get('target', 'specialist')}",
                    "RETURN": "Returned specialist finding and evidence to Coordinator",
                    "WAIT": "Saved waiting checkpoint",
                    "ESCALATE": "Requested staff ownership; this is not completion",
                    "COMPLETE": "Verified named staff acceptance; automation finished, staff task remains open",
                    "COMPLETE_SIMULATED_CONFIRMATION": "Verified source confirmation and simulated acknowledgement; follow-up finished",
                }
                stages.append(
                    stage(
                        "Worker → PostgreSQL",
                        descriptions.get(action, "Saved action"),
                        step.decision,
                        {"step_status": step.status},
                        "Explanation derived from the completed, permitted decision",
                    )
                )
            stages.append(
                stage(
                    "Worker → PostgreSQL",
                    "Recorded step outcome",
                    {"request_id": step.id},
                    {
                        "status": step.status,
                        "error_code": step.error_code,
                        "model_attempts": step.attempts,
                        "reported_input_tokens": step.input_tokens,
                        "reported_output_tokens": step.output_tokens,
                    },
                )
            )
            add(
                step.id,
                step.created_at,
                f"Decision {step.sequence} · {role}",
                stages,
                decision_summary(step),
                kind="decision",
                status=step.status,
                origin=step.origin,
                attempts=step.attempts,
                action=action,
                sequence=step.sequence,
            )
        for message in db.scalars(
            select(SimulatedMessage)
            .where(SimulatedMessage.run_id == run.id)
            .order_by(SimulatedMessage.created_at)
        ):
            add(
                message.id,
                message.created_at,
                "Simulated reminder displayed"
                if message.kind == "reminder"
                else "Simulated slots and clinic notes displayed"
                if message.kind == "options"
                else "Simulated acknowledgement displayed",
                [
                    stage(
                        "Worker → Patient simulator → PostgreSQL",
                        "Outgoing message saved and displayed locally",
                        {"run_id": run.id, **message.evidence},
                        message_dict(message),
                    )
                ],
                message.body,
                origin="rule",
            )
        handoff = db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
        if handoff:
            original = next(
                (c["previous"] for c in handoff_corrections if c.get("handoff_id") == handoff.id),
                {"reason_code": handoff.reason_code, "risk": handoff.risk},
            )
            add(
                handoff.id,
                handoff.created_at,
                "Staff handoff created",
                [
                    stage(
                        "Worker → PostgreSQL → Staff UI",
                        "Follow-up added to the staff queue",
                        {"run_id": run.id, "reason_code": original["reason_code"]},
                        {"handoff_id": handoff.id, "risk": original["risk"]},
                        "Saved handoff record; acceptance is a separate staff event",
                    )
                ],
                "The worker saved a staff task. Creating this task does not establish staff ownership.",
            )
    else:
        handoff = None
    entries.sort(key=lambda e: e["at"])
    owner = db.get(Principal, handoff.accepted_by) if handoff and handoff.accepted_by else None
    patient = db.get(Patient, case.patient_id)
    return {
        "case": {
            "id": case.id,
            "patient": patient.display_alias if patient else "Synthetic patient",
            "specialty": case.specialty,
            "trigger": case.trigger,
            "created_at": stamp(case.created_at),
            "source_episode_ref": case.source_episode_ref,
        },
        "runs": [
            {"id": r.id, "created_at": stamp(r.created_at), "status": r.status, "mode": r.mode}
            for r in runs
        ],
        "selected_run_id": run.id if run else None,
        "current": {
            "status": run.status if run else "No review started",
            "captured_at": stamp(utcnow()),
            "active_role": run.active_role if run else None,
            "steps_used": run.step_count if run else 0,
            "checkpoint": run.checkpoint if run else {},
            "handoff": {
                "id": handoff.id,
                "risk": handoff.risk,
                "accepted": bool(handoff.accepted_by),
                "owner": owner.email if owner else None,
                "accepted_at": stamp(handoff.accepted_at) if handoff.accepted_at else None,
                "staff_task_status": "resolved"
                if any(
                    run.checkpoint.get(k, {}).get("status") == "resolved"
                    for k in ("callback", "clinical_review")
                )
                else "open",
                "callback": run.checkpoint.get("callback"),
                "clinical_review": run.checkpoint.get("clinical_review"),
            }
            if handoff
            else None,
        },
        "entries": entries,
    }
