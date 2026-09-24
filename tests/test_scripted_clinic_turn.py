import pytest
from sqlalchemy import select
from test_runtime import event, start

from forget_lah.detector import detect
from forget_lah.runtime.models import AgentRun, SimulatedMessage
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from services.mock_clinic.fixtures import candidates


@pytest.fixture
def runtime(store, signed_client):
    factory = store[1]
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    return factory, signed_client, Settings(agent_min_interval_seconds=0, _env_file=None)


def test_scripted_clinic_turn_is_recorded_without_advancing_the_run(runtime) -> None:
    factory, client, _ = runtime
    case_id, run_id = start(runtime)
    with factory() as db:
        before = db.get(AgentRun, run_id).status

    body = "We can offer 2026-09-25 at 10:00. Shall I confirm this?"
    response = event(client, case_id, "scripted_clinic_turn", body)
    assert response.status_code in {200, 202}, response.text

    with factory() as db:
        newest = db.scalar(
            select(SimulatedMessage)
            .where(SimulatedMessage.run_id == run_id)
            .order_by(SimulatedMessage.created_at.desc(), SimulatedMessage.id.desc())
            .limit(1)
        )
        after = db.get(AgentRun, run_id).status

    assert newest is not None
    assert newest.body == body
    assert newest.evidence.get("scripted") is True
    assert after == before, "a controlled clinic input must not advance the run"


def test_scripted_clinic_turn_requires_content(runtime) -> None:
    _, client, _ = runtime
    case_id, run_id = start(runtime)
    response = event(client, case_id, "scripted_clinic_turn", "   ")
    assert response.status_code == 422
