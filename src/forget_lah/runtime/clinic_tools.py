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


class ContextData(StrictModel):
    specialty: Literal["dental", "myopia", "antenatal"]
    source_status: Literal["due", "scheduled", "no_show", "cancelled", "completed"]
    scheduled_at: str | None = Field(max_length=40)
    due_at: str | None = Field(max_length=40)
    can_contact_patient: Literal[False]
    can_write_appointments: Literal[False]


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
    """Read-only allowlist. No patient, URL or clinic is chosen by the model."""

    def __init__(self, base_url: str, transport=None):
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    def execute(self, tool_name: str, binding: dict) -> ToolResult:
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
