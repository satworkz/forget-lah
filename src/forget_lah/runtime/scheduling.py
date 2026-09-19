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
    return None


def normalize_review(review):
    """Intersect clear absolute source boundaries with model interpretation; never loosen them."""
    if review is None:
        return None
    result = []
    months = "|".join(calendar.month_name[1:])
    pattern = rf"\b(on or before|on or after|not before|not after|before|after|by)\s+((?:\d{{4}}-\d{{2}}-\d{{2}})|(?:(?:\d{{1,2}}\s+)?(?:{months})\s+\d{{4}}))\b"
    for value in review:
        item = dict(value)
        for match in re.finditer(pattern, item["quote"], re.I):
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
        result.append(item)
    return result


def compatible(slots, review):
    review = normalize_review(review)
    if review is None or any(r["effect"] == "CLINIC_REVIEW" for r in review):
        return []

    def allowed(slot):
        day = (
            datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00"))
            .astimezone(ZoneInfo("Asia/Singapore"))
            .date()
            .isoformat()
        )
        return all(
            (not r.get("date_from") or day >= r["date_from"])
            and (not r.get("date_to") or day <= r["date_to"])
            for r in review
        )

    return [slot for slot in slots if allowed(slot)]
