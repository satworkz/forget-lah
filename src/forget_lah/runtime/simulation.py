"""Application evidence and local-only message delivery for synthetic testing."""

import re
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

from forget_lah.db import FollowupCase, utcnow
from forget_lah.runtime.adaptation import effective_constraints, matching_slots, preferences_for
from forget_lah.runtime.models import AgentDelegation, AgentEvent, AgentStep, SimulatedMessage
from forget_lah.runtime.questions import question_response
from forget_lah.runtime.responses import patient_message
from forget_lah.runtime.scheduling import compatible, instruction_gate_clear
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
            r"(?:yes[, ]+)?i (?:confirm(?: (?:my |the )?attendance)?|(?:will )?attend)"
            r"(?:[,!. ]+(?:what should i bring|what do i need to bring|"
            r"do i have (?:a |any )?blood tests?(?: (?:on (?:the|that|the same|my appointment) day|that day))?|"
            r"is (?:a |any )?blood test scheduled(?: (?:on (?:the|that|the same|my appointment) day|that day))?)\??)?",
            text,
        )
    )


def saved_reply(db, run):
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
        )
        else None
    )



def pending_instruction_question(db, run):
    """Return the latest unresolved doctor-instruction question preceding this patient reply."""
    reply = saved_reply(db, run)
    if not reply:
        return None
    resolved = {
        (step.decision or {}).get("question_message_id")
        for step in db.scalars(
            select(AgentStep).where(
                AgentStep.run_id == run.id,
                AgentStep.clinic_id == run.clinic_id,
                AgentStep.status == "completed",
            )
        )
        if (step.decision or {}).get("step_type") == "INTERPRET_INSTRUCTION_CHECK"
    }
    for message in db.scalars(
        select(SimulatedMessage)
        .where(
            SimulatedMessage.run_id == run.id,
            SimulatedMessage.clinic_id == run.clinic_id,
            SimulatedMessage.kind == "doctor_instruction_check",
        )
        .order_by(SimulatedMessage.created_at.desc())
    ):
        if message.id in resolved or message.event_id == reply.id:
            continue
        return message
    return None


def save_instruction_question(
    db,
    run,
    requirement,
    review,
    *,
    source_version,
    resolutions=None,
    resume_appointment_intent="UNSPECIFIED",
    attempt=1,
):
    reply = saved_reply(db, run)
    existing = db.scalar(
        select(SimulatedMessage).where(
            SimulatedMessage.run_id == run.id,
            SimulatedMessage.event_id == reply.id,
            SimulatedMessage.kind == "doctor_instruction_check",
        )
    )
    if existing:
        return existing
    body = requirement["patient_question"].strip()
    if not body.endswith("?"):
        body += "?"
    body += " No appointment changes will be made until this is resolved."
    row = patient_message(
        run,
        clinic_id=run.clinic_id,
        case_id=run.case_id,
        run_id=run.id,
        event_id=reply.id,
        kind="doctor_instruction_check",
        body=body,
        source_version=source_version,
        evidence={
            "requirement": requirement,
            "scheduling_review": review,
            "resolutions": resolutions or [],
            "resume_appointment_intent": resume_appointment_intent,
            "attempt": attempt,
        },
    )
    db.add(row)
    db.flush()
    return row


def current_instruction_gate(db, run, context_step, choice=None):
    # A selected option is already bound to the exact Preparation review that
    # produced the offer. booking_choice() verifies that review, any patient
    # checks, and slot compatibility. The record gate separately verifies the
    # episode version and that the selected slot is still in the fresh source.
    if choice is not None:
        return bool(choice.get("scheduling_reviewed"))

    review_step_id = run.checkpoint.get("question_review_step_id")
    review_step = db.get(AgentStep, review_step_id) if review_step_id else None
    if (
        not review_step
        or review_step.run_id != run.id
        or review_step.clinic_id != run.clinic_id
        or review_step.role != "preparation"
        or review_step.status != "completed"
        or (review_step.policy or {}).get("decision") != "ALLOW"
    ):
        return False
    review = (review_step.decision or {}).get("scheduling_review")
    instruction_source = None
    for evidence_id in (review_step.decision or {}).get("evidence_ids", []):
        evidence = db.get(AgentStep, evidence_id)
        if (
            evidence
            and evidence.tool_result
            and evidence.tool_result.get("tool_name") == "get_approved_instructions"
        ):
            instruction_source = evidence.tool_result.get("source_version")
            break
    if not instruction_source or instruction_source != context_step.tool_result.get("source_version"):
        return False
    resolutions = run.checkpoint.get("instruction_check_resolutions", [])
    if not instruction_gate_clear(review, resolutions):
        return False
    target = choice["slot"] if choice else {"starts_at": context_step.tool_result["data"].get("scheduled_at")}
    if target.get("starts_at") and not compatible([target], review):
        return False
    return True

