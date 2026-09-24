"""Record and replay real model decisions.

A genuine replay archive reproduces an *observed* execution, so the decisions must come from a real
model run, not from the authored oracle. `RecordingModel` wraps a real provider and records each
observation/reply pair; `RecordedModel` serves those replies back in order and refuses to invent a
reply or accept a mismatched observation.

Observations are recorded by hash so a recording is tied to the context that produced it; the raw
observation is not stored, which keeps patient text out of the recording file beyond what the reply
already implies.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from forget_lah.runtime.provider import ModelError, ModelReply

RECORDING_VERSION = "1"


def observation_sha256(observation: Mapping[str, Any]) -> str:
    payload = json.dumps(observation, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


class RecordingModel:
    """Wrap a real provider; append one record per decision."""

    def __init__(self, inner: Any, records: list[dict[str, Any]]) -> None:
        self._inner = inner
        self._records = records

    def decide(self, observation: Mapping[str, Any], *, repair: bool = False) -> ModelReply:
        reply = self._inner.decide(observation, repair=repair)
        self._records.append(
            {
                "request_id": observation.get("request_id"),
                "repair": repair,
                "observation_sha256": observation_sha256(observation),
                "reply_text": reply.text,
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
                "latency_ms": reply.latency_ms,
            }
        )
        return reply


class RecordedModel:
    """Serve recorded replies in order; never fabricate one."""

    def __init__(
        self, records: Sequence[Mapping[str, Any]], *, verify_observation: bool = True
    ) -> None:
        self._records = list(records)
        self._index = 0
        self._verify = verify_observation

    def decide(self, observation: Mapping[str, Any], *, repair: bool = False) -> ModelReply:
        if self._index >= len(self._records):
            raise ModelError("RECORDING_EXHAUSTED")
        record = self._records[self._index]
        self._index += 1
        if self._verify and record.get("observation_sha256") != observation_sha256(observation):
            raise ModelError("RECORDING_OBSERVATION_MISMATCH")
        return ModelReply(
            record["reply_text"],
            record.get("input_tokens"),
            record.get("output_tokens"),
            record.get("latency_ms"),
        )

    @property
    def consumed(self) -> int:
        return self._index


def recording_document(
    variant_id: str,
    model_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    runtime_commit: str | None = None,
) -> dict[str, Any]:
    return {
        "recording_version": RECORDING_VERSION,
        "variant_id": variant_id,
        "model_id": model_id,
        "runtime_commit": runtime_commit,
        "records": list(records),
    }
