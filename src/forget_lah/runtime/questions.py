"""Per-turn questions are tasks, not persistent patient preferences."""

from forget_lah.runtime.models import AgentStep


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
        if answer["outcome"] in {"ANSWERED", "GUIDANCE"}:
            text = (
                f"Please keep your clinic's advice in mind: {answer['quote']}"
                if answer["outcome"] == "GUIDANCE"
                else f"Your clinic advises: {answer['quote']}"
            )
            if text not in parts:
                parts.append(text)
        elif answer["outcome"] == "NOT_REQUIRED":
            if "Thanks for letting us know your plans." not in parts:
                parts.append("Thanks for letting us know your plans.")
        elif answer["outcome"] == "UNSUPPORTED":
            parts.append(f"Regarding ‘{question}’, sorry, I can't check that here.")
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
