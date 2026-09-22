import json
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import Field

from forget_lah.agents import StrictModel
from forget_lah.runtime.contracts import ToolResult, reject_constant, unique_object


class Instruction(StrictModel):
    instruction_id: str = Field(max_length=60)
    version: str = Field(max_length=30)
    locale: Literal["en-SG"]
    approved_text: str = Field(max_length=400)
    synthetic: Literal[True]


class AvailableSlot(StrictModel):
    id: str = Field(max_length=36)
    starts_at: str = Field(max_length=40)
    ends_at: str = Field(max_length=40)
    doctor: str = Field(max_length=80)
    version: int = Field(default=1, ge=1)


class ContextData(StrictModel):
    specialty: Literal["dental", "myopia", "antenatal", "general"]
    source_status: Literal["due", "scheduled", "no_show", "cancelled", "completed"]
    scheduled_at: str | None = Field(max_length=40)
    due_at: str | None = Field(max_length=40)
    can_contact_patient: Literal[False]
    can_write_appointments: Literal[False]
    episode_version: int | None = Field(default=None, ge=1)
    can_simulate_confirmation: bool = False
    can_simulate_booking: bool = False
    can_simulate_rescheduling: bool = False
    available_slots: list[AvailableSlot] = Field(default_factory=list, max_length=10)
    more_available_slots: bool = False


class SourceEnvelope(StrictModel):
    clinic_id: str = Field(max_length=36)
    patient_id: str = Field(max_length=36)
    source_episode_ref: str = Field(max_length=100)
    source_version: str = Field(min_length=1, max_length=40)
    synthetic: Literal[True]
    context: ContextData
    instructions: list[Instruction] = Field(max_length=5)
    prerequisites: list[Literal["NOT_APPLICABLE", "STAFF_REVIEW_REQUIRED"]] = Field(max_length=5)


