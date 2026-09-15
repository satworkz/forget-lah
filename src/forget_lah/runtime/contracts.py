import json
import re
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from forget_lah.agents import StrictModel

Role = Literal["coordinator", "engagement", "preparation"]
# Generic escalation cannot assert clinical severity. REPORT_SYMPTOMS binds exact
# patient quotes to a clinical callback; RED denotes review, not emergency triage.
MODEL_ESCALATION_REASONS = ("AMBIGUOUS_REPLY", "CAPABILITY_UNAVAILABLE")
ToolName = Literal[
    "read_followup_context",
    "get_approved_instructions",
    "check_prerequisites",
    "record_simulated_confirmation",
    "send_simulated_acknowledgement",
    "send_simulated_options",
]
SIMULATION_TOOLS = {
    "engagement": ("record_simulated_confirmation",),
    "coordinator": ("send_simulated_acknowledgement", "send_simulated_options"),
    "preparation": (),
}
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
    "RECORD_SIMULATED_CONFIRMATION",
    "SEND_SIMULATED_ACKNOWLEDGEMENT",
    "SIMULATED_CONFIRMATION_ACKNOWLEDGED",
    "SEND_SIMULATED_OPTIONS",
]


class BoundDecision(StrictModel):
    request_id: str = Field(min_length=36, max_length=36)
    expected_case_version: int = Field(ge=1)
    reason_code: Reason


class ToolDecision(BoundDecision):
    step_type: Literal["TOOL"]
    reason_code: Literal[
        "READ_SOURCE",
        "RECORD_SIMULATED_CONFIRMATION",
        "SEND_SIMULATED_ACKNOWLEDGEMENT",
        "SEND_SIMULATED_OPTIONS",
    ]
    tool_name: ToolName

    @model_validator(mode="after")
    def tool_reason(self):
        expected = {
            "record_simulated_confirmation": "RECORD_SIMULATED_CONFIRMATION",
            "send_simulated_acknowledgement": "SEND_SIMULATED_ACKNOWLEDGEMENT",
            "send_simulated_options": "SEND_SIMULATED_OPTIONS",
        }.get(self.tool_name, "READ_SOURCE")
        if self.reason_code != expected:
            raise ValueError("Tool and reason must match")
        return self


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


class SelectionDecision(BoundDecision):
    step_type: Literal["INTERPRET_SELECTION"]
    reason_code: Literal["PATIENT_SELECTION_REVIEWED"]
    offer_id: str = Field(min_length=36, max_length=36)
    reply_event_id: str = Field(min_length=36, max_length=36)
    option_number: int | None = Field(ge=1, le=10)
    unsupported_question: Literal["NONE", "WEATHER", "PARKING", "OTHER_NON_CLINICAL"] = "NONE"


class AttendanceDecision(BoundDecision):
    step_type: Literal["INTERPRET_ATTENDANCE"]
    reason_code: Literal["PATIENT_ATTENDANCE_REVIEWED"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    source_step_id: str = Field(min_length=36, max_length=36)
    confirmed: bool
    unsupported_question: Literal["NONE", "WEATHER", "PARKING", "OTHER_NON_CLINICAL"] = "NONE"


class ClinicalReportDecision(BoundDecision):
    step_type: Literal["REPORT_SYMPTOMS"]
    reason_code: Literal["PATIENT_REPORTED_SYMPTOMS"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    symptom_quotes: list[str] = Field(min_length=1, max_length=3)
    attendance_quote: str | None = None


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


class CompleteSimulationDecision(BoundDecision):
    step_type: Literal["COMPLETE_SIMULATED_CONFIRMATION"]
    reason_code: Literal["SIMULATED_CONFIRMATION_ACKNOWLEDGED"]
    evidence_ids: list[str] = Field(min_length=2, max_length=2)


Decision = Annotated[
    ToolDecision
    | DelegateDecision
    | ReturnDecision
    | WaitDecision
    | EscalateDecision
    | CompleteDecision
    | CompleteSimulationDecision
    | SelectionDecision
    | AttendanceDecision
    | ClinicalReportDecision,
    # Synthetic success is distinct from owned staff handoff completion.
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
    error_code: (
        Literal["SOURCE_UNAVAILABLE", "SOURCE_INVALID", "SOURCE_NOT_FOUND", "SOURCE_CONFLICT"]
        | None
    )
    retryable: bool


TOOLS_BY_ROLE: dict[str, tuple[str, ...]] = {
    "coordinator": ("read_followup_context",),
    "engagement": ("read_followup_context",),
    "preparation": ("read_followup_context", "get_approved_instructions", "check_prerequisites"),
}

# The model receives this compact protocol; the complete machine-readable schema
# is exported for developers. Identity, URLs, recipients and permissions are absent.
DECISION_FORMATS = {
    "REPORT_SYMPTOMS": {
        "reply_event_id": "saved patient reply ID",
        "symptom_quotes": ["exact substring reporting current symptoms"],
        "attendance_quote": "exact unconditional attendance acceptance substring, or null",
    },
    "INTERPRET_ATTENDANCE": {
        "reply_event_id": "saved reply ID",
        "source_step_id": "current source step ID",
        "confirmed": "true for clear acceptance; false to clarify",
        "unsupported_question": ["NONE", "WEATHER", "PARKING", "OTHER_NON_CLINICAL"],
    },
    "INTERPRET_SELECTION": {
        "offer_id": "saved offer ID",
        "reply_event_id": "saved reply ID",
        "option_number": "selected option number, or null to clarify",
        "unsupported_question": ["NONE", "WEATHER", "PARKING", "OTHER_NON_CLINICAL"],
    },
    "TOOL": {"tool_name": list(TOOLS_BY_ROLE["preparation"])},
    "DELEGATE": {"target": ["engagement", "preparation"], "goal": "brief bounded goal"},
    "RETURN": {"evidence_ids": ["successful tool step ID from this delegation"]},
    "WAIT": {"wake_after_seconds": "0 for reply; 30-300 for source retry"},
    "ESCALATE": {},
    "COMPLETE": {"handoff_id": "accepted handoff ID from application evidence"},
    "COMPLETE_SIMULATED_CONFIRMATION": {
        "evidence_ids": ["confirmation tool step ID", "acknowledgement tool step ID"]
    },
}


def tools_for(role, simulated=False):
    return TOOLS_BY_ROLE[role] + (SIMULATION_TOOLS[role] if simulated else ())
