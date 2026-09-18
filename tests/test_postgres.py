import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from forget_lah.db import Base, FollowupCase, Principal, make_engine, session_factory, uid, utcnow
from forget_lah.detector import detect
from forget_lah.runtime.engine import claim_run, prepare_step
from forget_lah.runtime.models import AgentRun, ModelBudget
from forget_lah.seed import seed
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.worker import claim_job
from services.mock_clinic.fixtures import candidates


@pytest.mark.postgres
def test_postgres_simulator_migration_and_competing_editors(postgres_schema):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from fastapi.testclient import TestClient

    from services.mock_clinic.app import MockSettings, create_app
    from services.mock_clinic.bootstrap import migrate
    from services.mock_clinic.store import Base as SimulatorBase
    from services.mock_clinic.store import Episode, seed
    from tests.test_simulator import ADMIN, EPISODE, KEY, episode_body

    engine, factory = postgres_schema
    migrate(engine)
    seed(factory)
    settings = MockSettings(mock_database_url="sqlite://", mock_clinic_admin_key=KEY)
    with TestClient(create_app(settings, engine)) as client:
        body = episode_body(client)
        barrier = Barrier(2)

        def edit(note):
            barrier.wait(timeout=10)
            return client.put(
                f"/internal/admin/episodes/{EPISODE}",
                headers=ADMIN,
                json={**body, "doctor_note": note},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = [executor.submit(edit, note) for note in ("First edit", "Second edit")]
            assert sorted(f.result(timeout=20) for f in outcomes) == [200, 409]
    migrate(engine)
    seed(factory)
    with factory() as db:
        row = db.get(Episode, EPISODE)
        assert row.version == 2 and row.doctor_note in {"First edit", "Second edit"}
    with engine.connect() as connection:
        assert (
            compare_metadata(MigrationContext.configure(connection), SimulatorBase.metadata) == []
        )


@pytest.mark.postgres
def test_postgres_demo_reset_is_atomic_and_conflicting_resets_do_not_repeat(postgres_schema):
    from fastapi import HTTPException
    from sqlalchemy.exc import DBAPIError

    from forget_lah.demo_reset import lock_reset_tables, reset_demo

    _, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "head")
    seed(factory, "test@forget-lah.example", "postgres-test-only-password")
    source = candidates_from_payload(candidates())
    detect(factory, DEMO_CLINIC_ID, source)
    with factory() as db:
        old_ids = list(db.scalars(select(FollowupCase.id)))
    # An in-progress API/worker transaction makes reset fail promptly, with no deletion.
    with factory.begin() as holder:
        holder.scalar(select(FollowupCase).with_for_update().limit(1))
        with pytest.raises(DBAPIError), factory.begin() as contender:
            lock_reset_tables(contender)
    barrier = Barrier(2)

    def reset():
        barrier.wait(timeout=10)
        try:
            with factory.begin() as db:
                lock_reset_tables(db)
                return reset_demo(db, old_ids, source)["status"]
        except (DBAPIError, HTTPException):
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reset) for _ in range(2)]
        assert sorted(f.result(timeout=20) for f in futures) == ["conflict", "reset"]
    with factory() as db:
        new_ids = list(db.scalars(select(FollowupCase.id)))
        assert len(new_ids) == 3 and not set(old_ids).intersection(new_ids)
        assert db.get(ModelBudget, "organiser").calls == 0


@pytest.mark.postgres
def test_postgres_automatic_starters_queue_each_ready_case_once(postgres_schema):
    from forget_lah.runtime.startup import queue_ready_reviews
    from forget_lah.seed import seed_automation
    from forget_lah.settings import Settings
    from forget_lah.worker import finish_job

    _, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "head")
    seed(factory, "test@forget-lah.example", "postgres-test-only-password")
    seed_automation(factory)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    settings = Settings(agent_auto_start_enabled=False, _env_file=None)
    while claim := claim_job(factory):
        finish_job(factory, *claim, settings=settings)
    settings.agent_auto_start_enabled = True
    barrier = Barrier(2)

    def queue():
        barrier.wait(timeout=10)
        return queue_ready_reviews(factory, settings)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(queue) for _ in range(2)]
        assert sum(f.result(timeout=20) for f in futures) == 3
    with factory() as db:
        runs = list(db.scalars(select(AgentRun)))
        assert len(runs) == len({r.case_id for r in runs}) == 3
        assert {c.case_version for c in db.scalars(select(FollowupCase))} == {2}
    assert queue_ready_reviews(factory, settings) == 0