class ClinicTools:
    """Bound tools for Forget-lah imports or an external clinic API."""

    def __init__(self, base_url: str, transport=None, followup_key=None, factory=None):
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.followup_key = followup_key
        self.factory = factory

    def staff_change(self, binding, operation):
        # Bridge is committed in the owning application transaction, never over HTTP.
        if binding["source_episode_ref"].startswith("bridge:"):
            raise ValueError("Bridge staff changes require the owned transaction")
        if not self.followup_key:
            raise ValueError("Source authorization is not configured")
        episode = quote(binding["source_episode_ref"], safe="")
        with httpx.Client(timeout=10, follow_redirects=False, transport=self.transport) as client:
            response = client.post(
                f"{self.base_url}/internal/followup/{episode}/staff-change",
                json=operation,
                headers={"X-Followup-Key": self.followup_key},
            )
            response.raise_for_status()
            if len(response.content) > 16000:
                raise ValueError("Source receipt too large")
            receipt = response.json()
            from forget_lah.staff_change_contract import StaffChangeReceipt

            StaffChangeReceipt.model_validate(receipt)
        if (
            receipt.get("operation_id") != operation["operation_id"]
            or receipt.get("patient_id") != binding["patient_id"]
            or receipt.get("source_episode_ref") != binding["source_episode_ref"]
            or receipt.get("actor_id") != operation["actor_id"]
            or receipt.get("slot_id") != operation["slot_id"]
            or receipt.get("episode_version") != operation["expected_version"] + 1
            or receipt.get("status") != "STAFF_CHANGED_AWAITING_PATIENT"
            or receipt.get("record_owner") != "clinic_api"
        ):
            raise ValueError("Source receipt binding mismatch")
        return receipt

    def confirm(self, binding, operation):
        name = "record_simulated_confirmation"
        if binding.get("source_episode_ref", "").startswith("bridge:"):
            if self.factory is None:
                return self.failure(name, "SOURCE_INVALID", False)
            from forget_lah.bridge_source import bridge_confirm

            return bridge_confirm(self.factory, binding, operation)
        if not self.followup_key:
            return self.failure(name, "SOURCE_INVALID", False)
        episode = quote(binding["source_episode_ref"], safe="")
        booking = "slot_id" in operation
        endpoint = (
            "reschedule"
            if operation.get("reschedule")
            else "book-followup"
            if booking
            else "confirm-attendance"
        )
        payload = {
            **operation,
            "clinic_id": binding["clinic_id"],
            "patient_id": binding["patient_id"],
        }
        payload.pop("reschedule", None)
        try:
            with httpx.Client(
                timeout=10, follow_redirects=False, transport=self.transport
            ) as client:
                response = client.post(
                    f"{self.base_url}/internal/followup/{episode}/{endpoint}",
                    json=payload,
                    headers={"X-Followup-Key": self.followup_key},
                )
                if response.status_code == 409:
                    return self.failure(name, "SOURCE_CONFLICT", False)
                if response.status_code in {403, 404}:
                    return self.failure(name, "SOURCE_NOT_FOUND", False)
                response.raise_for_status()
                if len(response.content) > 16000:
                    raise ValueError("Response too large")
                receipt = ConfirmationEnvelope.model_validate(response.json())
            data = receipt.receipt.model_dump()
            if (
                data["receipt_id"] != operation["operation_id"]
                or data["run_id"] != operation["run_id"]
                or data["patient_id"] != binding["patient_id"]
                or data["source_episode_ref"] != binding["source_episode_ref"]
                or data["episode_version"] != operation["expected_version"] + int(booking)
                or (booking and data["booking_slot_id"] != operation["slot_id"])
            ):
                raise ValueError("Confirmation receipt binding mismatch")
            return ToolResult(
                tool_name=name,
                status="succeeded",
                source_version=receipt.source_version,
                data=data,
                error_code=None,
                retryable=False,
            )
        except httpx.HTTPError:
            return self.failure(name, "SOURCE_UNAVAILABLE", True)
        except ValueError:
            return self.failure(name, "SOURCE_INVALID", False)

    def execute(self, tool_name: str, binding: dict) -> ToolResult:
        if binding.get("source_episode_ref", "").startswith("bridge:"):
            if self.factory is None:
                return self.failure(tool_name, "SOURCE_INVALID", False)
            from forget_lah.bridge_source import bridge_tool_result

            return bridge_tool_result(self.factory, binding, tool_name)
        if tool_name not in {
            "read_followup_context",
            "get_approved_instructions",
            "check_prerequisites",
        }:
            raise ValueError("Tool not supported")
        episode = quote(binding["source_episode_ref"], safe="")
        try:
            with httpx.Client(
                timeout=10, follow_redirects=False, transport=self.transport
            ) as client:
                with client.stream(
                    "GET", f"{self.base_url}/internal/followup-context/{episode}"
                ) as r:
                    if r.status_code == 404:
                        return self.failure(tool_name, "SOURCE_NOT_FOUND", False)
                    r.raise_for_status()
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 16000:
                            raise ValueError("Source response too large")
            envelope = SourceEnvelope.model_validate(
                json.loads(body, object_pairs_hook=unique_object, parse_constant=reject_constant)
            )
            for field in ("clinic_id", "patient_id", "source_episode_ref"):
                if getattr(envelope, field) != binding[field]:
                    raise ValueError("Source binding mismatch")
            if tool_name == "read_followup_context":
                data = envelope.context.model_dump()
            elif tool_name == "get_approved_instructions":
                data = {"instructions": [item.model_dump() for item in envelope.instructions]}
            else:
                data = {"prerequisites": envelope.prerequisites}
            return ToolResult(
                tool_name=tool_name,
                status="succeeded",
                source_version=envelope.source_version,
                data=data,
                error_code=None,
                retryable=False,
            )
        except httpx.HTTPError:
            return self.failure(tool_name, "SOURCE_UNAVAILABLE", True)
        except ValueError:
            return self.failure(tool_name, "SOURCE_INVALID", False)

    @staticmethod
    def failure(tool_name, code, retryable):
        return ToolResult(
            tool_name=tool_name,
            status="failed",
            source_version=None,
            data={},
            error_code=code,
            retryable=retryable,
        )


class ConfirmationReceipt(StrictModel):
    receipt_id: str = Field(min_length=36, max_length=36)
    source_episode_ref: str = Field(max_length=100)
    patient_id: str = Field(min_length=36, max_length=36)
    run_id: str = Field(min_length=36, max_length=36)
    episode_version: int = Field(ge=1)
    scheduled_at: str = Field(max_length=40)
    confirmed_at: str = Field(max_length=40)
    synthetic: Literal[True]
    status: Literal["PATIENT_CONFIRMED_ATTENDANCE"]
    booking_slot_id: str | None = Field(default=None, max_length=36)


class ConfirmationEnvelope(StrictModel):
    receipt: ConfirmationReceipt
    source_version: str = Field(min_length=1, max_length=40)