def latest_selection_offer(db, run):
    reply = saved_reply(db, run)
    if not reply:
        return None
    offer = db.scalar(
        select(SimulatedMessage)
        .where(
            SimulatedMessage.run_id == run.id,
            SimulatedMessage.clinic_id == run.clinic_id,
            SimulatedMessage.kind == "options",
        )
        .order_by(SimulatedMessage.created_at.desc())
    )
    if not offer or offer.event_id == reply.id or offer.created_at > reply.created_at:
        return None
    return offer


def booking_choice(db, run):
    """Use the gateway-validated agent interpretation, bound to the actual reply/offer."""
    reply = saved_reply(db, run)
    offer = latest_selection_offer(db, run)
    selection = run.checkpoint.get("selection", {})
    if (
        not reply
        or not offer
        or selection.get("reply_event_id") != reply.id
        or selection.get("offer_id") != offer.id
    ):
        return None
    proof = db.get(AgentStep, selection.get("step_id")) if selection.get("step_id") else None
    if (
        not proof
        or proof.run_id != run.id
        or proof.clinic_id != run.clinic_id
        or proof.role != "engagement"
        or proof.status != "completed"
        or not proof.policy
        or proof.policy.get("decision") != "ALLOW"
        or (proof.decision or {}).get("step_type") != "INTERPRET_SELECTION"
    ):
        return None
    number = proof.decision.get("option_number")
    if number is None:
        return None
    options = offer.evidence.get("slots", [])
    index = number - 1
    if index >= len(options):
        return None
    review_id = offer.evidence.get("scheduling_review_step_id")
    review_step = db.get(AgentStep, review_id) if review_id else None
    review = (review_step.decision or {}).get("scheduling_review") if review_step else None
    resolutions = offer.evidence.get("instruction_check_resolutions", [])
    reviewed = bool(
        review_step
        and review_step.run_id == run.id
        and review_step.clinic_id == run.clinic_id
        and review_step.role == "preparation"
        and review_step.status == "completed"
        and (review_step.policy or {}).get("decision") == "ALLOW"
        and instruction_gate_clear(review, resolutions)
        and compatible([options[index]], review)
    )
    return {
        "scheduling_reviewed": reviewed,
        "slot": options[index],
        "episode_version": offer.evidence["episode_version"],
        "offer_id": offer.id,
        "unsupported_question": proof.decision.get("unsupported_question", "NONE"),
        "selection_step_id": proof.id,
        "instruction_check_resolutions": resolutions,
    }


def unsupported_question_reply(topic):
    return {
        "WEATHER": "Sorry, I can’t check the weather forecast here.",
        "PARKING": "Sorry, I can’t check parking availability at that time.",
        "OTHER_NON_CLINICAL": "Sorry, I can’t check that information here.",
    }.get(topic, "")


def attendance_interpretation(db, run):
    reply = saved_reply(db, run)
    binding = run.checkpoint.get("attendance", {})
    if not reply or binding.get("reply_event_id") != reply.id:
        return None
    proof = db.get(AgentStep, binding.get("step_id")) if binding.get("step_id") else None
    if (
        not proof
        or proof.run_id != run.id
        or proof.clinic_id != run.clinic_id
        or proof.role != "engagement"
        or proof.status != "completed"
        or (proof.policy or {}).get("decision") != "ALLOW"
        or (proof.decision or {}).get("step_type") != "INTERPRET_ATTENDANCE"
        or proof.decision.get("reply_event_id") != reply.id
    ):
        return None
    return proof


