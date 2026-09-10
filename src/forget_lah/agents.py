from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

AGENT_CATALOG = [
    {
        "role": "coordinator",
        "name": "Follow-up Coordinator",
        "goal": "Choose the next specialist and require evidence before closure.",
        "status": "planned",
    },
    {
        "role": "engagement",
        "name": "Patient Engagement",
        "goal": "Reach confirmed attendance or a source-confirmed alternative.",
        "status": "planned",
    },
    {
        "role": "preparation",
        "name": "Visit Preparation",
        "goal": "Deliver approved instructions and resolve acknowledgement.",
        "status": "planned",
    },
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DelegateStep(StrictModel):
    step_type: Literal["DELEGATE"]
    expected_case_version: int = Field(ge=1)
    target: Literal["engagement", "preparation"]
    goal: str = Field(min_length=1, max_length=300)


class EscalateStep(StrictModel):
    step_type: Literal["ESCALATE"]
    expected_case_version: int = Field(ge=1)
    reason_code: Literal["AMBIGUOUS_REPLY", "CLINICAL_REVIEW_REQUIRED"]


# Initial contract subset. Tool, WAIT and evidence-backed COMPLETE branches belong to M2.
Decision = Annotated[DelegateStep | EscalateStep, Field(discriminator="step_type")]
decision_adapter = TypeAdapter(Decision)


def validate_decision(text: str, *, trusted_role: str, current_case_version: int):
    proposal = decision_adapter.validate_json(text)
    if proposal.expected_case_version != current_case_version:
        raise ValueError("Stale case version")
    if isinstance(proposal, DelegateStep) and trusted_role != "coordinator":
        raise ValueError("Only the Coordinator may delegate")
    if trusted_role not in {"coordinator", "engagement", "preparation"}:
        raise ValueError("Unknown trusted role")
    return proposal
