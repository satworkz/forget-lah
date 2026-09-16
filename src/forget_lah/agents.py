from pydantic import BaseModel, ConfigDict

AGENT_CATALOG = [
    {
        "role": "coordinator",
        "name": "Follow-up Coordinator",
        "goal": "Choose the next specialist and require evidence before closure.",
    },
    {
        "role": "engagement",
        "name": "Patient Engagement",
        "goal": "Review the demo reply and return its intent with source evidence.",
    },
    {
        "role": "preparation",
        "name": "Visit Preparation",
        "goal": "Read approved instructions and prerequisites; return source evidence.",
    },
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
