import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from forget_lah.api import create_app
from forget_lah.db import make_engine, session_factory
from forget_lah.seed import seed
from forget_lah.settings import Settings

TEST_PASSWORD = "unit-test-only-not-a-live-credential"


@pytest.fixture
def store(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'unit.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    engine = make_engine(url)
    factory = session_factory(engine)
    seed(factory, "staff@forget-lah.example", TEST_PASSWORD)
    yield engine, factory
    engine.dispose()


@pytest.fixture
def client(store):
    engine, _ = store
    settings = Settings(
        app_env="test", database_url="sqlite://", public_origin="http://localhost:8080"
    )
    with TestClient(create_app(settings, engine), base_url="http://localhost:8080") as client:
        yield client


@pytest.fixture
def signed_client(client):
    response = client.post(
        "/api/auth/login",
        headers={"Origin": "http://localhost:8080"},
        json={"email": "staff@forget-lah.example", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return client


@pytest.fixture(autouse=True)
def clear_decider_env(monkeypatch):
    """A developer's enabled shell must never turn ordinary tests into network calls."""
    for name in (
        "AGENT_DECIDER_ENABLED",
        "AGENT_DECIDER_URL",
        "AGENT_DECIDER_FALLBACK_URL",
        "AGENT_DECIDER_MODEL",
        "AGENT_DECIDER_TIMEOUT",
        "AGENT_DECIDER_GATE_MODE",
        "AGENT_DECIDER_MIN_CONFIDENCE",
        "AGENT_DECIDER_MIN_PROBABILITY",
        "AGENT_DECIDER_MIN_MARGIN",
        "AGENT_DECIDER_SHADOW",
        "AGENT_DECIDER_RECORD",
        "AGENT_DECIDER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
