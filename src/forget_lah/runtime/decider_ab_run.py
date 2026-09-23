"""Lane B runner: drives the repository's own scenario shapes and writes the artifacts.

Usage (from the repository root):

    UV_PROJECT_ENVIRONMENT=/tmp/opencode/forget-lah-venv \
    uv run python -m forget_lah.runtime.decider_ab_run --out /tmp/opencode/lane-b

The runner is measurement-only. It never writes to the repository: the corpus, the results
JSON and the scorecard all land in `--out`. Live arms refuse to start when a credential is
absent, and every arm is skipped rather than half-run when it does not fit the call budget.
Credentials are read into the process environment only, never printed and never written.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from forget_lah.api import create_app
from forget_lah.db import FollowupCase, make_engine, session_factory, uid
from forget_lah.detector import detect
from forget_lah.runtime import decider_ab as ab
from forget_lah.runtime.clinic_tools import ClinicTools
from forget_lah.runtime.decider import DeciderModel, derive_options
from forget_lah.runtime.engine import claim_run, process_run
from forget_lah.runtime.models import AgentRun, AgentStep
from forget_lah.runtime.policy import policy_for
from forget_lah.runtime.provider import (
    AnthropicModel,
    MockModel,
    decision_formats_for,
    model_for,
)
from forget_lah.seed import seed
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_PASSWORD = "lane-b-harness-only-not-a-live-credential"
TEST_EMAIL = "staff@forget-lah.example"

LOCAL_KEV_4B = "http://172.17.0.1:8009"
LOCAL_KEV_27B = "http://127.0.0.1:8011"
HOSTED_PROVIDER = "https://api.commandcode.ai/provider"
DEFAULT_DECIDER_KEY_FILE = "/root/.config/opencode-cmd-azjam969ifr7/cc-provider.key"

MAX_DRAIN_STEPS = 45


class BudgetStop(RuntimeError):
    """Raised inside an arm that would exceed its own call allotment."""


@dataclass(frozen=True)
class Scenario:
    name: str
    specialty: str
    events: tuple[tuple[str, str], ...]


SCENARIOS: dict[str, Scenario] = {
    "dental-mixed-reply": Scenario(
        name="dental-mixed-reply",
        specialty="dental",
        events=(("demo_reply", "Next Friday please. What should I bring?"),),
    ),
    "myopia-mixed-reply": Scenario(
        name="myopia-mixed-reply",
        specialty="myopia",
        events=(("demo_reply", "Next Friday please. What should I bring?"),),
    ),
}


# -- credentials -------------------------------------------------------------------------


def read_secret(source: str | None, name: str) -> tuple[str | None, dict]:
    """Return a secret and a non-secret description; the value is never printed."""
    if not source:
        return None, {"present": False, "origin": "unset"}
    path = Path(source)
    if not path.is_file():
        return None, {"present": False, "origin": str(path), "error": "missing_file"}
    text = path.read_text()
    key = ""
    if "=" in text:
        for line in text.splitlines():
            field, _, value = line.strip().partition("=")
            if field.strip() == name:
                key = value.strip().strip('"').strip("'")
                break
    else:
        key = text.strip()
    if not key:
        return None, {"present": False, "origin": str(path), "error": "value_absent"}
    return key, {
        "present": True,
        "origin": str(path),
        "sha256_prefix": hashlib.sha256(key.encode()).hexdigest()[:12],
    }


def anthropic_credential(source: str | None) -> tuple[str | None, dict]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key, {
            "present": True,
            "origin": "environment",
            "sha256_prefix": hashlib.sha256(key.encode()).hexdigest()[:12],
        }
    return read_secret(source, "ANTHROPIC_API_KEY")


def decider_credential(source: str | None) -> tuple[str | None, dict]:
    key = os.environ.get("AGENT_DECIDER_API_KEY", "").strip()
    if key:
        return key, {
            "present": True,
            "origin": "environment",
            "sha256_prefix": hashlib.sha256(key.encode()).hexdigest()[:12],
        }
    value, description = read_secret(source, "AGENT_DECIDER_API_KEY")
    if value:
        os.environ["AGENT_DECIDER_API_KEY"] = value
    return value, description


# -- runtime -----------------------------------------------------------------------------


@dataclass
class Runtime:
    workdir: Path
    url: str
    engine: Any
    factory: Any
    settings: Settings
    client: TestClient


@dataclass(frozen=True)
class Arm:
    name: str
    mode: str
    decider: bool
    decider_url: str | None = None
    scenario: str | None = None
    allotment: int = 0
    paired: bool = False


def settings_for(
    url: str,
    arm: Arm,
    *,
    decider_url: str | None = None,
    record: Path | None = None,
    anthropic_key: str | None = None,
    gate: dict | None = None,
) -> Settings:
    kwargs: dict[str, Any] = {
        "app_env": "test",
        "database_url": url,
        "public_origin": "http://localhost:8080",
        "agent_min_interval_seconds": 0,
        "agent_step_delay_seconds": 0,
        "agent_model_mode": arm.mode,
        "agent_decider_enabled": arm.decider,
    }
    if decider_url:
        kwargs["agent_decider_url"] = decider_url
    if record:
        kwargs["agent_decider_record"] = str(record)
    if anthropic_key:
        kwargs["anthropic_api_key"] = anthropic_key
    if gate:
        kwargs["agent_decider_gate_mode"] = gate["mode"]
        kwargs["agent_decider_min_confidence"] = gate["min_confidence"]
        kwargs["agent_decider_min_probability"] = gate["min_probability"]
        kwargs["agent_decider_min_margin"] = gate["min_margin"]
    return Settings(**kwargs)


def build_runtime(
    workdir: Path,
    arm: Arm,
    *,
    decider_url: str | None = None,
    record: Path | None = None,
    anthropic_key: str | None = None,
    gate: dict | None = None,
) -> Runtime:
    workdir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{(workdir / 'lane-b.sqlite').as_posix()}"
    settings = settings_for(
        url,
        arm,
        decider_url=decider_url,
        record=record,
        anthropic_key=anthropic_key,
        gate=gate,
    )
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(url)
    factory = session_factory(engine)
    seed(factory, TEST_EMAIL, TEST_PASSWORD)
    from services.mock_clinic.fixtures import candidates

    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    client = TestClient(create_app(settings, engine), base_url="http://localhost:8080")
    client.__enter__()
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:8080"},
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    if response.status_code != 200:
        raise RuntimeError(f"harness login failed: {response.status_code}")
    return Runtime(workdir, url, engine, factory, settings, client)


def source_tools() -> ClinicTools:
    from services.mock_clinic.fixtures import followup_context

    return ClinicTools(
        "http://clinic",
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=followup_context(request.url.path.rsplit("/", 1)[-1])
            )
        ),
    )


# -- the app's own scenario driver -------------------------------------------------------


def headers(client: TestClient) -> dict:
    return {
        "Origin": "http://localhost:8080",
        "X-CSRF-Token": client.cookies.get("forget_lah_csrf"),
        "Idempotency-Key": uid(),
    }


def start(client: TestClient, specialty: str) -> tuple[str, str]:
    case = next(c for c in client.get("/api/cases").json() if c["specialty"] == specialty)
    response = client.post(
        f"/api/cases/{case['id']}/agent/runs",
        headers=headers(client),
        json={"expected_case_version": case["case_version"]},
    )
    if response.status_code != 202:
        raise RuntimeError(f"run start failed: {response.status_code} {response.text[:200]}")
    return case["id"], response.json()["run_id"]


def emit(client: TestClient, case_id: str, kind: str, content: str) -> int:
    snapshot = client.get(f"/api/cases/{case_id}/agent").json()
    response = client.post(
        f"/api/cases/{case_id}/agent/events",
        headers=headers(client),
        json={
            "expected_case_version": snapshot["case_version"],
            "run_id": snapshot["run"]["id"],
            "kind": kind,
            "content": content,
        },
    )
    return response.status_code


def drain(runtime: Runtime, *, model: Any, tools: ClinicTools) -> tuple[int, bool]:
    """Advance to the next durable checkpoint. Returns (steps, budget_stopped)."""
    steps = 0
    for _ in range(MAX_DRAIN_STEPS):
        claim = claim_run(runtime.factory)
        if claim is None:
            return steps, False
        try:
            process_run(runtime.factory, runtime.settings, *claim, model=model, tools=tools)
        except BudgetStop:
            return steps, True
        steps += 1
    raise RuntimeError("scenario did not reach a durable checkpoint within the step budget")


@dataclass
class CountingProvider:
    """Count an arm's own calls and stop the arm instead of exceeding its allotment.

    `start` is the leg's count when the arm begins, so the allotment bounds the arm rather
    than the whole run: replay calls already charged to the same leg must not exhaust it.
    """

    inner: Any
    leg: str
    ledger: ab.CallLedger
    allotment: int
    start: int = 0
    name = "lane-b-arm"

    def decide(self, observation: dict, *, repair: bool = False) -> Any:
        spent = self.ledger.counts.get(self.leg, 0) - self.start
        if spent >= self.allotment:
            raise BudgetStop(f"arm allotment {self.allotment} reached")
        self.ledger.charge(self.leg)
        return self.inner.decide(observation, repair=repair)


def drive_scenario(runtime: Runtime, *, model: Any, scenario: Scenario) -> dict:
    tools = source_tools()
    case_id, run_id = start(runtime.client, scenario.specialty)
    steps = 0
    stopped = False
    for kind, content in scenario.events:
        count, stopped = drain(runtime, model=model, tools=tools)
        steps += count
        if stopped:
            break
        emit(runtime.client, case_id, kind, content)
    if not stopped:
        count, stopped = drain(runtime, model=model, tools=tools)
        steps += count
    snapshot = runtime.client.get(f"/api/cases/{case_id}/agent").json()
    return {
        "case_id": case_id,
        "run_id": run_id,
        "steps_processed": steps,
        "budget_stopped": stopped,
        "snapshot": snapshot,
    }


def arm_metrics(result: dict, *, arm: Arm, calls: dict[str, int]) -> dict:
    snapshot = result.get("snapshot") or {}
    run = snapshot.get("run") or {}
    steps = snapshot.get("steps") or []
    failures: Counter = Counter()
    providers: Counter = Counter()
    for step in steps:
        for failure in step.get("validation_failures") or []:
            code = failure.get("code") if isinstance(failure, dict) else failure
            failures[str(code)] += 1
        providers[str(step.get("provider") or step.get("origin") or "unknown")] += 1
    for event in snapshot.get("events") or []:
        kind = str(event.get("kind") or "")
        if kind.startswith("MODEL_"):
            failures[kind] += 1
    repairs = sum(max(int(step.get("attempts") or 1) - 1, 0) for step in steps)
    denied = sum(1 for step in steps if (step.get("policy") or {}).get("decision") == "DENY")
    status = run.get("status")
    reached = status in {"waiting", "escalated", "completed", "paused"}
    if result.get("budget_stopped"):
        outcome = "INCOMPLETE_BUDGET"
    elif reached and not failures:
        outcome = "PASS"
    elif reached:
        outcome = "PASS_WITH_FAILURES"
    else:
        outcome = f"STOPPED_{status or 'unknown'}"
    return {
        "arm": arm.name,
        "mode": arm.mode,
        "decider": arm.decider,
        "decider_url": arm.decider_url,
        "scenario": arm.scenario,
        "status": status,
        "outcome": outcome,
        "steps": len(steps),
        "steps_processed": result.get("steps_processed"),
        "repairs": repairs,
        "events": len(snapshot.get("events") or []),
        "pause_outcomes": 1 if status == "waiting" else 0,
        "policy_denied": denied,
        "failure_codes": dict(sorted(failures.items())),
        "providers": dict(sorted(providers.items())),
        "wait_reason": run.get("wait_reason"),
        "pause_reason": run.get("pause_reason"),
        "run_outcome": run.get("outcome"),
        "calls": dict(sorted(calls.items())),
        "budget_stopped": bool(result.get("budget_stopped")),
    }


# -- paired replay arm -------------------------------------------------------------------


@dataclass
class LegPlan:
    leg: str
    call: Callable[[dict], Any]
    limit: int | None = None
    record: Path | None = None


def _plans(limits: dict[str, int], calls: dict[str, LegCall]) -> list[LegPlan]:
    """A leg with limit 0 is not measured at all; a negative limit means every observation."""
    plans = []
    for leg in (ab.LEG_KEV_4B, ab.LEG_KEV_27B, ab.LEG_HOSTED, ab.LEG_ANTHROPIC):
        if leg not in calls:
            continue
        limit = limits.get(leg, 0)
        if limit == 0:
            continue
        plans.append(LegPlan(leg, calls[leg].call, None if limit < 0 else limit, calls[leg].record))
    return plans


class PairedCapture:
    """Drive a mock arm while every planned leg decides the identical observation.

    The wrapper sits inside the engine's decision call, so the run/case/step rows are still
    current; that is what makes `policy_for` a real verdict instead of a replayed guess. The
    arm's own trajectory stays mock-driven, which is the off-policy caveat on this experiment.
    """

    name = "lane-b-paired"

    def __init__(
        self,
        runtime: Runtime,
        *,
        inner: Any,
        plans: Sequence[LegPlan],
        ledger: ab.CallLedger,
        rows: list[ab.ReplayRow],
        corpus_path: Path | None,
    ) -> None:
        self.runtime = runtime
        self.inner = inner
        self.plans = list(plans)
        self.ledger = ledger
        self.rows = rows
        self.corpus_path = corpus_path

    def decide(self, observation: dict, *, repair: bool = False) -> Any:
        index = len(self.rows) + 1
        outcomes: dict[str, ab.LegOutcome] = {}
        policy = self._policy(observation)
        source = self._patient_source(observation)
        for plan in self.plans:
            if plan.limit is not None and index > plan.limit:
                outcomes[plan.leg] = ab.skipped(plan.leg, "budget_subsample")
                continue
            outcomes[plan.leg] = ab.evaluate_leg(
                plan.leg,
                plan.call,
                observation,
                policy=policy,
                patient_source=source,
                charge=self.ledger.charge,
                record=plan.record,
            )
        row = ab.ReplayRow(
            index=index,
            role=str(observation.get("role") or "unknown"),
            phase=(observation.get("latest_event") or {}).get("kind"),
            repair=repair,
            legal_step_types=tuple(sorted(decision_formats_for(dict(observation)))),
            context=self._context(observation),
            observation=dict(observation),
            outcomes=outcomes,
        )
        self.rows.append(row)
        if self.corpus_path is not None:
            ab.write_rows(self.corpus_path, [row], append=True)
        return self.inner.decide(observation, repair=repair)

    def _ids(self, observation: dict):
        step_id = observation.get("request_id")
        with self.runtime.factory() as db:
            step = db.get(AgentStep, step_id) if step_id else None
            if step is None:
                return None
            run = db.get(AgentRun, step.run_id)
            case = db.get(FollowupCase, run.case_id) if run else None
            if run is None or case is None:
                return None
            return run.id, case.id, step.id, step.role

    def _context(self, observation: dict) -> dict:
        found = self._ids(observation)
        if found is None:
            return {"request_id": observation.get("request_id")}
        run_id, case_id, step_id, role = found
        return {"run_id": run_id, "case_id": case_id, "step_id": step_id, "role": role}

    def _policy(self, observation: dict) -> Callable[[Any], dict | None] | None:
        step_id = observation.get("request_id")

        def verdict(decision):
            with self.runtime.factory() as db:
                step = db.get(AgentStep, step_id) if step_id else None
                if step is None:
                    return None
                run = db.get(AgentRun, step.run_id)
                case = db.get(FollowupCase, run.case_id) if run else None
                if run is None or case is None:
                    return None
                return policy_for(db, run, case, step, decision)

        return verdict

    def _patient_source(self, observation: dict) -> str | None:
        latest = observation.get("latest_event") or {}
        content = latest.get("content")
        return content if isinstance(content, str) and content else None


# -- the run -----------------------------------------------------------------------------


@dataclass
class HarnessConfig:
    out: Path
    budget: int = 40
    limits: dict = None  # type: ignore[assignment]
    stability: int = 6
    stability_leg: str = ab.LEG_KEV_4B
    scenarios: tuple[str, ...] = ("dental-mixed-reply", "myopia-mixed-reply")
    closed_loop: bool = True
    dry_run: bool = False
    skip_live: bool = False
    anthropic_key_from: str | None = "/workspace/.env"
    decider_key_from: str | None = DEFAULT_DECIDER_KEY_FILE
    anthropic_allotment: int = 10
    gate: dict | None = None

    def __post_init__(self) -> None:
        if self.limits is None:
            self.limits = {
                ab.LEG_KEV_4B: -1,
                ab.LEG_KEV_27B: 8,
                ab.LEG_HOSTED: 5,
                ab.LEG_ANTHROPIC: 10,
            }
        if self.gate is None:
            defaults = Settings(database_url="sqlite://")
            self.gate = {
                "mode": defaults.agent_decider_gate_mode,
                "min_confidence": defaults.agent_decider_min_confidence,
                "min_probability": defaults.agent_decider_min_probability,
                "min_margin": defaults.agent_decider_min_margin,
                "source": "settings_default",
            }


@dataclass(frozen=True)
class LegCall:
    """One leg's callable plus the register its gate inputs are read back from."""

    call: Callable[[dict], Any]
    record: Path | None = None


