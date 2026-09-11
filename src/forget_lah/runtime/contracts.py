import json
import re
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from forget_lah.agents import StrictModel

Role = Literal["coordinator", "engagement", "preparation"]
ToolName = Literal["read_followup_context", "get_approved_instructions", "check_prerequisites"]
REQUIRED_EVIDENCE_BY_ROLE = {
    "coordinator": (),
    "engagement": ("read_followup_context",),
    "preparation": ("get_approved_instructions", "check_prerequisites"),
}
Reason = Literal[
    "READ_SOURCE",
    "FOLLOWUP_REVIEW_REQUIRED",
    "PREPARATION_REVIEW_REQUIRED",
    "PATIENT_CONFIRMED_ATTENDANCE",
    "PATIENT_REQUESTED_ALTERNATIVE_DATE",
    "AWAITING_PATIENT_REPLY",
    "SOURCE_TEMPORARILY_UNAVAILABLE",
    "SPECIALIST_REVIEW_FINISHED",
    "AMBIGUOUS_REPLY",
    "CLINICAL_REVIEW_REQUIRED",
    "CAPABILITY_UNAVAILABLE",
    "STAFF_HANDOFF_ACCEPTED",
]


class BoundDecision(StrictModel):
    request_id: str = Field(min_length=36, max_length=36)
    expected_case_version: int = Field(ge=1)
    reason_code: Reason


class ToolDecision(BoundDecision):
    step_type: Literal["TOOL"]
    reason_code: Literal["READ_SOURCE"]
    tool_name: ToolName


class DelegateDecision(BoundDecision):
    step_type: Literal["DELEGATE"]
    reason_code: Literal["FOLLOWUP_REVIEW_REQUIRED", "PREPARATION_REVIEW_REQUIRED"]
    target: Literal["engagement", "preparation"]
    goal: str = Field(min_length=1, max_length=200)


class ReturnDecision(BoundDecision):
    step_type: Literal["RETURN"]
    reason_code: Literal[
        "SPECIALIST_REVIEW_FINISHED",
        "PATIENT_CONFIRMED_ATTENDANCE",
        "PATIENT_REQUESTED_ALTERNATIVE_DATE",
        "AMBIGUOUS_REPLY",
    ]
    evidence_ids: list[str] = Field(min_length=1, max_length=4)


class WaitDecision(BoundDecision):
    step_type: Literal["WAIT"]
    reason_code: Literal["AWAITING_PATIENT_REPLY", "SOURCE_TEMPORARILY_UNAVAILABLE"]
    wake_after_seconds: int = Field(ge=0, le=300)

    @model_validator(mode="after")
    def valid_wait(self):
        if self.reason_code == "AWAITING_PATIENT_REPLY" and self.wake_after_seconds != 0:
            raise ValueError("Patient replies require an event, not polling")
        if self.reason_code == "SOURCE_TEMPORARILY_UNAVAILABLE" and self.wake_after_seconds < 30:
            raise ValueError("Source retry must wait at least 30 seconds")
        return self


class EscalateDecision(BoundDecision):
    step_type: Literal["ESCALATE"]
    reason_code: Literal["AMBIGUOUS_REPLY", "CLINICAL_REVIEW_REQUIRED", "CAPABILITY_UNAVAILABLE"]


class CompleteDecision(BoundDecision):
    step_type: Literal["COMPLETE"]
    reason_code: Literal["STAFF_HANDOFF_ACCEPTED"]
    handoff_id: str = Field(min_length=36, max_length=36)


Decision = Annotated[
    ToolDecision
    | DelegateDecision
    | ReturnDecision
    | WaitDecision
    | EscalateDecision
    | CompleteDecision,
    Field(discriminator="step_type"),
]
decision_adapter = TypeAdapter(Decision)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError("Non-finite JSON number")


def parse_decision(text: str, request_id: str, case_version: int):
    if len(text.encode("utf-8")) > 16000:
        raise ValueError("Decision exceeds limit")
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n([\s\S]+)\n```", text)
    if fenced:
        text = fenced.group(1)
    value = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    decision = decision_adapter.validate_python(value)
    if decision.request_id != request_id or decision.expected_case_version != case_version:
        raise ValueError("Decision does not match the current request and case version")
    return decision


class ToolResult(StrictModel):
    tool_name: ToolName
    status: Literal["succeeded", "failed"]
    source_version: str | None
    data: dict
    error_code: Literal["SOURCE_UNAVAILABLE", "SOURCE_INVALID", "SOURCE_NOT_FOUND"] | None
    retryable: bool


TOOLS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "coordinator": ("read_followup_context",),
    "engagement": ("read_followup_context",),
    "preparation": ("read_followup_context", "get_approved_instructions", "check_prerequisites"),
}

# The model receives this compact protocol; the complete machine-readable schema
# is exported for developers. Identity, URLs, recipients and permissions are absent.
DECISION_FORMATS = {
    "TOOL": {"tool_name": list(TOOLS_BY_ROLE["preparation"])},
    "DELEGATE": {"target": ["engagement", "preparation"], "goal": "brief bounded goal"},
    "RETURN": {"evidence_ids": ["successful tool step ID from this delegation"]},
    "WAIT": {"wake_after_seconds": "0 for reply; 30-300 for source retry"},
    "ESCALATE": {},
    "COMPLETE": {"handoff_id": "accepted handoff ID from application evidence"},
}
