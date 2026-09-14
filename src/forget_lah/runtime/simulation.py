"""Application evidence and local-only message delivery for synthetic testing."""

import re
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

from forget_lah.db import utcnow
from forget_lah.runtime.models import AgentDelegation, AgentEvent, AgentStep, SimulatedMessage
from forget_lah.source import DEMO_CLINIC_ID


def simulation_enabled(run):
    return (
        run.clinic_id == DEMO_CLINIC_ID and run.checkpoint.get("patient_simulator_enabled") is True
    )


def explicit_confirmation(text):
    """Conservative demo consent grammar; never treat a model finding as permission."""
    text = re.sub(r"\s+", " ", text.strip().lower()).rstrip(".! ")
    return bool(
        re.fullmatch(
            r"(?:yes[, ]+)?i (?:confirm(?: (?:my |the )?attendance)?|will attend)"
            r"(?:[,!. ]+(?:what should i bring\??|what do i need to bring\??))?",
            text,
        )
    )


def reply_evidence(db, run):
    event = run.checkpoint.get("latest_event", {})
    reply_id = event.get("reply_event_id", event.get("id"))
    reply = db.get(AgentEvent, reply_id) if reply_id else None
    return (
        reply
        if (
            reply
            and reply.run_id == run.id
            and reply.clinic_id == run.clinic_id
            and reply.kind == "demo_reply"
            and reply.content == event.get("content")
            and explicit_confirmation(reply.content)
        )
        else None
    )


def current_tools(db, run):
    return [
        s
        for s in db.scalars(
            select(AgentStep)
            .where(
                AgentStep.run_id == run.id,
                AgentStep.clinic_id == run.clinic_id,
                AgentStep.status == "completed",
            )
            .order_by(AgentStep.sequence)
        )
        if s.tool_result
        and s.tool_result.get("status") == "succeeded"
        and s.observation.get("latest_event", {}).get("id") == run.checkpoint["latest_event"]["id"]
    ]


def latest_tool(steps, name, role=None):
    return next(
        (
            s
            for s in reversed(steps)
            if s.tool_result["tool_name"] == name and (not role or s.role == role)
        ),
        None,
    )


def read_already_available(db, run, name):
    """Reuse successful reads within this event; specialists need their own evidence."""
    if name not in {"read_followup_context", "get_approved_instructions", "check_prerequisites"}:
        return False
    return any(
        s.tool_result["tool_name"] == name
        and (
            run.active_role == "coordinator"
            or (
                s.role == run.active_role and s.sequence > run.checkpoint.get("delegation_start", 0)
            )
        )
        for s in current_tools(db, run)
    )


def future_scheduled(data):
    try:
        date = datetime.fromisoformat(data.get("scheduled_at") or "")
        return (
            data.get("source_status") == "scheduled" and date.tzinfo is not None and date > utcnow()
        )
    except ValueError:
        return False


def simulation_evidence(db, run):
    result = {
        "enabled": simulation_enabled(run),
        "confirmation_authorized": False,
        "record_ready": False,
        "record_required": False,
        "ack_ready": False,
        "complete_evidence_ids": [],
    }
    if not result["enabled"]:
        return result
    reply = reply_evidence(db, run)
    result["confirmation_authorized"] = reply is not None
    steps = current_tools(db, run)
    context = latest_tool(steps, "read_followup_context", "engagement")
    receipt = latest_tool(steps, "record_simulated_confirmation", "engagement")
    result["record_required"] = bool(
        reply
        and context
        and context.tool_result["data"].get("can_simulate_confirmation")
        and context.tool_result["data"].get("episode_version")
        and future_scheduled(context.tool_result["data"])
    )
    result["record_ready"] = result["record_required"] and receipt is None
    reports = list(
        db.scalars(
            select(AgentDelegation).where(
                AgentDelegation.run_id == run.id,
                AgentDelegation.event_id == run.checkpoint["latest_event"]["id"],
                AgentDelegation.status == "returned",
            )
        )
    )
    engagement = next(
        (
            d
            for d in reports
            if d.target == "engagement" and d.result_reason_code == "PATIENT_CONFIRMED_ATTENDANCE"
        ),
        None,
    )
    preparation = next(
        (
            d
            for d in reports
            if d.target == "preparation" and d.result_reason_code == "SPECIALIST_REVIEW_FINISHED"
        ),
        None,
    )
    instructions = latest_tool(steps, "get_approved_instructions", "preparation")
    prerequisites = latest_tool(steps, "check_prerequisites", "preparation")
    ack = latest_tool(steps, "send_simulated_acknowledgement", "coordinator")
    ready = bool(
        reply
        and receipt
        and receipt.tool_result["data"].get("receipt_id") == reply.id
        and engagement
        and receipt.id in engagement.evidence_ids
        and preparation
        and instructions
        and instructions.id in preparation.evidence_ids
        and prerequisites
        and prerequisites.id in preparation.evidence_ids
        and prerequisites.tool_result["data"].get("prerequisites") == ["NOT_APPLICABLE"]
        and instructions.tool_result["source_version"] == receipt.tool_result["source_version"]
        and prerequisites.tool_result["source_version"] == receipt.tool_result["source_version"]
    )
    result["ack_ready"] = ready and ack is None
    if ready and ack:
        message = db.get(SimulatedMessage, ack.tool_result["data"].get("message_id"))
        if (
            message
            and message.run_id == run.id
            and message.event_id == reply.id
            and message.kind == "acknowledgement"
            and message.evidence.get("confirmation_step_id") == receipt.id
        ):
            result["complete_evidence_ids"] = [receipt.id, ack.id]
    return result


