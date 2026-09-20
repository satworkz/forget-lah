"""Per-turn questions are tasks, not persistent patient preferences."""

from forget_lah.runtime.guidance import render_plan_guidance
from forget_lah.runtime.models import AgentStep


def _field(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def validate_answers(db, run, decision):
    questions = run.checkpoint.get("patient_questions", [])
    answers = decision.question_answers
    if sorted(a.question_index for a in answers) != list(range(len(questions))):
        return "QUESTION_COVERAGE_INCOMPLETE"
    notes = {}
    for step_id in decision.evidence_ids:
        step = db.get(AgentStep, step_id)
        if (
            step
            and step.run_id == run.id
            and step.clinic_id == run.clinic_id
            and step.tool_result
            and step.tool_result.get("status") == "succeeded"
            and step.tool_result.get("tool_name") == "get_approved_instructions"
        ):
            notes.update(
                {
                    n["instruction_id"]: n["approved_text"]
                    for n in step.tool_result["data"].get("instructions", [])
                }
            )
    information_reviews = [
        item
        for item in (getattr(decision, "scheduling_review", None) or [])
        if _field(item, "effect") == "INFORMATION"
    ]
    types = run.checkpoint.get("patient_task_types", [])
    for answer in answers:
        task_type = (
            types[answer.question_index] if answer.question_index < len(types) else "QUESTION"
        )
        if task_type == "PLAN" and answer.outcome not in {"GUIDANCE", "NOT_REQUIRED"}:
            return "NEUTRAL_PLAN_REQUIRES_GUIDANCE_REVIEW"
        if answer.outcome in {"GUIDANCE", "NOT_REQUIRED"} and task_type != "PLAN":
            return "PLAN_OUTCOME_REQUIRES_PLAN"
        if answer.outcome in {"ANSWERED", "GUIDANCE"} and (
            answer.instruction_id not in notes
            or not answer.quote.strip()
            or answer.quote not in notes[answer.instruction_id]
        ):
            return "QUESTION_ANSWER_NOT_IN_APPROVED_SOURCE"
        if answer.outcome == "GUIDANCE" and not any(
            _field(item, "instruction_id") == answer.instruction_id
            and answer.quote in (_field(item, "quote") or "")
            for item in information_reviews
        ):
            return "GUIDANCE_REQUIRES_INFORMATION_REVIEW"
        if answer.outcome == "GUIDANCE":
            actions = set(answer.actions)
            if answer.relation == "CONFLICTS" and "FOLLOW_CLINIC_INSTRUCTION" not in actions:
                return "CONFLICT_MUST_PRESERVE_CLINIC_INSTRUCTION"
            if answer.relation == "POSSIBLE_SUBSTITUTION" and not (
                {"CONTACT_CLINIC", "FOLLOW_CLINIC_INSTRUCTION"} & actions
            ):
                return "SUBSTITUTION_NEEDS_SOURCE_PRESERVING_NEXT_STEP"
            if "OFFER_RESCHEDULE" in actions and run.checkpoint.get("appointment_intent") not in {
                "CONFIRM",
                "CHANGE",
            }:
                return "RESCHEDULE_OFFER_REQUIRES_APPOINTMENT_CONTEXT"
    return None


def question_response(run, reply, *, confirmation_step_id=None):
    questions = run.checkpoint.get("patient_questions", [])
    answers = run.checkpoint.get("question_answers", [])
    if not questions:
        return ""
    by_index = {a["question_index"]: a for a in answers}
    parts, pending = [], []
    for index, question in enumerate(questions):
        answer = by_index.get(index, {"outcome": "CLINIC_REVIEW"})
        if answer["outcome"] == "GUIDANCE":
            text = render_plan_guidance(
                question, answer, run.checkpoint.get("appointment_intent", "UNSPECIFIED")
            )
            if text not in parts:
                parts.append(text)
        elif answer["outcome"] == "ANSWERED":
            text = f"Your clinic advises: {answer['quote']}"
            if text not in parts:
                parts.append(text)
        elif answer["outcome"] == "NOT_REQUIRED":
            # A neutral/unrelated plan needs no filler sentence. The appointment
            # acknowledgement already covers the part of the turn that matters.
            continue
        elif answer["outcome"] == "UNSUPPORTED":
            parts.append(
                f"Regarding ‘{question}’, sorry, I can't check that here from the clinic information available."
            )
        else:
            pending.append(question)
    if pending:
        parts.append(
            "I've sent your question to the clinic team and requested a callback: "
            + " ".join(pending)
        )
        run.checkpoint = {
            **run.checkpoint,
            "callback": {
                "status": "requested",
                "question": " ".join(pending),
                "reply_event_id": reply.id,
                "confirmation_step_id": confirmation_step_id,
                "question_review_step_id": run.checkpoint.get("question_review_step_id"),
            },
        }
    return "\n\n".join(parts)
