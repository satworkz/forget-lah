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


class QuestionAnswer(StrictModel):
    question_index: int = Field(ge=0, le=2)
    outcome: Literal["ANSWERED", "GUIDANCE", "NOT_REQUIRED", "CLINIC_REVIEW", "UNSUPPORTED"]
    instruction_id: str | None = None
    quote: str | None = Field(default=None, max_length=600)
    relation: (
        Literal[
            "CONFLICTS",
            "MAY_CONFLICT",
            "SATISFIES",
            "POSSIBLE_SUBSTITUTION",
            "RELEVANT",
        ]
        | None
    ) = None
    practical_issue: (
        Literal[
            "LOCATION_OR_DIRECTIONS",
            "TRANSPORT_OR_ACCOMPANIMENT",
            "WORK_OR_SOCIAL_COMMITMENT",
            "ITEM_OR_DOCUMENT",
            "PREPARATION_ROUTINE",
            "OTHER",
        ]
        | None
    ) = None
    dependency: (
        Literal[
            "SCREEN_USE",
            "DRIVING",
            "FOOD_OR_DRINK",
            "MEDICATION",
            "ITEM_OR_DOCUMENT",
            "TIMING",
            "TRAVEL_OR_NAVIGATION",
            "OTHER",
        ]
        | None
    ) = None
    actions: list[
        Literal[
            "FOLLOW_CLINIC_INSTRUCTION",
            "ARRANGE_ASSISTANCE",
            "CONTACT_CLINIC",
            "OFFER_RESCHEDULE",
        ]
    ] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def bound_answer(self):
        if self.outcome in {"ANSWERED", "GUIDANCE"} and (not self.instruction_id or not self.quote):
            raise ValueError("Answered questions require an exact approved source quote")
        if self.outcome not in {"ANSWERED", "GUIDANCE"} and (self.instruction_id or self.quote):
            raise ValueError("Unanswered questions have no source answer")
        if self.outcome == "GUIDANCE":
            if self.relation is None or self.practical_issue is None or self.dependency is None:
                raise ValueError(
                    "Plan guidance requires a typed relation, practical issue and dependency"
                )
            if self.relation == "CONFLICTS" and "FOLLOW_CLINIC_INSTRUCTION" not in self.actions:
                raise ValueError("A conflict must preserve the clinic instruction")
            if self.relation == "POSSIBLE_SUBSTITUTION" and not (
                {
                    "CONTACT_CLINIC",
                    "FOLLOW_CLINIC_INSTRUCTION",
                }
                & set(self.actions)
            ):
                raise ValueError("A possible substitution needs a source-preserving next step")
            if self.relation == "SATISFIES" and self.actions:
                raise ValueError("A satisfied plan does not need corrective actions")
        elif (
            self.relation is not None
            or self.practical_issue is not None
            or self.dependency is not None
            or self.actions
        ):
            raise ValueError("Only plan guidance carries relation/actions")
        return self


class SchedulingInstruction(StrictModel):
    instruction_id: str
    quote: str = Field(min_length=1, max_length=2000)
    effect: Literal["INFORMATION", "DATE_WINDOW", "PATIENT_CHECK", "CLINIC_REVIEW"]
    date_from: str | None = None
    date_to: str | None = None
    condition_quote: str | None = Field(default=None, min_length=1, max_length=600)
    patient_question: str | None = Field(default=None, min_length=8, max_length=240)
    if_not_met: Literal["RESCHEDULE", "CLINIC_REVIEW"] | None = None
    consequence_quote: str | None = Field(default=None, min_length=1, max_length=600)

    @model_validator(mode="after")
    def valid_window(self):
        from datetime import date

        for value in (self.date_from, self.date_to):
            if value is not None:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("Use ISO YYYY-MM-DD dates")
        if self.effect == "DATE_WINDOW":
            if not (self.date_from or self.date_to):
                raise ValueError("A date window needs at least one bound")
            if self.date_from and self.date_to and self.date_from > self.date_to:
                raise ValueError("Invalid date window")
        elif self.date_from or self.date_to:
            raise ValueError("Only date windows have date bounds")

        check_fields = (self.condition_quote, self.patient_question, self.if_not_met)
        if self.effect == "PATIENT_CHECK":
            if any(value is None for value in check_fields):
                raise ValueError(
                    "Patient checks need condition evidence, a question and an unmet action"
                )
            if self.if_not_met == "RESCHEDULE" and not self.consequence_quote:
                raise ValueError("Reschedule requires an exact consequence quote")
        elif any(value is not None for value in (*check_fields, self.consequence_quote)):
            raise ValueError("Only patient checks carry patient-check fields")
        return self