@pytest.mark.postgres
def test_postgres_workers_cannot_claim_the_same_job():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run actual PostgreSQL locking verification")
    engine = make_engine(url)
    assert engine.dialect.name == "postgresql"
    schema = "forget_lah_test_" + uid().replace("-", "")
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated)
        factory = session_factory(isolated)
        seed(factory, "test@forget-lah.example", "postgres-test-only-password")
        detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates())[:1])
        barrier = Barrier(2)

        def claim():
            barrier.wait(timeout=10)
            return claim_job(factory)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(claim) for _ in range(2)]
            results = [f.result(timeout=20) for f in futures]
        assert sum(result is not None for result in results) == 1
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.fixture
def postgres_schema(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to verify real PostgreSQL behaviour")
    engine = make_engine(url)
    assert engine.dialect.name == "postgresql"
    schema = "forget_lah_test_" + uid().replace("-", "")
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    # A unique search path makes Alembic, ORM and cleanup use only this test schema.
    schema_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("DATABASE_URL", schema_url.render_as_string(hide_password=False))
    isolated = None
    try:
        isolated = make_engine(schema_url.render_as_string(hide_password=False))
        yield isolated, session_factory(isolated)
    finally:
        if isolated is not None:
            isolated.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


@pytest.mark.postgres
def test_postgres_migration_preserves_existing_cases_and_creates_budget(postgres_schema):
    engine, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "0001")
    seed(factory, "test@forget-lah.example", "postgres-test-only-password")
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory() as db:
        before = set(db.scalars(select(FollowupCase.id)))
    command.upgrade(Config("alembic.ini"), "head")
    with factory() as db:
        assert set(db.scalars(select(FollowupCase.id))) == before
        assert len(before) == 3
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0009"
        assert db.get(ModelBudget, "organiser").calls == 0
    # No differences between the explicit migration and mapped runtime schema.
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def seed_runs(factory, count, mode="mock"):
    seed(factory, "test@forget-lah.example", "postgres-test-only-password")
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates())[:count])
    with factory.begin() as db:
        user = db.scalar(select(Principal))
        for case in db.scalars(select(FollowupCase)):
            run_id = uid()
            db.add(
                AgentRun(
                    id=run_id,
                    clinic_id=case.clinic_id,
                    case_id=case.id,
                    start_key=uid(),
                    start_case_version=case.case_version,
                    started_by=user.id,
                    authorised_by=user.id,
                    mode=mode,
                    goal="Concurrent synthetic review",
                    checkpoint={
                        "latest_event": {"id": run_id, "kind": "started", "content": ""},
                        "returned_specialists": [],
                    },
                )
            )


@pytest.mark.postgres
def test_direct_claude_migration_preserves_existing_run_and_budget(postgres_schema):
    _, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "0002")
    seed_runs(factory, 1, "organiser")
    with factory.begin() as db:
        run_id = db.scalar(select(AgentRun.id))
        db.get(ModelBudget, "organiser").calls = 17
    command.upgrade(Config("alembic.ini"), "head")
    with factory.begin() as db:
        assert db.get(AgentRun, run_id).mode == "organiser"
        assert db.get(ModelBudget, "organiser").calls == 17
        db.get(AgentRun, run_id).mode = "anthropic"
    with factory() as db:
        assert db.get(AgentRun, run_id).mode == "anthropic"


@pytest.mark.postgres
def test_postgres_only_one_worker_claims_an_agent(postgres_schema):
    _, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "head")
    seed_runs(factory, 1)
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=10)
        return claim_run(factory)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert sum(result is not None for result in results) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("constraint", ["daily_limit", "pacing"])
@pytest.mark.parametrize("mode", ["organiser", "anthropic"])
def test_postgres_shared_model_budget_is_atomic(postgres_schema, constraint, mode):
    import httpx

    from forget_lah.runtime.clinic_tools import ClinicTools
    from forget_lah.runtime.engine import process_run
    from services.mock_clinic.fixtures import followup_context

    _, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "head")
    seed_runs(factory, 2, mode)
    claims = [claim_run(factory), claim_run(factory)]
    assert claims[0][0] != claims[1][0]
    settings = Settings(
        agent_model_mode=mode,
        agent_daily_call_limit=1 if constraint == "daily_limit" else 40,
        agent_min_interval_seconds=30 if constraint == "pacing" else 0,
    )
    # Finish the deterministic first read before racing to reserve model calls.
    source = ClinicTools(
        "http://clinic",
        httpx.MockTransport(
            lambda r: httpx.Response(200, json=followup_context(r.url.path.rsplit("/", 1)[-1]))
        ),
    )

    class NeverModel:
        def decide(self, *_args, **_kwargs):
            pytest.fail("Initial source read must not reserve or invoke a model")

    for claim in claims:
        process_run(
            factory,
            settings.model_copy(update={"agent_min_interval_seconds": 0}),
            *claim,
            model=NeverModel(),
            tools=source,
        )
    claims = [claim_run(factory), claim_run(factory)]
    barrier = Barrier(2)

    def reserve(claim):
        barrier.wait(timeout=10)
        return prepare_step(factory, settings, *claim)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve, claim) for claim in claims]
        results = [future.result(timeout=20) for future in futures]
    assert sum(result is not None for result in results) == 1
    with factory() as db:
        assert db.get(ModelBudget, "organiser").calls == 1
        assert db.get(ModelBudget, "organiser").day == utcnow().date().isoformat()


@pytest.mark.postgres
def test_postgres_patient_memory_revisions_and_audit(postgres_schema):
    from forget_lah.db import AuditEvent
    from forget_lah.runtime.contracts import NeedsDecision
    from forget_lah.runtime.memory import effective_memory, persist_needs
    from forget_lah.runtime.models import PatientMemory

    _, factory = postgres_schema
    command.upgrade(Config("alembic.ini"), "head")
    seed(factory, "test@forget-lah.example", "postgres-test-only-password")
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase).limit(1))
        for value in ("5", "5,6"):
            step = uid()
            decision = NeedsDecision(
                request_id=step,
                expected_case_version=case.case_version,
                step_type="REVIEW_NEEDS",
                reason_code="PATIENT_NEEDS_REVIEWED",
                reply_event_id=uid(),
                updates=[
                    dict(key="excluded_weekdays", value=value, scope="future", quote="fixture")
                ],
            )
            persist_needs(db, case, decision, step)
        assert effective_memory(db, case)["excluded_weekdays"] == [5, 6]
        row = db.scalar(select(PatientMemory).where(PatientMemory.status == "active"))
        row.status = "retracted"
        db.add(
            AuditEvent(
                clinic_id=case.clinic_id,
                case_id=case.id,
                event_type="PATIENT_MEMORY_RETRACTED:" + row.id.replace("-", ""),
                details={"memory_id": row.id},
            )
        )
        db.flush()
        assert not effective_memory(db, case)
