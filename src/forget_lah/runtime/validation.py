"""Bounded diagnostics, kept apart from permitted decisions and model instructions."""

import hashlib
import json

from pydantic import ValidationError

from forget_lah.runtime.contracts import reject_constant, unique_object


def validation_failure(text: str, error: ValueError, attempt: int) -> dict:
    raw = text.encode("utf-8")
    proposal = None
    if len(raw) <= 16000:
        try:
            value = json.loads(
                text, object_pairs_hook=unique_object, parse_constant=reject_constant
            )
            if isinstance(value, dict):
                proposal = value
        except (ValueError, TypeError):
            pass
    if isinstance(error, ValidationError):
        errors = [
            {"field": ".".join(map(str, item["loc"])), "code": item["type"], "message": item["msg"]}
            for item in error.errors(include_input=False, include_context=False, include_url=False)[
                :8
            ]
        ]
    else:
        # Do not persist unstructured model text or echo it into a repair prompt.
        errors = [
            {
                "field": "decision",
                "code": "invalid_decision",
                "message": "Decision must be valid JSON and match the current request and case version.",
            }
        ]
    return {
        "attempt": attempt,
        "errors": errors,
        "proposal": proposal,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_bytes": len(raw),
    }