def appointment_time(value):
    return (
        datetime.fromisoformat(value)
        .astimezone(timezone(timedelta(hours=8)))
        .strftime("%d %B %Y at %I:%M %p SGT")
    )


def save_reminder(db, run, source):
    existing = db.scalar(
        select(SimulatedMessage).where(
            SimulatedMessage.run_id == run.id, SimulatedMessage.kind == "reminder"
        )
    )
    if existing:
        return existing
    data = source["result"]["data"]
    if data["source_status"] == "scheduled" and data.get("scheduled_at"):
        body = f"Your clinic follow-up is scheduled for {appointment_time(data['scheduled_at'])}. Please confirm whether you will attend."
    elif data["source_status"] == "no_show":
        body = "Your clinic record shows a missed appointment. Please reply so we can help arrange follow-up with the clinic."
    else:
        body = "Your clinic record shows a routine follow-up is due. Please reply so we can help you arrange it with the clinic."
    row = SimulatedMessage(
        clinic_id=run.clinic_id,
        case_id=run.case_id,
        run_id=run.id,
        event_id=run.checkpoint["latest_event"]["id"],
        kind="reminder",
        body=body,
        source_version=source["result"]["source_version"],
        evidence={"source_step_id": source["id"]},
    )
    db.add(row)
    db.flush()
    return row


def save_acknowledgement(db, run):
    reply = reply_evidence(db, run)
    existing = db.scalar(
        select(SimulatedMessage).where(
            SimulatedMessage.run_id == run.id,
            SimulatedMessage.event_id == reply.id,
            SimulatedMessage.kind == "acknowledgement",
        )
    )
    if existing:
        return existing
    steps = current_tools(db, run)
    receipt = latest_tool(steps, "record_simulated_confirmation", "engagement")
    instructions = latest_tool(steps, "get_approved_instructions", "preparation")
    body = f"Thank you. We've recorded your confirmation for {appointment_time(receipt.tool_result['data']['scheduled_at'])}."
    notes = instructions.tool_result["data"]["instructions"]
    if notes:
        body += "\n\nClinic instructions:\n" + "\n".join(n["approved_text"] for n in notes)
    row = SimulatedMessage(
        clinic_id=run.clinic_id,
        case_id=run.case_id,
        run_id=run.id,
        event_id=reply.id,
        kind="acknowledgement",
        body=body,
        source_version=receipt.tool_result["source_version"],
        evidence={
            "confirmation_step_id": receipt.id,
            "instruction_step_id": instructions.id,
            "instructions": [
                {"instruction_id": n["instruction_id"], "version": n["version"]} for n in notes
            ],
        },
    )
    db.add(row)
    db.flush()
    return row


def message_dict(row):
    at = row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
    return {
        "id": row.id,
        "kind": row.kind,
        "body": row.body,
        "created_at": at.isoformat(),
        "source_version": row.source_version,
        "evidence": row.evidence,
        "channel": "patient_simulator",
        "delivery_status": "displayed_in_simulator",
        "synthetic": True,
    }
