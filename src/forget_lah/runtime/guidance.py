"""Grounded response synthesis for patient plans reviewed against approved clinic notes."""


def _quoted(label, value):
    suffix = "" if value.rstrip().endswith((".", "!", "?")) else "."
    return f'{label}: "{value}"{suffix}'


def _action_lines(issue, actions, appointment_intent):
    actions = set(actions or [])
    parts = []
    if "ARRANGE_ASSISTANCE" in actions:
        if issue == "LOCATION_OR_DIRECTIONS":
            parts.append(
                "For location or directions, consider having someone accompany or assist you instead."
            )
        elif issue == "TRANSPORT_OR_ACCOMPANIMENT":
            parts.append("Consider arranging someone to accompany or assist you.")
        else:
            parts.append(
                "Consider arranging someone to assist you with the practical issue you mentioned."
            )
    if "CONTACT_CLINIC" in actions:
        if issue == "LOCATION_OR_DIRECTIONS":
            parts.append("You can also contact the clinic for directions or location help.")
        elif issue == "ITEM_OR_DOCUMENT":
            parts.append(
                "If you are unsure whether the item or alternative you mentioned meets the clinic requirement, contact the clinic to confirm."
            )
        else:
            parts.append("You can also contact the clinic for practical clarification or help.")
    if "OFFER_RESCHEDULE" in actions and appointment_intent in {"CONFIRM", "CHANGE"}:
        parts.append(
            "If this makes the appointment impractical, I can show you alternative appointment dates."
        )
    return " ".join(parts)


def render_plan_guidance(task, answer, appointment_intent):
    """Render only validated model semantics plus exact patient/source evidence."""
    quote = answer["quote"]
    relation = answer["relation"]
    issue = answer.get("practical_issue") or "OTHER"
    dependency = answer.get("dependency") or "OTHER"
    actions = answer.get("actions") or []
    source = _quoted("The clinic advised", quote)
    patient = _quoted("You mentioned", task)
    tail = _action_lines(issue, actions, appointment_intent)

    if relation == "CONFLICTS":
        if dependency == "SCREEN_USE":
            core = (
                "The plan you mentioned would require looking at a screen, which conflicts with that clinic instruction. "
                "Please follow the clinic instruction and avoid screen use during the stated restricted period."
            )
        elif dependency == "FOOD_OR_DRINK":
            core = (
                "The eating or drinking plan you mentioned conflicts with that clinic instruction. "
                "Please follow the clinic instruction during the stated restricted period."
            )
        elif issue == "LOCATION_OR_DIRECTIONS":
            core = (
                "The route-finding plan you mentioned conflicts with that clinic instruction. "
                "Please follow the clinic instruction and do not rely on that conflicting plan during the stated restricted period."
            )
        elif issue == "ITEM_OR_DOCUMENT":
            core = (
                "What you plan to bring or use conflicts with the clinic instruction. "
                "Please follow the clinic instruction rather than substituting the plan you mentioned."
            )
        elif issue == "PREPARATION_ROUTINE":
            core = (
                "The preparation plan you mentioned conflicts with the clinic instruction. "
                "Please follow the clinic instruction during the stated period."
            )
        else:
            core = (
                "The plan you mentioned conflicts with that clinic instruction. "
                "Please follow the clinic instruction rather than the conflicting plan."
            )
    elif relation == "MAY_CONFLICT":
        core = (
            "That clinic guidance may affect the plan you mentioned. "
            "I cannot infer a stronger restriction than the clinic actually wrote, so please take the approved guidance into account."
        )
    elif relation == "SATISFIES":
        core = (
            "What you described is consistent with this clinic instruction. "
            "I am not adding any requirement beyond the approved note."
        )
    elif relation == "POSSIBLE_SUBSTITUTION":
        core = "The clinic instruction names a specific requirement, and I cannot assume that the alternative you mentioned is equivalent."
    else:
        core = (
            "That approved clinic guidance is materially relevant to the plan you mentioned. "
            "Please take it into account without adding requirements beyond the note."
        )

    return " ".join(part for part in (patient, source, core, tail) if part)
