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
from services.mock_clinic.app import candidates


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
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
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