@contextlib.contextmanager
def _decider_key_scope(url: str | None):
    """Present the decider key only to endpoints allowed to carry it.

    Production refuses a key over plain http (`endpoint_usable`), so a local http decider must
    be queried keyless. The key is process-wide, so each leg call scopes it to its own endpoint
    instead of letting a hosted leg's key invalidate every local endpoint.
    """
    key = os.environ.get("AGENT_DECIDER_API_KEY")
    try:
        if url and url.startswith("https://") and key:
            os.environ["AGENT_DECIDER_API_KEY"] = key
        else:
            os.environ.pop("AGENT_DECIDER_API_KEY", None)
        yield
    finally:
        if key is None:
            os.environ.pop("AGENT_DECIDER_API_KEY", None)
        else:
            os.environ["AGENT_DECIDER_API_KEY"] = key


def _scoped(call: Callable[..., Any], url: str | None) -> Callable[..., Any]:
    def wrapped(observation: dict, *, repair: bool = False) -> Any:
        with _decider_key_scope(url):
            return call(observation, repair=repair)

    return wrapped


def leg_calls(
    runtime: Runtime, config: HarnessConfig, anthropic_key: str | None, *, dry_run: bool
) -> dict[str, LegCall]:
    """One leg per callable; in dry-run every leg is the deterministic mock."""
    if dry_run:
        mock = MockModel()
        return {
            leg: LegCall(mock.decide)
            for leg in (ab.LEG_KEV_4B, ab.LEG_KEV_27B, ab.LEG_HOSTED, ab.LEG_ANTHROPIC)
        }
    llm = settings_for(
        runtime.url,
        Arm("leg-llm", "anthropic", False),
        anthropic_key=anthropic_key,
    )
    calls: dict[str, LegCall] = {
        ab.LEG_ANTHROPIC: LegCall(AnthropicModel(llm).decide),
    }
    for leg, url in (
        (ab.LEG_KEV_4B, LOCAL_KEV_4B),
        (ab.LEG_KEV_27B, LOCAL_KEV_27B),
        (ab.LEG_HOSTED, HOSTED_PROVIDER),
    ):
        record = config.out / f"decider-{leg}.jsonl"
        settings = settings_for(
            runtime.url,
            Arm(f"leg-{leg}", "mock", True, decider_url=url),
            decider_url=url,
            record=record,
            gate=config.gate,
        )
        model = DeciderModel(settings, MockModel(), inner_name="mock", event_kind="lane-b-replay")
        calls[leg] = LegCall(_scoped(model.decide, url), record)
    return calls


