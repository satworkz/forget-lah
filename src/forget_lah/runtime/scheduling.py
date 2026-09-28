"""Source-bound scheduling constraints, interpreted by Preparation and enforced in code."""

import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from forget_lah.runtime.models import AgentStep


def validate_review(db, run, decision):
    notes = {}
    for step_id in decision.evidence_ids:
        step = db.get(AgentStep, step_id)
        if step and step.run_id == run.id and step.clinic_id == run.clinic_id:
            result = step.tool_result or {}
            if result.get("tool_name") == "get_approved_instructions":
                notes.update(
                    {
                        n["instruction_id"]: n["approved_text"]
                        for n in result["data"].get("instructions", [])
                    }
                )
    review = decision.scheduling_review
    if review is None or {r.instruction_id for r in review} != set(notes):
        return "SCHEDULING_INSTRUCTION_COVERAGE_REQUIRED"
    for item in review:
        if item.quote != notes[item.instruction_id]:
            return "SCHEDULING_INSTRUCTION_SOURCE_MISMATCH"
        if item.effect == "PATIENT_CHECK":
            if not item.condition_quote or item.condition_quote not in item.quote:
                return "PATIENT_CHECK_CONDITION_SOURCE_MISMATCH"
            if item.if_not_met == "RESCHEDULE" and (
                not item.consequence_quote or item.consequence_quote not in item.quote
            ):
                return "PATIENT_CHECK_CONSEQUENCE_SOURCE_MISMATCH"
    return None


def normalize_review(review):
    """Intersect clear absolute source boundaries with model interpretation; never loosen them."""
    if review is None:
        return None
    result = []
    months = "|".join(calendar.month_name[1:])
    pattern = rf"\b(on or before|on or after|not before|not after|before|after|by)\s+((?:\d{{4}}-\d{{2}}-\d{{2}})|(?:(?:\d{{1,2}}\s+)?(?:{months})\s+\d{{4}}))\b"
    for value in review:
        source = dict(value)
        is_check = source.get("effect") == "PATIENT_CHECK"
        if is_check and source not in result:
            result.append(source)

        # Explicit absolute timing text remains enforceable even when the same
        # approved note also contains a patient-verification gate. In that case
        # derive a separate DATE_WINDOW entry instead of replacing PATIENT_CHECK.
        item = (
            {
                "instruction_id": source.get("instruction_id"),
                "quote": source["quote"],
                "effect": "INFORMATION",
                "date_from": None,
                "date_to": None,
            }
            if is_check
            else source
        )
        found_boundary = False
        for match in re.finditer(pattern, source["quote"], re.I):
            found_boundary = True
            operator, raw = match.groups()
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                    first = last = date.fromisoformat(raw)
                else:
                    parts = raw.split()
                    month = next(
                        i
                        for i in range(1, 13)
                        if calendar.month_name[i].lower() == parts[-2].lower()
                    )
                    year = int(parts[-1])
                    first = date(year, month, int(parts[0]) if len(parts) == 3 else 1)
                    last = (
                        first
                        if len(parts) == 3
                        else date(year, month, calendar.monthrange(year, month)[1])
                    )
            except ValueError:
                item["effect"] = "CLINIC_REVIEW"
                continue
            operator = operator.lower()
            if operator in {"before", "by", "on or before", "not after"}:
                upper = (first - timedelta(days=1) if operator == "before" else last).isoformat()
                item["date_to"] = min(item.get("date_to") or upper, upper)
            else:
                lower = (last + timedelta(days=1) if operator == "after" else first).isoformat()
                item["date_from"] = max(item.get("date_from") or lower, lower)
            if item["effect"] != "CLINIC_REVIEW":
                item["effect"] = "DATE_WINDOW"
        if (not is_check or found_boundary) and item not in result:
            result.append(item)
    return result


def requires_completion_date(requirement):
    return requirement.get("if_not_met") == "RESCHEDULE" and bool(
        re.search(
            r"\bafter\b.*\b(?:completion|completed)\b",
            requirement.get("consequence_quote") or requirement.get("quote", ""),
            re.I,
        )
    )


def dependency_date_floor(resolutions):
    dates = [
        r["completion_date"]
        for r in resolutions or []
        if r.get("resolution") == "RESCHEDULE" and r.get("completion_date")
    ]
    return (date.fromisoformat(max(dates)) + timedelta(days=1)).isoformat() if dates else None


def compatible(slots, review, resolutions=None):
    review = normalize_review(review)
    if review is None or any(r["effect"] == "CLINIC_REVIEW" for r in review):
        return []

    if any(r.get("completion_date_pending") for r in resolutions or []):
        return []
    lower = dependency_date_floor(resolutions)

    def allowed(slot):
        day = (
            datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
            .astimezone(ZoneInfo("Asia/Singapore"))
            .date()
            .isoformat()
        )
        return (not lower or day >= lower) and all(
            (not r.get("date_from") or day >= r["date_from"])
            and (not r.get("date_to") or day <= r["date_to"])
            for r in review
        )

    return [slot for slot in slots if allowed(slot)]


def check_signature(item):
    """Stable, source-bound identity for a patient-verifiable doctor-note condition."""
    value = item.model_dump() if hasattr(item, "model_dump") else dict(item)
    if value.get("effect") != "PATIENT_CHECK":
        return None
    return {
        "instruction_id": value["instruction_id"],
        "quote": value["quote"],
        "condition_quote": value["condition_quote"],
        "if_not_met": value["if_not_met"],
    }


def _same_check_source(resolution, requirement):
    return (
        resolution.get("instruction_id") == requirement.get("instruction_id")
        and resolution.get("quote") == requirement.get("quote")
        and resolution.get("if_not_met") == requirement.get("if_not_met")
    )


def _condition_span_matches(resolution, requirement):
    left = (resolution.get("condition_quote") or "").strip()
    right = (requirement.get("condition_quote") or "").strip()
    return bool(left and right and (left == right or left in right or right in left))


def pending_patient_checks(review, resolutions=None):
    requirements = []
    for item in review or []:
        value = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        if value.get("effect") == "PATIENT_CHECK":
            requirements.append(value)
    resolved = [r for r in (resolutions or []) if r.get("resolution") in {"MET", "RESCHEDULE"}]

    pending = []
    for requirement in requirements:
        exact = any(
            _same_check_source(resolution, requirement)
            and resolution.get("condition_quote") == requirement.get("condition_quote")
            for resolution in resolved
        )
        if exact:
            continue

        # A live model may select a slightly wider/narrower exact substring from
        # the same unchanged doctor note on a later pass. Reuse that resolution
        # only when the source/action are identical and the containment match is
        # unambiguous among the current checks. Never use semantic similarity.
        matched = False
        for resolution in resolved:
            if not _same_check_source(resolution, requirement) or not _condition_span_matches(
                resolution, requirement
            ):
                continue
            candidates = [
                item
                for item in requirements
                if _same_check_source(resolution, item)
                and _condition_span_matches(resolution, item)
            ]
            if len(candidates) == 1:
                matched = True
                break
        if not matched:
            pending.append(requirement)
    return pending


def instruction_gate_clear(review, resolutions=None):
    if review is None or any(
        (item.model_dump() if hasattr(item, "model_dump") else item).get("effect")
        == "CLINIC_REVIEW"
        for item in review
    ):
        return False
    return not pending_patient_checks(review, resolutions)
