"""Bounded staff-authorized follow-up change contract."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class StaffSourceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    clinic_id: UUID
    patient_id: UUID
    actor_id: UUID
    expected_version: int = Field(ge=1)
    expected_source_version: str = Field(min_length=1, max_length=40)
    slot_id: UUID
    slot_version: int = Field(ge=1)


class StaffChangeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    patient_id: UUID
    source_episode_ref: str = Field(min_length=1, max_length=100)
    actor_id: UUID
    old_scheduled_at: AwareDatetime
    scheduled_at: AwareDatetime
    slot_id: UUID
    episode_version: int = Field(ge=1)
    changed_at: AwareDatetime
    status: Literal["STAFF_CHANGED_AWAITING_PATIENT"]
    source_version: str = Field(min_length=1, max_length=40)
    record_owner: Literal["clinic_api", "forget_lah"]
