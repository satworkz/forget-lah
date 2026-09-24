import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_runtime import event, source_tools, start

from forget_lah.api import create_app
from forget_lah.corpus.recording import RecordingModel, recording_document
from forget_lah.corpus.replay import grade
from forget_lah.corpus.runtime_fixtures import archive_record, write_archive
from forget_lah.corpus.runtime_mapping import (
    build_delivery,
    build_memory,
    observation_from_runtime,
)
from forget_lah.detector import detect
from forget_lah.runtime.engine import claim_run, process_run
from forget_lah.runtime.models import AgentRun, AgentStep
from forget_lah.runtime.provider import AnthropicModel
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "development" / "pilot"
RECORDINGS = ROOT / "corpus" / "development" / "recordings"
ARCHIVES = ROOT / "corpus" / "development" / "archives"
ENV_FILE = ROOT / ".env"

pytestmark = pytest.mark.live


def _load_env(monkeypatch) -> bool:
    """Load the untracked .env into this test's environment only; never export it globally."""
    if not ENV_FILE.exists():
        return False
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    for key, value in values.items():
        if value:
            monkeypatch.setenv(key, value)
    return bool(values.get("ANTHROPIC_API_KEY"))


@pytest.fixture
def live(store, monkeypatch):
    if os.environ.get("RUN_LIVE_RECORDING") != "1":
        pytest.skip("set RUN_LIVE_RECORDING=1 to record against the live model")
    if not _load_env(monkeypatch):
        pytest.skip("no ANTHROPIC_API_KEY in .env")
    engine, factory = store
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    settings = Settings(
        app_env="test",
        database_url="sqlite://",
        public_origin="http://localhost:8080",
        agent_model_mode="anthropic",
        multilingual_enabled=True,
        patient_simulator_enabled=True,
        agent_min_interval_seconds=0,
        _env_file=None,
    )
    assert settings.translation_configured, "multilingual gate must be open for a corpus recording"
    with TestClient(create_app(settings, engine), base_url="http://localhost:8080") as client:
        client.post(
            "/api/auth/login",
            headers={"Origin": "http://localhost:8080"},
            json={"email": "staff@forget-lah.example", "password": TEST_PASSWORD},
        ).raise_for_status()
        yield factory, client, settings


def _drain_until_idle(runtime, model, *, seconds: int = 180) -> int:
    """Claim and process until nothing is queued/running, waiting out retry backoffs."""
    factory, _, settings = runtime
    deadline = time.monotonic() + seconds
    processed = 0
    while time.monotonic() < deadline:
        claim = claim_run(factory)
        if claim is not None:
            process_run(factory, settings, *claim, model=model, tools=source_tools())
            processed += 1
            continue
        with factory() as db:
            rows = db.execute(
                select(AgentRun.status, AgentRun.available_at).where(
                    AgentRun.status.in_(["queued", "running"])
                )
            ).all()
        if not rows:
            break
        now = datetime.now(UTC)
        waits = []
        for status, available_at in rows:
            if status == "running":
                waits.append(5.0)
            elif available_at is None:
                waits.append(0.0)
            else:
                due = (
                    available_at.replace(tzinfo=UTC)
                    if available_at.tzinfo is None
                    else available_at
                )
                waits.append(max(0.0, (due - now).total_seconds()))
        nap = min(5.0, min(waits)) if waits else 0.5
        time.sleep(max(nap, 0.5))
    return processed


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


VARIANT = os.environ.get("RECORD_VARIANT", "fam-ambiguous-01-en")


def test_record_a_live_decision_stream(live) -> None:
    """Drive one pilot variant with the real Anthropic model and record its decisions."""
    variant = json.loads((PILOT / f"{VARIANT.removeprefix('fam-')}.json").read_text())
    factory, client, settings = live
    records: list[dict] = []
    recorder = RecordingModel(AnthropicModel(settings), records)

    case_id, run_id = start(live)
    _drain_until_idle(live, recorder)
    patient_text = variant["conversation"][-1]["body"]
    response = event(client, case_id, "demo_reply", patient_text)
    for _ in range(3):
        if response.status_code == 202:
            break
        response = event(client, case_id, "demo_reply", patient_text)
    assert response.status_code == 202, response.text
    _drain_until_idle(live, recorder)

    with factory() as db:
        run = db.get(AgentRun, run_id)
        run_status = run.status
        checkpoint = dict(run.checkpoint)
        run_available_at = run.available_at.isoformat() if run.available_at else None
        run_lease_until = run.lease_until.isoformat() if run.lease_until else None
        steps = db.scalars(select(AgentStep).where(AgentStep.run_id == run_id)).all()
        step_diagnostics = [(step.status, step.error_code, step.attempts) for step in steps]
        updates = [
            update
            for step in steps
            if step.decision
            for update in (step.decision.get("updates") or [])
        ]
        step_payloads = [{"tool_result": step.tool_result} for step in steps if step.tool_result]

    assert records, "the live model produced no decisions to record"

    document = recording_document(
        variant["identity"]["variant_id"],
        settings.anthropic_model,
        records,
    )
    document["run_status"] = run_status
    document["run_diagnostics"] = {
        "available_at": run_available_at,
        "lease_until": run_lease_until,
        "steps": step_diagnostics,
    }
    target = RECORDINGS / f"{variant['identity']['variant_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")

    reloaded = json.loads(target.read_text())
    assert reloaded["model_id"] == settings.anthropic_model
    assert reloaded["records"]

    # Resolution B: grade the observation captured during the recorded run. The archive's `observed`
    # block is captured evidence, not a re-derivation, so no engine re-execution is needed.
    observation = observation_from_runtime(
        variant,
        checkpoint=checkpoint,
        terminal=_terminal(run_status, checkpoint),
        memory_updates=build_memory(updates),
        delivery={
            "expected_block": None,
            "effective_language": variant["identity"]["language"],
            "expected_message_delivery": build_delivery(
                step_payloads,
                [
                    turn["turn_id"]
                    for turn in variant["conversation"]
                    if turn.get("origin") == "replay"
                ],
            ),
        },
    )
    archive = archive_record(
        variant,
        observation,
        model_id=settings.anthropic_model,
        request_id=run_id,
        translation_status="ok",
        evidence={
            "recording": target.name,
            "recorded_decisions": len(records),
            "observed_run_status": run_status,
        },
    )
    archive["verdict"] = grade(variant, observation)
    archive_path = write_archive(archive, ARCHIVES / f"{variant['identity']['variant_id']}.json")
    persisted = json.loads(archive_path.read_text())
    assert persisted["verdict"]["grade"] in {"PASS", "FAILED", "UNSCORED"}
    assert persisted["source_run"]["model_id"] == settings.anthropic_model