def run_paired_capture(
    config: HarnessConfig,
    *,
    ledger: ab.CallLedger,
    anthropic_key: str | None,
    credential: dict,
) -> tuple[list[ab.ReplayRow], dict]:
    arm = Arm(name="paired-capture", mode="mock", decider=False, paired=True)
    runtime = build_runtime(config.out / "paired", arm, gate=config.gate)
    rows: list[ab.ReplayRow] = []
    corpus_path = config.out / "corpus.jsonl"
    if corpus_path.exists():
        corpus_path.unlink()
    calls = leg_calls(runtime, config, anthropic_key, dry_run=config.dry_run)
    limits = dict(config.limits)
    if config.skip_live:
        limits = {ab.LEG_KEV_4B: -1}
    if not credential.get("present") and not config.dry_run:
        limits.pop(ab.LEG_ANTHROPIC, None)
    plans = _plans(limits, calls)
    paired = PairedCapture(
        runtime,
        inner=model_for(runtime.settings, "mock"),
        plans=plans,
        ledger=ledger,
        rows=rows,
        corpus_path=corpus_path,
    )
    scenarios = []
    for name in config.scenarios:
        result = drive_scenario(runtime, model=paired, scenario=SCENARIOS[name])
        scenarios.append(
            {
                "scenario": name,
                "steps": result["steps_processed"],
                "status": (result["snapshot"].get("run") or {}).get("status"),
            }
        )
    return rows, {
        "scenarios": scenarios,
        "corpus_path": str(corpus_path),
        "plans": [{"leg": plan.leg, "limit": plan.limit} for plan in plans],
    }


