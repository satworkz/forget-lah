import json
import os
import time
from pathlib import Path

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_runtime import event, source_tools, start

from forget_lah.api import create_app
from forget_lah.corpus.recording import RecordingModel, recording_document
from forget_lah.detector import detect
from forget_lah.runtime.engine import claim_run, process_run
from forget_lah.runtime.models import AgentRun
from forget_lah.runtime.provider import AnthropicModel
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "development" / "pilot"
RECORDINGS = ROOT / "corpus" / "development" / "recordings"
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


def _drain_until_idle(runtime, model, *, seconds: int = 60) -> int:
    """Claim and process until nothing is queued/running, waiting out pacing timers."""
    factory, _, settings = runtime
    deadline = time.monotonic() + seconds
    processed = 0
    while time.monotonic() < deadline:
        claim = claim_run(factory)
        if claim is None:
            time.sleep(1)
            with factory() as db:
                pending = db.scalar(
                    select(func.count())
                    .select_from(AgentRun)
                    .where(AgentRun.status.in_(["queued", "running"]))
                )
            if not pending:
                break
            continue
        process_run(factory, settings, *claim, model=model, tools=source_tools())
        processed += 1
    return processed


def test_record_a_live_decision_stream(live) -> None:
    """Drive one pilot variant with the real Anthropic model and record its decisions."""
    variant = json.loads((PILOT / "ambiguous-01-en.json").read_text())
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

    assert records, "the live model produced no decisions to record"

    document = recording_document(
        variant["identity"]["variant_id"],
        settings.anthropic_model,
        records,
    )
    document["run_status"] = run_status
    target = RECORDINGS / f"{variant['identity']['variant_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")

    reloaded = json.loads(target.read_text())
    assert reloaded["model_id"] == settings.anthropic_model
    assert reloaded["records"]
