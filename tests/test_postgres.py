import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.schema import CreateSchema, DropSchema

from forget_lah.db import Base, make_engine, session_factory, uid
from forget_lah.detector import detect
from forget_lah.seed import seed
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
