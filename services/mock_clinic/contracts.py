"""Small test-data editor contracts; these are not patient-facing clinical APIs."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EpisodeInput(Strict):
    specialty: Literal["dental", "myopia", "antenatal"]
    record_type: Literal["appointment", "recall"]
    source_status: Literal["scheduled", "no_show", "due", "cancelled", "completed"]
    scheduled_at: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    has_future_booking: bool = False
    doctor_note: str = Field(default="", max_length=400)
    note_approved: bool = False
    prerequisite: Literal["NOT_APPLICABLE", "STAFF_REVIEW_REQUIRED"] = "NOT_APPLICABLE"

    @field_validator("scheduled_at", "due_at")
    @classmethod
    def utc_dates(cls, value):
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def coherent_schedule(self):
        if self.record_type == "recall":
            if (
                not self.due_at
                or self.scheduled_at
                or self.source_status in {"scheduled", "no_show"}
            ):
                raise ValueError("Recall needs a due date and status due, cancelled or completed")
        elif not self.scheduled_at or self.due_at or self.source_status == "due":
            raise ValueError("Appointment needs an appointment date and a compatible status")
        if self.note_approved and not self.doctor_note:
            raise ValueError("Enter a note before marking it approved for the demo")
        return self


class CreateEpisode(EpisodeInput):
    request_id: UUID
    display_alias: str = Field(min_length=1, max_length=90)


class UpdateEpisode(EpisodeInput):
    expected_version: int = Field(ge=1)


class SlotInput(Strict):
    specialty: Literal["dental", "myopia", "antenatal"]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    doctor: str = Field(min_length=1, max_length=80)
    available: bool = True

    @field_validator("starts_at", "ends_at")
    @classmethod
    def utc_dates(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def positive_duration(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Slot end must be later than its start")
        return self


class CreateSlot(SlotInput):
    request_id: UUID


class UpdateSlot(SlotInput):
    expected_version: int = Field(ge=1)


def iso(value: datetime | None) -> str | None:
    from datetime import UTC

    return (
        value.replace(tzinfo=UTC).isoformat()
        if value and value.tzinfo is None
        else value.isoformat()
        if value
        else None
    )