class ReturnDecision(BoundDecision):
    scheduling_review: list[SchedulingInstruction] | None = Field(default=None, max_length=20)
    question_answers: list[QuestionAnswer] = Field(default_factory=list, max_length=3)
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


class InstructionCheckDecision(BoundDecision):
    step_type: Literal["INTERPRET_INSTRUCTION_CHECK"]
    reason_code: Literal["DOCTOR_INSTRUCTION_CHECK_REVIEWED"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    question_message_id: str = Field(min_length=36, max_length=36)
    outcome: Literal["MET", "NOT_MET", "UNCLEAR"]
    answer_quote: str = Field(min_length=1, max_length=240)


class ClinicalReportDecision(BoundDecision):
    step_type: Literal["REPORT_SYMPTOMS"]
    reason_code: Literal["PATIENT_REPORTED_SYMPTOMS"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    symptom_quotes: list[str] = Field(min_length=1, max_length=3)
    attendance_quote: str | None = None
    contact_stop_quote: str | None = Field(default=None, max_length=240)


class ClarifyDecision(BoundDecision):
    step_type: Literal["CLARIFY"]
    reason_code: Literal["AMBIGUOUS_REPLY"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    question: str = Field(min_length=10, max_length=240)
    concern_quote: str | None = Field(default=None, max_length=200)
    excluded_minutes: list[int] = Field(default_factory=list, max_length=12)
    remember_exclusions: bool = False
    evidence_quotes: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def valid_memory(self):
        if any(not 0 <= m <= 1439 for m in self.excluded_minutes):
            raise ValueError("Excluded time out of range")
        if self.remember_exclusions and (not self.excluded_minutes or not self.evidence_quotes):
            raise ValueError("Lasting restriction requires time and quote evidence")
        return self


class MemoryChange(StrictModel):
    key: Literal[
        "excluded_weekdays",
        "excluded_minutes",
        "preferred_language",
        "excluded_languages",
        "contact_permission",
        "arrival_support",
        "other_concern",
    ]
    value: str = Field(max_length=160)
    scope: Literal["visit", "future"]
    operation: Literal["set", "remove"] = "set"
    quote: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def valid_value(self):
        if self.operation == "remove":
            if self.key == "contact_permission":
                raise ValueError("Contact permission requires explicit simulator control to resume")
            return self
        if self.key in {"excluded_weekdays", "excluded_minutes"}:
            numbers = [int(v.strip()) for v in self.value.split(",")]
            if (
                not numbers
                or len(numbers) > 12
                or any(
                    n < 0 or n > (6 if self.key == "excluded_weekdays" else 1439) for n in numbers
                )
            ):
                raise ValueError(
                    "Use at most 12 explicitly rejected exact times/days. Never expand a preferred time window into exclusions; use ASSESS_BARRIERS time bounds or clarify instead."
                )
        if self.key == "contact_permission" and (self.value != "stopped" or self.scope != "future"):
            raise ValueError("Stop contact is persistent; resume uses an explicit control")
        if self.key == "preferred_language" and not re.fullmatch(
            r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", self.value
        ):
            raise ValueError("Use a language tag or und for unknown")
        if self.key == "excluded_languages" and not all(
            re.fullmatch(r"[a-z]{2,3}", v) for v in self.value.split(",")
        ):
            raise ValueError("Invalid language tags")
        if self.key == "arrival_support" and self.value != "needs_clarification":
            raise ValueError("Clarify practical support; never label a patient as late")
        return self


class AttendanceQualification(StrictModel):
    """Explicit qualification attached to an apparent attendance confirmation.

    The model extracts only what the patient said. Application code compares
    structured timing with the source appointment; the model never decides
    whether late arrival is acceptable to the clinic.
    """

    quote: str = Field(min_length=1, max_length=240)
    kind: Literal["ARRIVAL_TIME", "ARRIVAL_OFFSET", "CONDITION"]
    arrival_minute: int | None = Field(default=None, ge=0, le=1439)
    arrival_offset_minutes: int | None = Field(default=None, ge=-240, le=240)

    @model_validator(mode="after")
    def consistent(self):
        if self.kind == "ARRIVAL_TIME":
            if self.arrival_minute is None or self.arrival_offset_minutes is not None:
                raise ValueError("ARRIVAL_TIME requires only arrival_minute")
        elif self.kind == "ARRIVAL_OFFSET":
            if self.arrival_offset_minutes is None or self.arrival_minute is not None:
                raise ValueError("ARRIVAL_OFFSET requires only arrival_offset_minutes")
        elif self.arrival_minute is not None or self.arrival_offset_minutes is not None:
            raise ValueError("CONDITION does not carry invented timing")
        return self


class NeedsDecision(BoundDecision):
    preparation_plans: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Neutral transport, accompaniment, food or medication plans; exact quotes. Never attendance/booking intent alone. Inability to meet preparation requirements belongs in patient_questions; declining attendance belongs in appointment_intent.",
    )
    patient_questions: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="Questions or explicit preparation needs; exact reply quotes. Plain attendance refusal is appointment_intent CHANGE, cancellation is CANCEL, not a patient question.",
    )
    step_type: Literal["REVIEW_NEEDS"]
    reason_code: Literal["PATIENT_NEEDS_REVIEWED"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    updates: list[MemoryChange] = Field(max_length=5)
    appointment_intent: Literal["UNSPECIFIED", "CHANGE", "CONFIRM", "CANCEL"] = "UNSPECIFIED"
    appointment_request_quote: str | None = Field(default=None, max_length=240)
    attendance_qualification: AttendanceQualification | None = None
    question: str | None = Field(default=None, max_length=240)
    comprehension_quote: str | None = Field(default=None, max_length=240)
    concern_quote: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def unique_keys(self):
        for update in self.updates:
            if update.key == "arrival_support" and any(
                plan in update.quote or update.quote in plan for plan in self.preparation_plans
            ):
                raise ValueError(
                    "A neutral preparation plan cannot also be an arrival-support need; remove that update or classify an explicit unmet need as patient_questions"
                )
        if len(self.patient_questions) + len(self.preparation_plans) > 3:
            raise ValueError("At most three preparation tasks per reply")
        if len({u.key for u in self.updates}) != len(self.updates):
            raise ValueError("One change per key per decision")
        if self.appointment_intent != "UNSPECIFIED" and not self.appointment_request_quote:
            raise ValueError("Appointment intent needs supporting words")
        if self.attendance_qualification is not None and self.appointment_intent != "CONFIRM":
            raise ValueError(
                "Attendance qualification is valid only with stated confirmation intent"
            )
        return self


class BarrierDecision(BoundDecision):
    step_type: Literal["ASSESS_BARRIERS"]
    reason_code: Literal["PATIENT_BARRIERS_REVIEWED"]
    reply_event_id: str = Field(min_length=36, max_length=36)
    evidence_quotes: list[str] = Field(min_length=1, max_length=3)
    earliest_minute: int | None = Field(default=None, ge=0, le=1439)
    latest_minute: int | None = Field(default=None, ge=0, le=1439)
    weekdays: list[Literal[0, 1, 2, 3, 4, 5, 6]] = Field(default_factory=list, max_length=7)
    requested_date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    clarification_question: str | None = Field(default=None, min_length=1, max_length=240)
    excluded_minutes: list[int] = Field(default_factory=list, max_length=12)
    rejects_current_offer: bool = False
    concern_quote: str | None = Field(default=None, max_length=200)
    remember_exclusions: bool = False
    preparation_issue: Literal["NONE", "INCOMPLETE", "NEEDS_EXPLANATION"] = "NONE"
    clarification_reason: Literal["NONE", "AMBIGUOUS_DATE", "UNRESOLVED_PREFERENCE"] = "NONE"
    next_action: Literal["SEARCH_SLOTS", "CLARIFY_TIME", "REVIEW_PREPARATION"]

    @model_validator(mode="after")
    def valid_constraints(self):
        from datetime import date

        if any(not 0 <= minute <= 1439 for minute in self.excluded_minutes):
            raise ValueError("Excluded times must be minutes of day")
        if self.remember_exclusions and not self.excluded_minutes:
            raise ValueError("Lasting scheduling concern requires an excluded time")
        if self.requested_date is not None:
            date.fromisoformat(self.requested_date)
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("Date range needs both date_from and date_to")
        if self.date_from is not None:
            if date.fromisoformat(self.date_from) > date.fromisoformat(self.date_to):
                raise ValueError("Date range is reversed")
            if self.requested_date and not self.date_from <= self.requested_date <= self.date_to:
                raise ValueError("Requested date conflicts with date range")
        if self.earliest_minute is not None and self.latest_minute is not None:
            if self.earliest_minute > self.latest_minute:
                raise ValueError("Time window is reversed")
        if self.clarification_reason != "NONE" and not self.clarification_question:
            raise ValueError("A real timing ambiguity needs a focused question")
        if self.next_action == "REVIEW_PREPARATION" and self.preparation_issue == "NONE":
            raise ValueError("Preparation review requires an explicit issue")
        return self


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
    | InstructionCheckDecision
    | ClinicalReportDecision
    | BarrierDecision
    | ClarifyDecision
    | NeedsDecision,
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


def parse_decision(
    text: str, request_id: str, case_version: int, *, patient_source=None, quote_repairs=None
):
    if len(text.encode("utf-8")) > 16000:
        raise ValueError("Decision exceeds limit")
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n([\s\S]+)\n```", text)
    if fenced:
        text = fenced.group(1)
    value = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    if isinstance(value, dict) and patient_source is not None:
        from forget_lah.runtime.evidence_text import restore_patient_quotes

        value, repairs = restore_patient_quotes(value, patient_source)
        if quote_repairs is not None:
            quote_repairs.extend(repairs)
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
        Literal[
            "SOURCE_UNAVAILABLE",
            "SOURCE_INVALID",
            "SOURCE_NOT_FOUND",
            "SOURCE_CONFLICT",
            "SOURCE_READ_ONLY",
        ]
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
    "REVIEW_NEEDS": {},
    "CLARIFY": {
        "reply_event_id": "saved reply ID",
        "question": "one short administrative clarification question, no advice or promises",
    },
    "ASSESS_BARRIERS": {
        "reply_event_id": "saved reply ID",
        "evidence_quotes": ["exact patient substrings supporting constraints or preparation issue"],
        "earliest_minute": "local SGT minute of day, or null",
        "latest_minute": "local SGT minute of day, or null",
        "weekdays": "Monday=0 through Sunday=6; empty means unrestricted",
        "requested_date": "unambiguous YYYY-MM-DD or null; clarify ambiguous dates",
        "date_from": "inclusive local YYYY-MM-DD range start, or null",
        "date_to": "inclusive local YYYY-MM-DD range end, or null",
        "clarification_question": "one focused question resolving a stated ambiguity, or null",
        "clarification_reason": ["NONE", "AMBIGUOUS_DATE", "UNRESOLVED_PREFERENCE"],
        "excluded_minutes": "SGT minutes explicitly unavailable; not a before/after bound",
        "rejects_current_offer": "true only when patient rejects all currently offered choices",
        "preparation_issue": ["NONE", "INCOMPLETE", "NEEDS_EXPLANATION"],
        "next_action": ["SEARCH_SLOTS", "CLARIFY_TIME", "REVIEW_PREPARATION"],
    },
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
    "INTERPRET_INSTRUCTION_CHECK": {
        "reply_event_id": "saved reply ID",
        "question_message_id": "doctor-instruction question message ID",
        "outcome": ["MET", "NOT_MET", "UNCLEAR"],
        "answer_quote": "exact patient substring that answers the doctor-instruction question",
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
