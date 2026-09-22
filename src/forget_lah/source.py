from datetime import datetime
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

DEMO_CLINIC_ID = "10000000-0000-4000-8000-000000000001"


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    patient_id: UUID
    display_alias: str = Field(min_length=1, max_length=100)
    source_episode_ref: str = Field(min_length=1, max_length=100)
    specialty: Literal["dental", "myopia", "antenatal", "general"]
    record_type: Literal["appointment", "recall"]
    source_status: Literal["scheduled", "no_show", "due", "cancelled", "completed"]
    scheduled_at: datetime | None = None
    due_at: datetime | None = None
    has_future_booking: bool = False


def candidates_from_payload(payload: list[dict]) -> list[Candidate]:
    if len(payload) > 500:
        raise ValueError("Candidate batch exceeds the local limit")
    return [Candidate.model_validate(row) for row in payload]


def read_candidates(base_url: str) -> list[Candidate]:
    # Endpoint is operator configuration, never a model or uploaded-data URL.
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        response = client.get(f"{base_url.rstrip('/')}/internal/candidates")
        response.raise_for_status()
        return candidates_from_payload(response.json())
