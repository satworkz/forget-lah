"""Runtime-facing fixtures and archive assembly for the M2 replay producer.

Gap 2 — source fixtures. A corpus item's `environment.fixtures.source_api` is a list of
`{"call", "result"}` entries. `source_transport` serves those results by call name over an
`httpx.MockTransport`, falling back to the harness's frozen default transport for anything the item
does not pin. An empty `source_api` therefore means "use the harness default", which is what the M1
and pilot items currently declare.

Gap 3 — provenance. `archive_record` builds the archive with a `source_run` block that names the
model actually used. A deterministic test double must be recorded as such; it is never presented as a
live model.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

ARCHIVE_VERSION = "1"


def source_transport(
    variant: Mapping[str, Any],
    fallback: Callable[[httpx.Request], httpx.Response] | None = None,
) -> httpx.MockTransport:
    """Serve the item's frozen `source_api` results, delegating anything else to `fallback`.

    A fixture `call` is matched against the request path either as a suffix or as its final segment,
    so both the runtime's episode paths (`followup-context/<episode>`,
    `followup/<episode>/confirm`) and bare names (`availability`) are addressable.
    """
    fixtures = (variant.get("environment") or {}).get("fixtures") or {}
    results = {
        entry["call"]: entry["result"]
        for entry in (fixtures.get("source_api") or [])
        if isinstance(entry, Mapping) and "call" in entry
    }

    def _matches(call: str, path: str) -> bool:
        trimmed = path.rstrip("/")
        return trimmed.endswith(call) or trimmed.rsplit("/", 1)[-1] == call

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for call, result in results.items():
            if _matches(call, path):
                return httpx.Response(200, json=result)
        if fallback is not None:
            return fallback(request)
        return httpx.Response(404, json={"error": f"no frozen source fixture for {path!r}"})

    return httpx.MockTransport(handler)


def variant_tools(variant: Mapping[str, Any], fallback: httpx.MockTransport) -> httpx.MockTransport:
    """Wrap a base source transport so `followup-context` carries the item's approved instructions.

    Without this the runtime answers from the harness-default clinic note, so a cited
    `instruction_id` is never the one the corpus authored.
    """
    fixtures = (variant.get("environment") or {}).get("fixtures") or {}
    instructions = fixtures.get("approved_instructions") or []

    def handler(request: httpx.Request) -> httpx.Response:
        response = fallback.handle_request(request)
        if (
            not instructions
            or response.status_code != 200
            or "followup-context" not in request.url.path
        ):
            return response
        payload = json.loads(response.content)
        payload["instructions"] = [
            {
                "instruction_id": entry["instruction_id"],
                "version": "1",
                "locale": "en-SG",
                "approved_text": entry["approved_text"],
                "synthetic": True,
            }
            for entry in instructions
        ][:5]
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def source_run_provenance(
    variant: Mapping[str, Any],
    *,
    model_id: str,
    request_id: str,
    runtime_commit: str | None = None,
) -> dict[str, Any]:
    """Provenance for the execution an archive reproduces."""
    profile = (variant.get("environment") or {}).get("translation_profile") or {}
    clock = variant.get("clock") or {}
    return {
        "runtime_commit": runtime_commit or profile.get("runtime_commit"),
        "model_id": model_id,
        "prompt_version": profile.get("prompt_version"),
        "started_at": clock.get("reference_datetime"),
        "request_id": request_id,
    }


def archive_record(
    variant: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    model_id: str,
    request_id: str,
    runtime_commit: str | None = None,
    translation_status: str = "ok",
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a replay archive. `evidence` carries hashes/references only."""
    identity = variant.get("identity") or {}
    return {
        "replay_version": ARCHIVE_VERSION,
        "variant_id": identity.get("variant_id"),
        "execution_origin": "replay",
        "source_run": source_run_provenance(
            variant, model_id=model_id, request_id=request_id, runtime_commit=runtime_commit
        ),
        "translation_status": translation_status,
        "observed": dict(observed),
        "evidence": dict(evidence or {}),
    }


def write_archive(record: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return target
