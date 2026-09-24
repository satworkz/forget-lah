"""Restore typographic variants to exact saved patient text, without paraphrase matching."""

import re

PUNCTUATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def indexed_text(text):
    chars, spans = [], []
    for match in re.finditer(r"\s+|\S", text):
        value = match.group()
        chars.append(" " if value.isspace() else value.translate(PUNCTUATION))
        spans.append(match.span())
    return "".join(chars), spans


def source_quote(quote, source):
    if not isinstance(quote, str) or not quote.strip():
        return quote
    if quote in source:
        return quote
    canonical, offsets = indexed_text(source)
    wanted, _ = indexed_text(quote)
    index = canonical.find(wanted)
    if index < 0:
        return quote
    return source[offsets[index][0] : offsets[index + len(wanted) - 1][1]]


def restore_patient_quotes(value, source):
    repairs = []

    def restore(container, key, path):
        old = container.get(key)
        if not isinstance(old, str):
            return
        new = source_quote(old, source)
        if new != old:
            container[key] = new
            repairs.append({"field": path, "model_quote": old, "source_quote": new})

    for field in (
        "concern_quote",
        "comprehension_quote",
        "appointment_request_quote",
        "attendance_quote",
        "contact_stop_quote",
        "answer_quote",
    ):
        restore(value, field, field)
    for field in ("patient_questions", "preparation_plans", "evidence_quotes", "symptom_quotes"):
        items = value.get(field)
        if isinstance(items, list):
            for i, item in enumerate(items):
                box = {"quote": item}
                restore(box, "quote", f"{field}.{i}")
                items[i] = box["quote"]
    updates = value.get("updates")
    for i, update in enumerate(updates if isinstance(updates, list) else []):
        if isinstance(update, dict):
            restore(update, "quote", f"updates.{i}.quote")
    return value, repairs