def run_closed_loop_arm(
    config: HarnessConfig,
    arm: Arm,
    *,
    ledger: ab.CallLedger,
    anthropic_key: str | None,
    credential: dict,
) -> dict:
    """One arm drives one whole scenario; the comparison is the end-to-end run state."""
    live_llm = arm.mode == "anthropic" and not config.dry_run
    if live_llm and not credential.get("present"):
        return {
            "arm": arm.name,
            "status": "SKIPPED",
            "reason": "no_anthropic_credential",
            "scenario": arm.scenario,
        }
    if arm.allotment and not ledger.fits(arm.allotment):
        return {
            "arm": arm.name,
            "status": "SKIPPED",
            "reason": f"budget: needs {arm.allotment}, {ledger.remaining} remain",
            "scenario": arm.scenario,
        }
    workdir = config.out / f"arm-{arm.name}"
    if workdir.exists():
        shutil.rmtree(workdir)
    # A dry run must not touch the network or require credentials, so the effective arm is
    # mock-only while the reported arm keeps its real label.
    effective = (
        Arm(name=arm.name, mode="mock", decider=False, scenario=arm.scenario)
        if config.dry_run
        else arm
    )
    runtime = build_runtime(
        workdir,
        effective,
        decider_url=effective.decider_url,
        record=workdir / "decider.jsonl",
        anthropic_key=anthropic_key,
        gate=config.gate,
    )
    inner = model_for(runtime.settings, effective.mode)
    leg = ab.LEG_ANTHROPIC if arm.mode == "anthropic" else ab.LEG_MOCK
    if config.dry_run or not arm.allotment:
        model: Any = inner
    else:
        model = CountingProvider(
            inner=inner,
            leg=leg,
            ledger=ledger,
            allotment=arm.allotment,
            start=ledger.counts.get(leg, 0),
        )
    before = dict(ledger.counts)
    # The arm's decider may be a keyless local endpoint; scope the key so a hosted leg's
    # credential cannot make the local endpoint look invalid.
    decider_url = effective.decider_url if effective.decider else None
    with _decider_key_scope(decider_url):
        result = drive_scenario(runtime, model=model, scenario=SCENARIOS[arm.scenario])
    delta = {
        name: count - before.get(name, 0)
        for name, count in ledger.counts.items()
        if count - before.get(name, 0)
    }
    metrics = arm_metrics(result, arm=arm, calls=delta)
    metrics["decider_record"] = str(workdir / "decider.jsonl")
    return metrics


