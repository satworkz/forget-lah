import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from test_runtime import drain, event, start

from forget_lah import db as db_mod
from forget_lah.corpus.replay import grade
from forget_lah.corpus.runtime_fixtures import archive_record, source_transport, write_archive
from forget_lah.corpus.runtime_mapping import observation_from_runtime
from forget_lah.detector import detect
from forget_lah.runtime.models import AgentRun
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "development" / "pilot"


@pytest.fixture
def runtime(store, signed_client):
    factory = store[1]
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    return factory, signed_client, Settings(agent_min_interval_seconds=0, _env_file=None)


def _terminal(run_status: str, checkpoint: dict) -> dict:
    if run_status == "waiting":
        return {
            "kind": "waiting",
            "run_status": "waiting",
            "wait_reason": checkpoint.get("wait_reason"),
            "intended": True,
        }
    if run_status == "completed":
        outcome = checkpoint.get("outcome")
        kind = (
            "completed_handoff"
            if outcome == "OWNED_STAFF_HANDOFF"
            else "completed_simulated_confirmation"
        )
        return {"kind": kind, "run_status": "completed", "outcome": outcome}
    if run_status == "paused":
        return {
            "kind": "failure",
            "run_status": "paused",
            "failure_code": checkpoint.get("pause_reason"),
        }
    if run_status == "escalated":
        return {"kind": "escalated", "run_status": "escalated", "outcome": None}
    raise AssertionError(f"unmapped run status {run_status!r}")


def test_source_transport_serves_item_fixtures_and_delegates_the_rest() -> None:
    variant = {
        "environment": {
            "fixtures": {
                "source_api": [
                    {
                        "call": "followup-context/DEMO-DENTAL-RECALL-01",
                        "result": {"episode": "DEMO-DENTAL-RECALL-01", "slots": []},
                    },
                    {"call": "availability", "result": {"slots": []}},
                ]
            }
        }
    }
    transport = source_transport(variant)
    episode = transport.handle_request(
        httpx.Request("GET", "http://clinic/internal/followup-context/DEMO-DENTAL-RECALL-01")
    )
    assert episode.status_code == 200
    assert episode.json()["episode"] == "DEMO-DENTAL-RECALL-01"
    bare = transport.handle_request(httpx.Request("GET", "http://clinic/availability"))
    assert bare.json() == {"slots": []}
    missing = transport.handle_request(httpx.Request("GET", "http://clinic/internal/unknown"))
    assert missing.status_code == 404


def test_producer_drives_a_variant_and_writes_a_gradable_archive(
    runtime, monkeypatch, tmp_path
) -> None:
    variant = json.loads((PILOT / "ambiguous-01-en.json").read_text())
    fixed = datetime.fromisoformat(variant["clock"]["reference_datetime"]).astimezone(UTC)
    monkeypatch.setattr(db_mod, "utcnow", lambda: fixed)

    factory, client, _ = runtime
    case_id, run_id = start(runtime)
    drain(runtime)

    patient_text = variant["conversation"][-1]["body"]
    assert event(client, case_id, "demo_reply", patient_text).status_code == 202
    drain(runtime)

    with factory() as db:
        run = db.get(AgentRun, run_id)
        checkpoint = dict(run.checkpoint)
        run_status = run.status

    observation = observation_from_runtime(
        variant,
        checkpoint=checkpoint,
        terminal=_terminal(run_status, checkpoint),
        memory_updates=[],
        delivery={
            "expected_block": None,
            "effective_language": variant["identity"]["language"],
            "expected_message_delivery": [],
        },
    )
    record = archive_record(variant, observation, model_id="mock-deterministic", request_id=run_id)
    path = write_archive(record, tmp_path / f"{variant['identity']['variant_id']}.json")

    reloaded = json.loads(path.read_text())
    assert reloaded["execution_origin"] == "replay"
    assert reloaded["source_run"]["model_id"] == "mock-deterministic"
    assert reloaded["observed"]["observation_version"] == "1"
    assert reloaded["variant_id"] == variant["identity"]["variant_id"]

    result = grade(variant, observation)
    assert result["grade"] in {"PASS", "FAILED", "UNSCORED"}
    assert result["origin"] == "replay"
