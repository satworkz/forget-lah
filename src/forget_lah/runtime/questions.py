"""Per-turn questions are tasks, not persistent patient preferences."""

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

        if task_type == "PLAN" and answer.outcome not in {
            "GUIDANCE",
            "NOT_REQUIRED",
        }:
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
            # Contextual synthesis can only use information that Preparation
            # explicitly classified as informational guidance for this turn.
            # PATIENT_CHECK or DATE_WINDOW instructions cannot quietly be
            # weakened into friendly advice.
            return "GUIDANCE_REQUIRES_INFORMATION_REVIEW"

    return None


def _contextual_guidance(task, answer, appointment_intent):
    quote = answer["quote"]
    relation = answer.get("guidance_relation") or "GENERAL_RELEVANCE"

    prefix = f'You mentioned: "{task}". Your clinic\'s approved note says: {quote}.'

    if relation == "PRACTICAL_RELEVANCE":
        body = (
            prefix
            + " That guidance may be relevant to the practical plan you "
            + "mentioned, so please take it into account when planning "
            + "around the appointment. "
            + "I can't tell from the note alone whether you need to change "
            + "that plan."
        )

        if appointment_intent == "CONFIRM":
            body += (
                " If this affects your plans, you can keep the appointment "
                "or ask me to show alternative appointment dates."
            )

        return body

    if relation == "PREPARATION_RELEVANCE":
        return (
            prefix
            + " That guidance may be relevant to how you prepare for the "
            + "appointment. "
            + "I can't confirm from your plan alone that the clinic "
            + "instruction is satisfied. "
            + "If following it may be difficult, tell me so I can help with "
            + "appointment options or ask the clinic team."
        )

    if relation == "POSSIBLE_SUBSTITUTION":
        return (
            prefix
            + " The clinic note names a specific preparation item or "
            + "requirement. "
            + "I can't confirm that the alternative or availability you "
            + "mentioned replaces or satisfies it. "
            + "If this may be difficult to follow, tell me so I can help "
            + "with appointment options or ask the clinic team."
        )

    body = (
        prefix
        + " This approved guidance may be relevant to the plan you "
        + "mentioned. Please take it into account. "
        + "I don't have enough source information to add requirements "
        + "beyond that note."
    )

    if appointment_intent == "CONFIRM":
        body += (
            " If it creates a problem with your plans, you can ask me to "
            "show alternative appointment dates."
        )

    return body


def question_response(run, reply, *, confirmation_step_id=None):
    questions = run.checkpoint.get("patient_questions", [])
    answers = run.checkpoint.get("question_answers", [])

    if not questions:
        return ""

    by_index = {a["question_index"]: a for a in answers}

    parts = []
    pending = []

    for index, question in enumerate(questions):
        answer = by_index.get(index, {"outcome": "CLINIC_REVIEW"})

        if answer["outcome"] == "GUIDANCE":
            text = _contextual_guidance(
                question,
                answer,
                run.checkpoint.get(
                    "appointment_intent",
                    "UNSPECIFIED",
                ),
            )

            if text not in parts:
                parts.append(text)

        elif answer["outcome"] == "ANSWERED":
            text = f"Your clinic advises: {answer['quote']}"

            if text not in parts:
                parts.append(text)

        elif answer["outcome"] == "NOT_REQUIRED":
            text = "Thanks for letting us know your plans."

            if text not in parts:
                parts.append(text)

        elif answer["outcome"] == "UNSUPPORTED":
            parts.append(
                f'Regarding "{question}", sorry, I can\'t check that here '
                "from the clinic information available."
            )

        else:
            pending.append(question)

    if pending:
        parts.append(
            "I've sent your question to the clinic team and requested a "
            "callback: " + " ".join(pending)
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
