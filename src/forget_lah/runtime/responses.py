"""One response per patient turn, composed from evidence-backed application parts."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from forget_lah.runtime.models import AgentStep, SimulatedMessage


def appointment_facts(db, run):
    rows = db.scalars(
        select(AgentStep)
        .where(
            AgentStep.run_id == run.id,
            AgentStep.clinic_id == run.clinic_id,
            AgentStep.status == "completed",
            AgentStep.tool_result.is_not(None),
        )
        .order_by(AgentStep.sequence.desc())
    )
    for row in rows:
        result = row.tool_result
        if (
            result.get("tool_name") != "read_followup_context"
            or result.get("status") != "succeeded"
        ):
            continue
        data = result["data"]
        if data.get("source_status") != "scheduled" or not data.get("scheduled_at"):
            return None
        local = datetime.fromisoformat(data["scheduled_at"]).astimezone(
            timezone(timedelta(hours=8))
        )
        return {
            "scheduled_at": data["scheduled_at"],
            "weekday": local.strftime("%A"),
            "local_display": local.strftime("%A, %d %B %Y at %I:%M %p SGT"),
            "source_step_id": row.id,
        }
    return None


def defer_response(run, event_id, key, text, step_id):
    pending = run.checkpoint.get("response_parts", {})
    if pending.get("event_id") != event_id:
        pending = {"event_id": event_id, "parts": {}}
    parts = {**pending["parts"], key: {"text": text, "step_id": step_id}}
    run.checkpoint = {**run.checkpoint, "response_parts": {"event_id": event_id, "parts": parts}}


def patient_message(run, **fields):
    pending = run.checkpoint.get("response_parts", {})
    if pending.get("event_id") == fields.get("event_id"):
        parts = pending.get("parts", {})
        ordered = [parts[k] for k in ("empathy", "memory") if k in parts]
        fields["body"] = "\n\n".join([p["text"] for p in ordered] + [fields["body"]])
        fields["evidence"] = {**fields.get("evidence", {}), "response_parts": ordered}
        run.checkpoint = {**run.checkpoint, "response_parts": {}}
    return SimulatedMessage(**fields)


def memory_ack(updates):
    parts = []
    for change in updates:
        if change.operation == "remove":
            parts.append("I've updated your saved preference.")
        elif change.key == "excluded_weekdays":
            days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            names = ", ".join(days[int(v)] for v in change.value.split(","))
            parts.append(f"I've noted that {names} appointments don't work for you.")
        elif change.key == "excluded_minutes":
            times = ", ".join(
                f"{int(v) // 60:02d}:{int(v) % 60:02d}" for v in change.value.split(",")
            )
            parts.append(f"I've noted that {times} SGT doesn't work for you.")
        else:
            parts.append("I've noted your concern.")
    if parts:
        parts.append(
            "I'll remember this for future follow-ups."
            if any(u.scope == "future" for u in updates)
            else "This applies to this visit only."
        )
    return " ".join(dict.fromkeys(parts))
