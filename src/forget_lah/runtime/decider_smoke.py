"""One-call, seam-level System One smoke (Lane A milestone 9).

This is a **seam-level live-model event**, not engine validation. It builds an explicitly
synthetic Coordinator observation, calls ``DeciderModel.decide`` exactly once and reports whether
the hosted decider's decision was accepted or the call fell back to the deterministic inner
provider. It executes no tools, performs no database writes and delivers nothing to a patient.

Shadow mode, standby switching and retries stay disabled: exactly one System One POST happens, and
the result is never repeated to obtain a preferred answer. The inner provider is ``MockModel``
(labelled ``smoke-inner``) purely as a deterministic, non-networked fallback and goal author.

The API key comes from ``AGENT_DECIDER_API_KEY`` in the environment only. This module never opens
a secret file and never prints the key.

Run::

    AGENT_DECIDER_API_KEY=... uv run python -m forget_lah.runtime.decider_smoke
"""

from __future__ import annotations

import json
import os

from forget_lah.db import uid
from forget_lah.runtime.decider import DeciderModel, derive_options
from forget_lah.runtime.provider import base_model_for
from forget_lah.settings import Settings

DEFAULT_RECORD = "/tmp/opencode/forget-lah-lane-a-smoke.jsonl"

REQUIRED_RECORD_KEYS = (
    "schema_version",
    "raw_answer",
    "endpoint_used",
    "usage",
    "latency_ms",
    "decision_provider",
    "legs",
)


def synthetic_observation() -> dict:
    """An explicitly synthetic Coordinator phase; it carries no patient data."""
    return {
        "role": "coordinator",
        "request_id": uid(),
        "expected_case_version": 1,
        "goal": "Synthetic smoke observation: choose the next action for a follow-up case.",
        "latest_event": {"id": uid(), "kind": "started", "content": ""},
        "tools": [],
        "returned_specialists": [],
        "specialist_reports": [],
        "handoff": None,
    }


def main() -> int:
    if not os.environ.get("AGENT_DECIDER_API_KEY", "").strip():
        print("LANE_A_SMOKE_MISSING_KEY: set AGENT_DECIDER_API_KEY in the environment")
        return 2
    record_path = (os.environ.get("AGENT_DECIDER_RECORD") or DEFAULT_RECORD).strip()
    settings = Settings(
        app_env="local",
        database_url="sqlite://",
        agent_model_mode="mock",
        agent_decider_enabled=True,
        agent_decider_shadow=False,
        agent_decider_record=record_path,
        _env_file=None,
    )
    observation = synthetic_observation()
    options = derive_options(observation)
    if not options.eligible:
        print(f"LANE_A_SMOKE_UNUSABLE_OBSERVATION: {options.bypass_reason}")
        return 2

    records: list[dict] = []
    decider = DeciderModel(
        settings,
        base_model_for(settings, "mock"),
        inner_name="smoke-inner",
        event_kind="live-model",
        record_hook=records.append,
    )
    decider.decide(observation)
    record = records[0] if records else {}
    missing = [key for key in REQUIRED_RECORD_KEYS if key not in record]
    raw_answer = record.get("raw_answer") or {}
    summary = {
        "record_path": record_path,
        "gate": record.get("gate"),
        "endpoint_used": record.get("endpoint_used"),
        "model": record.get("model"),
        "schema_version": record.get("schema_version"),
        "missing_record_keys": missing,
        "choice": raw_answer.get("choice"),
        "confidence": record.get("confidence"),
        "probabilities": record.get("probabilities"),
        "usage": record.get("usage"),
        "decider_latency_ms": record.get("decider_latency_ms"),
        "legs": [leg.get("purpose") for leg in record.get("legs", [])],
        "decision_provider": record.get("decision_provider"),
        "fell_back": record.get("fell_back"),
        "fallback_reason": record.get("fallback_reason"),
        "bypass_reason": record.get("bypass_reason"),
        "options": len(options.candidates),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if missing or not record:
        print("LANE_A_SMOKE_RECORD_INVALID")
        return 2
    if record.get("fell_back") or record.get("bypass_reason"):
        print("LANE_A_LIVE_SMOKE_FELL_BACK")
        return 0
    print(f"LANE_A_LIVE_SMOKE_RECORDED options={len(options.candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