def reply_evidence(db, run):
    reply = saved_reply(db, run)
    interpretation = attendance_interpretation(db, run)
    resumed_confirmation = bool(
        reply
        and run.checkpoint.get("instruction_check_processed") == reply.id
        and run.checkpoint.get("instruction_check_resume_intent") == "CONFIRM"
    )
    return (
        reply
        if reply
        and (
            explicit_confirmation(reply.content)
            or booking_choice(db, run)
            or resumed_confirmation
            or (interpretation and interpretation.decision.get("confirmed") is True)
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
        "booking_authorized": False,
        "options_ready": False,
        "recall_options_available": False,
        "selection_needs_refresh": False,
        "has_offer": False,
        "instruction_check": None,
    }
    if not result["enabled"]:
        return result
    pending_check = pending_instruction_question(db, run)
    if pending_check:
        requirement = pending_check.evidence.get("requirement", {})
        result["instruction_check"] = {
            "question_message_id": pending_check.id,
            "reply_event_id": saved_reply(db, run).id,
            "question": pending_check.body,
            "condition_quote": requirement.get("condition_quote"),
            "if_not_met": requirement.get("if_not_met"),
            "attempt": pending_check.evidence.get("attempt", 1),
        }
    reply = reply_evidence(db, run)
    result["confirmation_authorized"] = reply is not None
    steps = current_tools(db, run)
    context = latest_tool(steps, "read_followup_context", "engagement")
    receipt = latest_tool(steps, "record_simulated_confirmation", "engagement")
    choice = booking_choice(db, run)
    interpreted = attendance_interpretation(db, run)
    result["unsupported_question"] = (
        interpreted.decision.get("unsupported_question", "NONE")
        if interpreted
        else (choice or {}).get("unsupported_question", "NONE")
    )
    offer = latest_selection_offer(db, run)
    result["has_offer"] = offer is not None
    patient_reply = saved_reply(db, run)
    barriers = run.checkpoint.get("barriers", {})
    refining_search = bool(
        patient_reply
        and run.checkpoint.get("appointment_intent") == "CHANGE"
        and barriers.get("reply_event_id") == patient_reply.id
        and barriers.get("next_action") == "SEARCH_SLOTS"
    )
    reminder = db.scalar(
        select(SimulatedMessage).where(
            SimulatedMessage.run_id == run.id,
            SimulatedMessage.kind == "reminder",
        )
    )
    reminder_source = (
        db.get(AgentStep, reminder.evidence.get("source_step_id")) if reminder else None
    )
    if (
        not offer
        and not refining_search
        and patient_reply
        and not reply
        and context
        and context.sequence > run.checkpoint.get("delegation_start", 0)
        and run.active_role == "engagement"
        and future_scheduled(context.tool_result["data"])
        and (
            run.checkpoint.get("reopened_from_run_id")
            or (
                reminder_source
                and reminder_source.tool_result["data"].get("scheduled_at")
                == context.tool_result["data"]["scheduled_at"]
            )
        )
    ):
        result["attendance_review"] = {
            "reply_event_id": patient_reply.id,
            "source_step_id": context.id,
            "appointment": appointment_time(context.tool_result["data"]["scheduled_at"]),
        }
    if (
        offer
        and not refining_search
        and context
        and context.sequence > run.checkpoint.get("delegation_start", 0)
        and not choice
        and run.active_role == "engagement"
    ):
        result["selection_offer"] = {
            "offer_id": offer.id,
            "reply_event_id": saved_reply(db, run).id,
            "options": [
                {"number": i, "time": appointment_time(s["starts_at"]), "doctor": s["doctor"]}
                for i, s in enumerate(offer.evidence.get("slots", []), 1)
            ],
        }
    result["booking_authorized"] = bool(choice and choice.get("scheduling_reviewed"))
    instruction_gate = bool(context and current_instruction_gate(db, run, context, choice))
    result["record_required"] = bool(
        reply
        and context
        and instruction_gate
        and context.tool_result["data"].get("can_simulate_confirmation")
        and context.tool_result["data"].get("episode_version")
        and (
            (not choice and future_scheduled(context.tool_result["data"]))
            or (
                choice
                and choice["scheduling_reviewed"]
                and (
                    context.tool_result["data"].get("can_simulate_booking")
                    or (
                        context.tool_result["data"].get("can_simulate_rescheduling")
                        and future_scheduled(context.tool_result["data"])
                    )
                )
                and context.tool_result["data"].get("episode_version") == choice["episode_version"]
                and choice["slot"] in context.tool_result["data"].get("available_slots", [])
            )
        )
    )
    attendance = attendance_interpretation(db, run)
    if attendance and context:
        original = db.get(AgentStep, attendance.decision["source_step_id"])
        if (
            not original
            or original.tool_result["source_version"] != context.tool_result["source_version"]
        ):
            result["record_required"] = False
    result["record_ready"] = result["record_required"] and receipt is None
    if run.checkpoint.get("barriers", {}).get("preparation_issue", "NONE") != "NONE":
        result["record_ready"] = result["record_required"] = False
    result["selection_needs_refresh"] = bool(
        choice
        and context
        and not receipt
        and (
            not choice["scheduling_reviewed"]
            or choice["slot"] not in context.tool_result["data"].get("available_slots", [])
            or choice["episode_version"] != context.tool_result["data"].get("episode_version")
        )
    )
    if result["selection_needs_refresh"]:
        result["booking_authorized"] = result["confirmation_authorized"] = False
    reports = list(
        db.scalars(
            select(AgentDelegation).where(
                AgentDelegation.run_id == run.id,
                AgentDelegation.event_id == run.checkpoint["latest_event"]["id"],
                AgentDelegation.status == "returned",
            )
        )
    )
    instructions = latest_tool(steps, "get_approved_instructions", "preparation")
    prerequisites = latest_tool(steps, "check_prerequisites", "preparation")
    # A guarded write can introduce more than one specialist return in the same
    # patient turn: Engagement interprets the choice, Preparation clears the
    # doctor-note gate, Engagement performs the write, and Preparation refreshes
    # against the new source version. Select the reports that actually contain
    # the current evidence rather than relying on unspecified SQL row order.
    engagement = next(
        (
            d
            for d in reports
            if d.target == "engagement"
            and d.result_reason_code == "PATIENT_CONFIRMED_ATTENDANCE"
            and (not receipt or receipt.id in d.evidence_ids)
        ),
        None,
    )
    preparation = next(
        (
            d
            for d in reports
            if d.target == "preparation"
            and d.result_reason_code == "SPECIALIST_REVIEW_FINISHED"
            and instructions
            and instructions.id in d.evidence_ids
            and prerequisites
            and prerequisites.id in d.evidence_ids
        ),
        None,
    )
    ack = latest_tool(steps, "send_simulated_acknowledgement", "coordinator")
    any_context = latest_tool(steps, "read_followup_context")
    result["recall_options_available"] = bool(
        any_context and saved_reply(db, run) and (not choice or result["selection_needs_refresh"])
    )
    date_report = next(
        (
            d
            for d in reports
            if d.target == "engagement"
            and d.result_reason_code == "PATIENT_REQUESTED_ALTERNATIVE_DATE"
        ),
        None,
    )
    result["options_ready"] = bool(
        result["recall_options_available"]
        and date_report
        and run.checkpoint.get("scheduling_review") is not None
        and preparation
        and instructions
        and prerequisites
        and instructions.id in preparation.evidence_ids
        and prerequisites.id in preparation.evidence_ids
        and context
        and context.id in date_report.evidence_ids
        and prerequisites.tool_result["data"].get("prerequisites") == ["NOT_APPLICABLE"]
        and instructions.tool_result["source_version"] == any_context.tool_result["source_version"]
        and prerequisites.tool_result["source_version"] == any_context.tool_result["source_version"]
        and not latest_tool(steps, "send_simulated_options")
    )
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
            and not run.checkpoint.get("callback")
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
    from forget_lah.runtime.memory import effective_memory

    case = db.get(FollowupCase, run.case_id)
    memory = effective_memory(db, case)
    if memory.get("arrival_support") == "needs_clarification":
        body += " You previously mentioned difficulty arriving on time. Would a different appointment time help?"
    preferences = preferences_for(db, case)
    if data.get("scheduled_at") and not matching_slots(
        [{"id": "existing", "starts_at": data["scheduled_at"]}], preferences
    ):
        body = f"Your clinic still has an appointment scheduled for {appointment_time(data['scheduled_at'])}, which conflicts with your saved timing preference. Would you like help finding another time? Your appointment has not been changed."
    row = patient_message(
        run,
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
    if receipt.tool_result["data"].get("booking_slot_id"):
        body = f"Your follow-up is booked in the clinic simulator for {appointment_time(receipt.tool_result['data']['scheduled_at'])}. Thank you for confirming."
        context = latest_tool(steps, "read_followup_context", "engagement")
        if context and context.tool_result["data"].get("source_status") == "scheduled":
            body = f"Your appointment has been moved in the clinic simulator from {appointment_time(context.tool_result['data']['scheduled_at'])} to {appointment_time(receipt.tool_result['data']['scheduled_at'])}. Thank you for confirming."
    notes = instructions.tool_result["data"]["instructions"]
    quoted_answers = {
        (a.get("instruction_id"), a.get("quote"))
        for a in run.checkpoint.get("question_answers", [])
        if a.get("outcome") in {"ANSWERED", "GUIDANCE"}
    }
    remaining_notes = [
        n
        for n in notes
        if not any(
            ident == n["instruction_id"] and quote and quote in n["approved_text"]
            for ident, quote in quoted_answers
        )
    ]
    if remaining_notes:
        body += "\n\nClinic instructions:\n" + "\n".join(
            n["approved_text"] for n in remaining_notes
        )
    selection = booking_choice(db, run) or {}
    attendance = attendance_interpretation(db, run)
    unsupported = selection.get("unsupported_question", "NONE")
    if attendance:
        unsupported = attendance.decision.get("unsupported_question", "NONE")
    if not run.checkpoint.get("patient_questions") and (
        limitation := unsupported_question_reply(unsupported)
    ):
        body += "\n\n" + limitation
    blood_test_question = not run.checkpoint.get("patient_questions") and bool(
        re.search(r"\bblood tests?\b", reply.content, re.IGNORECASE)
    )
    if blood_test_question:
        if not notes:
            body += "\n\nNo clinic-approved instructions are recorded for this visit."
        body += (
            "\n\nI've sent your blood-test question to the clinic team and requested a callback. "
            "Your attendance confirmation has been recorded separately."
        )
        # Free-text notes are not structured proof that this specific question is answered.
        # Persist the request atomically with the acknowledgement; staff must resolve it.
        run.checkpoint = {
            **run.checkpoint,
            "callback": {
                "status": "requested",
                "question": reply.content,
                "reply_event_id": reply.id,
                "confirmation_step_id": receipt.id,
                "instruction_step_id": instructions.id,
                "source_version": instructions.tool_result["source_version"],
            },
        }
    if answer := question_response(run, reply, confirmation_step_id=receipt.id):
        body += "\n\n" + answer
    row = patient_message(
        run,
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
            "patient_question_topic": "blood_test" if blood_test_question else None,
            "question_review_step_id": run.checkpoint.get("question_review_step_id"),
            "question_answers": run.checkpoint.get("question_answers", []),
            "unsupported_question": unsupported,
            "selection_step_id": selection.get("selection_step_id"),
            "attendance_step_id": attendance.id if attendance else None,
            "instructions": [
                {"instruction_id": n["instruction_id"], "version": n["version"]} for n in notes
            ],
        },
    )
    db.add(row)
    db.flush()
    return row


def save_options(db, run):
    reply = saved_reply(db, run)
    existing = db.scalar(
        select(SimulatedMessage).where(
            SimulatedMessage.run_id == run.id,
            SimulatedMessage.event_id == reply.id,
            SimulatedMessage.kind == "options",
        )
    )
    if existing:
        return existing
    steps = current_tools(db, run)
    context = latest_tool(steps, "read_followup_context", "engagement")
    instructions = latest_tool(steps, "get_approved_instructions", "preparation")
    data = context.tool_result["data"]
    slots = data["available_slots"]
    if run.checkpoint.get("appointment_intent") == "CHANGE" and data.get("scheduled_at"):
        current_time = datetime.fromisoformat(data["scheduled_at"])
        slots = [s for s in slots if datetime.fromisoformat(s["starts_at"]) != current_time]
    all_slots = slots
    case = db.get(FollowupCase, run.case_id)
    constraints = effective_constraints(run, preferences_for(db, case))
    slots = matching_slots(slots, constraints)
    requested_slots = slots
    review = run.checkpoint.get("scheduling_review")
    slots = compatible(slots, review)
    restricted = [r for r in (review or []) if r["effect"] != "INFORMATION"]
    clinical_conflict = bool(restricted and (len(slots) != len(requested_slots) or not slots))
    mismatch = bool(all_slots and not slots)
    scheduled = context.tool_result["data"].get("source_status") == "scheduled"
    unchanged = (
        "Your existing appointment is unchanged. " if scheduled else "Nothing has been booked. "
    )
    if slots:
        body = unchanged + "These alternative clinic slots are available now:\n"
        if booking_choice(db, run):
            body = (
                unchanged
                + "The selected slot or clinic details changed. These are the current alternatives:\n"
            )
        body += "\n".join(
            f"Option {i}: {appointment_time(slot['starts_at'])} — {slot['doctor']}"
            for i, slot in enumerate(slots, 1)
        )
    elif mismatch:
        body = (
            unchanged
            + "None of the currently listed slots matches your requested times or saved preferences. Would another day or time work?"
        )
    else:
        body = (
            unchanged
            + "The clinic currently lists no alternative slots. I've requested help from the clinic team to find a suitable time."
        )
    if clinical_conflict:
        explanation = "Your doctor's instructions say: " + " ".join(
            dict.fromkeys(r["quote"] for r in restricted)
        )
        if slots:
            body = (
                explanation
                + "\n\nOnly these matching slots meet the recorded timing instructions:\n"
                + "\n".join(
                    f"Option {i}: {appointment_time(slot['starts_at'])} — {slot['doctor']}"
                    for i, slot in enumerate(slots, 1)
                )
            )
        else:
            unavailable_explanation = ""
            if requested_slots and all(r["effect"] == "DATE_WINDOW" for r in restricted):
                listed_times = "; ".join(
                    dict.fromkeys(appointment_time(s["starts_at"]) for s in requested_slots)
                )
                unavailable_explanation = (
                    "The listed alternatives are "
                    + listed_times
                    + ". These fall outside the timing allowed by your doctor's instructions. "
                )
            body = (
                explanation
                + "\n\n"
                + unavailable_explanation
                + "I can't offer a time matching your request within these instructions. I've requested a call from the clinic team to help arrange a suitable appointment."
            )
            if scheduled:
                body += (
                    " Your existing appointment on "
                    + appointment_time(context.tool_result["data"]["scheduled_at"])
                    + " has not been changed."
                )
            else:
                body += " Nothing has been booked."
            run.checkpoint = {
                **run.checkpoint,
                "callback": {
                    "status": "requested",
                    "topic": "doctor scheduling instructions",
                    "question": reply.content,
                    "reply_event_id": reply.id,
                    "decision_step_id": run.checkpoint["question_review_step_id"],
                    "instructions": restricted,
                },
            }
    # Preparation evidence still gates eligibility; general instructions are
    # delivered by save_acknowledgement after a verified source confirmation.
    if slots:
        body += "\n\nWhich option works for you? We will check availability before confirming your choice or moving your existing appointment."
    if answer := question_response(run, reply):
        body += "\n\n" + answer
    row = patient_message(
        run,
        clinic_id=run.clinic_id,
        case_id=run.case_id,
        run_id=run.id,
        event_id=reply.id,
        kind="options",
        body=body,
        source_version=context.tool_result["source_version"],
        evidence={
            "slots": slots,
            "scheduling_review_step_id": run.checkpoint.get("question_review_step_id"),
            "scheduling_review": review,
            "doctor_instruction_conflict": clinical_conflict,
            "constraint_mismatch": mismatch,
            "applied_constraints": constraints,
            "selection_changed": bool(booking_choice(db, run)),
            "episode_version": context.tool_result["data"]["episode_version"],
            "source_step_id": context.id,
            "instruction_step_id": instructions.id,
            "instruction_check_resolutions": run.checkpoint.get("instruction_check_resolutions", []),
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
        "body": row.translation.get(
            "body",
            "Translation needs staff attention; this message has not been sent."
            if row.translation.get("status") == "failed"
            else "Translation is being prepared; this message has not been sent.",
        )
        if row.translation
        else row.body,
        "original_body": row.body,
        "translation": row.translation,
        "created_at": at.isoformat(),
        "source_version": row.source_version,
        "evidence": row.evidence,
        "channel": "patient_simulator",
        "delivery_status": "displayed_in_simulator",
        "synthetic": True,
    }


def clarification_count(db, run):
    return sum(
        bool(m.evidence.get("general_clarification"))
        for m in db.scalars(
            select(SimulatedMessage).where(
                SimulatedMessage.run_id == run.id,
                SimulatedMessage.clinic_id == run.clinic_id,
                SimulatedMessage.kind == "clarification",
            )
        )
    )


def clarification_allowed(db, run):
    if (
        not simulation_enabled(run)
        or not saved_reply(db, run)
        or clarification_count(db, run) >= 2
        or reply_evidence(db, run)
    ):
        return False
    event_id = run.checkpoint.get("latest_event", {}).get("id")
    for step in db.scalars(
        select(AgentStep).where(
            AgentStep.run_id == run.id,
            AgentStep.clinic_id == run.clinic_id,
            AgentStep.tool_result.is_not(None),
        )
    ):
        if step.observation.get("latest_event", {}).get("id") != event_id:
            continue
        result = step.tool_result
        if result.get("status") == "failed" or "STAFF_REVIEW_REQUIRED" in result.get(
            "data", {}
        ).get("prerequisites", []):
            return False
    return True