def run_stability(
    config: HarnessConfig, rows: Sequence[ab.ReplayRow], *, ledger: ab.CallLedger
) -> dict:
    from forget_lah.runtime.decider import DeciderModel as Model

    if config.dry_run:
        return {"status": ab.SKIPPED, "reason": "dry_run"}
    for row in rows:
        outcome = row.outcomes.get(config.stability_leg)
        if outcome is None or outcome.status != ab.REPLAY:
            continue
        if len(derive_options(row.observation).candidates) < 2:
            continue
        record = config.out / "decider-stability.jsonl"
        if record.exists():
            record.unlink()
        settings = settings_for(
            "sqlite://",
            Arm("stability", "mock", True, decider_url=LOCAL_KEV_4B),
            decider_url=LOCAL_KEV_4B,
            record=record,
            gate=config.gate,
        )
        call = Model(settings, MockModel(), inner_name="mock", event_kind="lane-b-stability").decide
        with _decider_key_scope(LOCAL_KEV_4B):
            return ab.order_stability(
                call,
                row.observation,
                leg=config.stability_leg,
                n=config.stability,
                charge=ledger.charge,
                record=record,
            )
    return {"status": ab.SKIPPED, "reason": "no_observation_with_two_options"}


def compose_verdict(results: dict) -> str:
    """State only what the measurements support; refuse any claim beyond the corpus."""
    if results.get("dry_run"):
        return (
            "DRY RUN: every leg was the deterministic mock, so nothing here is a measurement. "
            "The output only proves the harness plumbing and the artifact writing work."
        )
    corpus = results.get("corpus") or {}
    replay = results.get("replay") or {}
    legs = replay.get("legs") or {}
    arms = results.get("closed_loop") or []
    observations = corpus.get("observations") or 0
    if not observations:
        return "No corpus was captured, so no paired comparison exists."
    parts = [
        f"Measured on {observations} recorded decision points; the corpus is mock-driven, so the "
        "paired replay is off-policy: a state is not caused by the leg being measured."
    ]
    llm = legs.get(ab.LEG_ANTHROPIC) or {}
    if llm.get("ran"):
        validity = llm.get("contract_validity_rate")
        allowed = llm.get("policy_allow_rate")
        parts.append(
            f"The LLM leg produced {llm.get('ran')} replies, "
            f"contract-valid {validity if validity is not None else 'n/a'}, "
            f"policy-ALLOW {allowed if allowed is not None else 'n/a'}."
        )
    else:
        parts.append("The LLM leg did not run, so no LLM-versus-decider statement is supported.")
    for leg in (ab.LEG_KEV_4B, ab.LEG_KEV_27B, ab.LEG_HOSTED):
        summary = legs.get(leg)
        if not summary:
            continue
        if not summary.get("ran"):
            parts.append(f"`{leg}` produced no replies.")
            continue
        parts.append(
            f"`{leg}`: contract-valid {summary.get('contract_validity_rate')}, "
            f"policy-ALLOW {summary.get('policy_allow_rate')}, "
            f"abstain {summary.get('abstain_rate')} (causes {summary.get('fallback_causes')}), "
            f"p50 {summary.get('latency_ms', {}).get('p50')} ms."
        )
    for pair, value in sorted((replay.get("agreement") or {}).items()):
        parts.append(
            f"Agreement `{pair}`: step type {value.get('step_type')}, "
            f"type+reason {value.get('step_type_and_reason')}, full {value.get('full')} "
            f"on {value.get('n_compared')} comparable observations."
        )
    stability = results.get("stability") or {}
    if stability.get("status") == ab.REPLAY:
        parts.append(
            f"Order stability: flip rate {stability.get('flip_rate_vs_canonical')} over "
            f"{stability.get('n')} shuffled presentations, {stability.get('distinct_choices')} "
            "distinct choices."
        )
    parts.append(
        "Agreement is not accuracy and this run has no human-adjudicated correctness labels, so "
        "no claim that either leg decides better is supported; the supported axes are contract "
        "validity, policy admissibility, stability, latency and cost."
    )
    measured = [arm.get("arm") for arm in arms if arm.get("outcome")]
    skipped = [
        f"{arm.get('arm')} ({arm.get('reason')})" for arm in arms if arm.get("status") == "SKIPPED"
    ]
    if measured:
        parts.append(f"Closed-loop arms that completed: {', '.join(measured)}.")
    if skipped:
        parts.append(f"Closed-loop arms skipped: {', '.join(skipped)}.")
    uncovered = corpus.get("uncovered_legal_step_types") or []
    if uncovered:
        parts.append(f"Unmeasured decision classes: {', '.join(uncovered)}.")
    parts.append(f"Call budget: {json.dumps(results.get('budget') or {}, sort_keys=True)}.")
    return " ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lane B LLM vs decider A/B harness")
    parser.add_argument("--out", default="/tmp/opencode/lane-b")
    parser.add_argument("--budget", type=int, default=40)
    parser.add_argument("--anthropic-replay", type=int, default=10)
    parser.add_argument("--hosted-replay", type=int, default=5)
    parser.add_argument("--kev27b-replay", type=int, default=8)
    parser.add_argument("--stability", type=int, default=6)
    parser.add_argument("--stability-leg", default=ab.LEG_KEV_4B)
    parser.add_argument("--scenarios", default="dental-mixed-reply,myopia-mixed-reply")
    parser.add_argument("--no-closed-loop", dest="closed_loop", action="store_false")
    parser.add_argument(
        "--corpus",
        default=None,
        help="Reuse a captured corpus instead of paying for a new paired capture.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--anthropic-key-from", default="/workspace/.env")
    parser.add_argument("--decider-key-from", default=DEFAULT_DECIDER_KEY_FILE)
    parser.add_argument("--anthropic-allotment", type=int, default=10)
    parser.add_argument("--gate-mode", default=None)
    parser.add_argument("--gate-min-confidence", type=float, default=None)
    parser.add_argument("--gate-min-probability", type=float, default=None)
    parser.add_argument("--gate-min-margin", type=float, default=None)
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    defaults = Settings(database_url="sqlite://")
    gate = {
        "mode": args.gate_mode or defaults.agent_decider_gate_mode,
        "min_confidence": args.gate_min_confidence
        if args.gate_min_confidence is not None
        else defaults.agent_decider_min_confidence,
        "min_probability": args.gate_min_probability
        if args.gate_min_probability is not None
        else defaults.agent_decider_min_probability,
        "min_margin": args.gate_min_margin
        if args.gate_min_margin is not None
        else defaults.agent_decider_min_margin,
        "source": "cli"
        if any(
            value is not None
            for value in (
                args.gate_mode,
                args.gate_min_confidence,
                args.gate_min_probability,
                args.gate_min_margin,
            )
        )
        else "settings_default",
    }
    config = HarnessConfig(
        out=Path(args.out),
        budget=args.budget,
        limits={
            ab.LEG_KEV_4B: -1,
            ab.LEG_KEV_27B: args.kev27b_replay,
            ab.LEG_HOSTED: args.hosted_replay,
            ab.LEG_ANTHROPIC: args.anthropic_replay,
        },
        stability=args.stability,
        stability_leg=args.stability_leg,
        scenarios=tuple(name for name in args.scenarios.split(",") if name),
        closed_loop=args.closed_loop,
        dry_run=args.dry_run,
        skip_live=args.skip_live,
        anthropic_key_from=args.anthropic_key_from,
        decider_key_from=args.decider_key_from,
        anthropic_allotment=args.anthropic_allotment,
        gate=gate,
    )
    config.out.mkdir(parents=True, exist_ok=True)
    ledger = ab.CallLedger(limit=config.budget)
    anthropic_key, anthropic = anthropic_credential(config.anthropic_key_from)
    decider_key, decider = decider_credential(config.decider_key_from)
    if config.dry_run:
        anthropic_key, anthropic = None, {"present": False, "origin": "dry-run"}
        decider_key, decider = None, {"present": False, "origin": "dry-run"}
    print(f"LANE_B_CREDENTIAL anthropic={anthropic} decider={decider}", flush=True)
    del decider_key

    if args.corpus:
        corpus = Path(args.corpus)
        rows = ab.read_rows(corpus)
        capture_meta = {"source": "loaded", "corpus_path": str(corpus)}
    else:
        rows, capture_meta = run_paired_capture(
            config, ledger=ledger, anthropic_key=anthropic_key, credential=anthropic
        )
    print(f"LANE_B_CORPUS observations={len(rows)} at={capture_meta['corpus_path']}", flush=True)
    distribution = ab.corpus_distribution(rows)
    print(f"LANE_B_DISTRIBUTION {json.dumps(distribution, sort_keys=True)}", flush=True)

    decider_legs = [ab.LEG_KEV_4B, ab.LEG_KEV_27B, ab.LEG_HOSTED]
    replay = ab.aggregate(rows, decider_legs=decider_legs, llm_leg=ab.LEG_ANTHROPIC)
    replay["gate_sweep"] = ab.gate_sweep(rows, ab.LEG_KEV_4B, llm_leg=ab.LEG_ANTHROPIC)
    stability = run_stability(config, rows, ledger=ledger)
    print(f"LANE_B_STABILITY {json.dumps(stability, sort_keys=True, default=str)}", flush=True)

    arms: list[dict] = []
    if config.closed_loop:
        specs = [
            Arm("mock-control", "mock", False, scenario=config.scenarios[0]),
            Arm(
                "mock+decider",
                "mock",
                True,
                decider_url=LOCAL_KEV_4B,
                scenario=config.scenarios[0],
            ),
            Arm(
                "anthropic",
                "anthropic",
                False,
                scenario=config.scenarios[0],
                allotment=config.anthropic_allotment,
            ),
            Arm(
                "anthropic+decider",
                "anthropic",
                True,
                decider_url=LOCAL_KEV_4B,
                scenario=config.scenarios[0],
                allotment=config.anthropic_allotment,
            ),
        ]
        for arm in specs:
            arms.append(
                run_closed_loop_arm(
                    config, arm, ledger=ledger, anthropic_key=anthropic_key, credential=anthropic
                )
            )
            print(f"LANE_B_ARM {json.dumps(arms[-1], sort_keys=True, default=str)}", flush=True)

    results = {
        "command": "uv run python -m forget_lah.runtime.decider_ab_run "
        + " ".join(argv if argv is not None else sys.argv[1:]),
        "config": {
            "budget": config.budget,
            "limits": config.limits,
            "stability": config.stability,
            "scenarios": list(config.scenarios),
            "dry_run": config.dry_run,
            "gate": config.gate,
            "anthropic_allotment": config.anthropic_allotment,
        },
        "credentials": {"anthropic": anthropic, "decider": decider},
        "dry_run": config.dry_run,
        "corpus": distribution,
        "capture": capture_meta,
        "replay": replay,
        "stability": stability,
        "closed_loop": arms,
        "budget": ledger.as_dict(),
    }
    results["verdict"] = compose_verdict(results)
    (config.out / "results.json").write_text(
        json.dumps(results, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    (config.out / "scorecard.md").write_text(ab.scorecard_markdown(results), encoding="utf-8")
    print(f"LANE_B_RESULTS {config.out / 'results.json'}", flush=True)
    print(f"LANE_B_SCORECARD {config.out / 'scorecard.md'}", flush=True)
    print(f"LANE_B_BUDGET {json.dumps(ledger.as_dict(), sort_keys=True)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
