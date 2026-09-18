"""Resolve appointment identity before any agent or source write is allowed."""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from forget_lah.channel_models import ChannelInbox, ChannelOutbox, ChannelRoutingState
from forget_lah.db import AuditEvent, FollowupCase
from forget_lah.runtime.models import AgentRun, AgentStep
from forget_lah.runtime.responses import patient_message


def patient_cases(db, binding):
    anchor = db.get(FollowupCase, binding.case_id)
    if not anchor or anchor.clinic_id != binding.clinic_id:
        return []
    return list(
        db.scalars(
            select(FollowupCase)
            .where(
                FollowupCase.clinic_id == anchor.clinic_id,
                FollowupCase.patient_id == anchor.patient_id,
            )
            .order_by(FollowupCase.created_at, FollowupCase.id)
        )
    )


def conversation(db, binding):
    state = db.get(ChannelRoutingState, binding.id)
    if not state:
        state = ChannelRoutingState(id=binding.id, clinic_id=binding.clinic_id, data={})
        db.add(state)
        db.flush()
    return state


def channel_notice(db, case, incoming, text, kind="channel_notice"):
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.case_id == case.id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )
    if not run:
        return
    db.add(
        patient_message(
            run,
            clinic_id=case.clinic_id,
            case_id=case.id,
            run_id=run.id,
            event_id=incoming.sid,
            kind=kind,
            body=text,
            source_version="channel-routing-v1",
            evidence={"origin": "rule", "incoming_sid": incoming.sid},
        )
    )


def case_description(db, case):
    # Labels are explicitly historical context; the agent must refresh source evidence.
    date = None
    for step in db.scalars(
        select(AgentStep)
        .where(
            AgentStep.case_id == case.id,
            AgentStep.clinic_id == case.clinic_id,
            AgentStep.tool_result.is_not(None),
        )
        .order_by(AgentStep.created_at.desc(), AgentStep.sequence.desc())
    ):
        result = step.tool_result
        if (
            result.get("tool_name") == "read_followup_context"
            and result.get("status") == "succeeded"
        ):
            date = result.get("data", {}).get("scheduled_at")
            break
    if not date:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.case_id == case.id, AuditEvent.event_type == "CASE_IDENTIFIED"
            )
        )
        date = event.details.get("source_candidate", {}).get("scheduled_at") if event else None
    label = case.specialty.title() + " follow-up"
    if date:
        local = datetime.fromisoformat(date).astimezone(timezone(timedelta(hours=8)))
        label += " — last recorded " + local.strftime("%d %b %Y, %I:%M %p SGT")
    return label + f" — reference {case.id[:8]}"


def resolve_case(db, binding, incoming):
    """Return the resolved original reply; never treat a routing choice as booking consent."""
    cases = patient_cases(db, binding)
    by_id = {c.id: c for c in cases}
    if not cases:
        return None
    state = conversation(db, binding)
    context = db.get(ChannelRoutingState, incoming.sid)
    quoted = (context.data if context else {}).get("reply_to_sid")
    chosen = None
    if quoted:
        outbound = db.scalar(
            select(ChannelOutbox).where(
                ChannelOutbox.provider_sid == quoted,
                ChannelOutbox.clinic_id == binding.clinic_id,
                ChannelOutbox.recipient == binding.recipient,
            )
        )
        if (
            outbound
            and outbound.case_id in by_id
            and not outbound.message_id.startswith("routing:")
        ):
            # Routing notices themselves do not identify an appointment.
            from forget_lah.runtime.models import SimulatedMessage

            message = db.get(SimulatedMessage, outbound.message_id)
            if not message or message.kind != "channel_routing":
                chosen = outbound.case_id
    pending = (
        db.get(ChannelInbox, state.data.get("pending_sid"))
        if state.data.get("pending_sid")
        else None
    )
    if pending and pending.status != "awaiting_case":
        pending = None
    options = state.data.get("choices", [])
    if pending:
        # Identity selection only. Any request remains in the original signed message.
        match = re.fullmatch(
            r"\s*(?:(?:appointment|case|number|option)\s*)?(\d+)\s*[.!]?\s*", incoming.body, re.I
        )
        if not chosen and match and 1 <= int(match[1]) <= len(options):
            chosen = options[int(match[1]) - 1]
    if not chosen:
        tokens = [
            c.id
            for c in cases
            if re.search(r"\b" + re.escape(c.id[:8]) + r"\b", incoming.body, re.I)
        ]
        if len(tokens) == 1:
            chosen = tokens[0]
    if not chosen and not pending:
        if len(cases) == 1 and not quoted:
            chosen = cases[0].id
        elif not quoted:
            chosen = (
                context.data if context and "active_case_id" in context.data else state.data
            ).get("active_case_id")
    if chosen not in by_id:
        chosen = None
    if chosen:
        state.data = {
            "active_case_id": chosen,
            "focus_message_id": state.data.get("focus_message_id"),
        }
        if pending:
            pending.case_id, pending.status = chosen, "queued"
            incoming.status = "routing_selection"
            original_context = db.get(ChannelRoutingState, pending.sid)
            if original_context:
                selection_only = re.fullmatch(
                    r"\s*(?:(?:appointment|case|number|option)\s*)?(?:\d+|[0-9a-f]{8})\s*[.!]?\s*",
                    incoming.body,
                    re.I,
                )
                content = (
                    pending.body
                    if selection_only
                    else (pending.body + "\nPatient clarification: " + incoming.body)
                )
                if len(content) > 1000:
                    pending.status = "needs_staff"
                    channel_notice(
                        db,
                        by_id[chosen],
                        incoming,
                        "I've received your request and clarification. Clinic staff need to review the full message; your appointment has not been changed.",
                    )
                    return None
                original_context.data = {
                    **original_context.data,
                    "clarification_sid": incoming.sid,
                    "resolved_content": content,
                }
            return pending
        incoming.case_id = chosen
        return incoming
    # Keep the patient's request intact until appointment identity is established.
    if not pending:
        incoming.status = "awaiting_case"
        options = list(by_id)[-10:]
        state.data = {
            "pending_sid": incoming.sid,
            "choices": options,
            "focus_message_id": state.data.get("focus_message_id"),
        }
    else:
        incoming.status = "routing_unresolved"
    descriptions = [
        f"{i}. {case_description(db, by_id[ident])}"
        for i, ident in enumerate(options, 1)
        if ident in by_id
    ]
    channel_notice(
        db,
        by_id.get(binding.case_id, cases[0]),
        incoming,
        "I can help. Which appointment is this about?\n"
        + "\n".join(descriptions)
        + "\nReply with its number or reference, or use WhatsApp Reply on that appointment's message. "
        "This only selects the appointment; it does not confirm, cancel or change a booking.",
        "channel_routing",
    )
    return None
