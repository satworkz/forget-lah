import copy
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_channel import channel as channel
from test_channel import post
from test_postgres import postgres_schema as postgres_schema
from test_translations import settings

from forget_lah.api import create_app
from forget_lah.channel import ingest_one
from forget_lah.channel_models import ChannelOutbox
from forget_lah.db import FollowupCase, uid, utcnow
from forget_lah.detector import detect
from forget_lah.runtime.models import AgentEvent, AgentRun, ModelBudget, SimulatedMessage
from forget_lah.runtime.provider import ModelError
from forget_lah.runtime.startup import queue_case_review
from forget_lah.seed import seed, seed_automation
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.staff_translations import initial_translation, translate_staff_one
from services.mock_clinic.fixtures import candidates

ORIGINAL = "Ya, saya sahkan temu janji, tetapi saya mengalami bengkak dan sakit."
ENGLISH = "Yes, I confirm the appointment, but I have swelling and pain."


@pytest.fixture
def pending(store):
    return make_pending(store)


def make_pending(store):
    engine, factory = store
    config = settings()
    seed_automation(factory)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase))
        run = queue_case_review(db, case, config)
        run.status, run.available_at = "escalated", None
        run.checkpoint = {"clinical_review": {"symptom_quotes": ["bengkak dan sakit"]}}
        event = AgentEvent(
            clinic_id=case.clinic_id,
            case_id=case.id,
            run_id=run.id,
            client_key=uid(),
            actor_id=run.started_by,
            expected_case_version=case.case_version,
            kind="demo_reply",
            content=ORIGINAL,
            staff_translation=initial_translation(config, "demo_reply"),
        )
        db.add(event)
        db.flush()
        ids = case.id, run.id, event.id
    return engine, factory, config, ids


def test_translation_is_cached_display_only_and_preserves_original(pending):
    _, factory, config, (cid, rid, eid) = pending
    with factory() as db:
        checkpoint = copy.deepcopy(db.get(AgentRun, rid).checkpoint)
        version = db.get(FollowupCase, cid).case_version
        calls = db.get(ModelBudget, "organiser").calls

    def translator(_, original, language):
        assert original == ORIGINAL and language == "en"
        return ENGLISH

    translate_staff_one(factory, config, translator=translator)
    translate_staff_one(factory, config, translator=lambda *_: pytest.fail("Duplicate call"))
    with factory() as db:
        event = db.get(AgentEvent, eid)
        assert event.content == ORIGINAL
        assert event.staff_translation["body"] == ENGLISH
        assert db.get(AgentRun, rid).checkpoint == checkpoint
        assert db.get(AgentRun, rid).status == "escalated"
        assert db.get(FollowupCase, cid).case_version == version
        assert db.get(ModelBudget, "organiser").calls == calls + 1
        assert db.scalar(select(func.count()).select_from(ChannelOutbox)) == 0
        assert db.scalar(select(func.count()).select_from(SimulatedMessage)) == 0


def test_translation_failure_does_not_block_clinical_review(pending):
    _, factory, config, (_, rid, eid) = pending

    def fail(*_):
        raise ModelError("TRANSLATION_VALIDATION_FAILED")

    translate_staff_one(factory, config, translator=fail)
    with factory() as db:
        assert db.get(AgentEvent, eid).content == ORIGINAL
        assert db.get(AgentEvent, eid).staff_translation["status"] == "failed"
        assert db.get(AgentRun, rid).status == "escalated"


def test_active_clinical_processing_has_priority_over_staff_translation(pending):
    _, factory, config, (_, rid, eid) = pending
    with factory.begin() as db:
        db.get(AgentRun, rid).status = "running"
    translate_staff_one(factory, config, translator=lambda *_: pytest.fail("Must wait"))
    with factory() as db:
        assert db.get(AgentEvent, eid).staff_translation["status"] == "pending"


def test_saved_reply_in_a_paused_review_can_still_be_translated(pending):
    _, factory, config, (_, rid, eid) = pending
    with factory.begin() as db:
        db.get(AgentRun, rid).status = "paused"
    translate_staff_one(factory, config, translator=lambda *_: ENGLISH)
    with factory() as db:
        assert db.get(AgentEvent, eid).staff_translation["status"] == "ready"
        assert db.get(AgentRun, rid).status == "paused"


def test_interrupted_claim_is_not_silently_replayed(pending):
    _, factory, config, (_, _, eid) = pending
    with factory.begin() as db:
        db.get(AgentEvent, eid).staff_translation = {
            "language": "en",
            "status": "processing",
            "started_at": (utcnow() - timedelta(minutes=3)).isoformat(),
        }
    translate_staff_one(factory, config, translator=lambda *_: pytest.fail("Unexpected call"))
    with factory() as db:
        assert db.get(AgentEvent, eid).staff_translation["error"] == "TRANSLATION_INTERRUPTED"


def test_stale_translation_cannot_overwrite_new_claim(pending):
    _, factory, config, (_, _, eid) = pending

    def replaced(*_):
        with factory.begin() as db:
            db.get(AgentEvent, eid).staff_translation = {"language": "en", "status": "pending"}
        return ENGLISH

    translate_staff_one(factory, config, translator=replaced)
    with factory() as db:
        assert db.get(AgentEvent, eid).staff_translation["status"] == "pending"


def test_request_and_read_require_case_scope_and_csrf(pending):
    engine, factory, config, (cid, _, eid) = pending
    config.app_env = "test"
    with TestClient(create_app(config, engine), base_url=config.public_origin) as client:
        url = f"/api/cases/{cid}/events/{eid}/staff-translation"
        assert client.post(url).status_code in {401, 403}
        client.post(
            "/api/auth/login",
            headers={"Origin": config.public_origin},
            json={
                "email": "staff@forget-lah.example",
                "password": TEST_PASSWORD,
            },
        ).raise_for_status()
        assert client.post(url, headers={"Origin": config.public_origin}).status_code == 403
        headers = {
            "Origin": config.public_origin,
            "X-CSRF-Token": client.cookies["forget_lah_csrf"],
        }
        with factory.begin() as db:
            db.get(AgentEvent, eid).staff_translation = None
            other = db.scalar(select(FollowupCase.id).where(FollowupCase.id != cid))
        assert (
            client.post(
                f"/api/cases/{other}/events/{eid}/staff-translation", headers=headers
            ).status_code
            == 404
        )
        assert client.post(url, headers=headers).status_code == 202
        translate_staff_one(factory, config, translator=lambda *_: ENGLISH)
        assert client.post(url, headers=headers).json()["translation"]["status"] == "ready"
        event = client.get(f"/api/cases/{cid}/agent").json()["events"][0]
        assert event["content"] == ORIGINAL and event["staff_translation"]["body"] == ENGLISH


def test_whatsapp_reply_queues_translation_without_changing_workflow(channel):
    client, factory, config, _, rid = channel
    config.agent_model_mode = "anthropic"
    config.anthropic_api_key = settings().anthropic_api_key
    config.multilingual_enabled = True
    post(client, config, body=ORIGINAL).raise_for_status()
    ingest_one(factory, config)
    with factory() as db:
        event = db.scalar(select(AgentEvent).where(AgentEvent.run_id == rid))
        assert event.content == ORIGINAL
        assert event.staff_translation == {"language": "en", "status": "pending"}
        assert db.get(AgentRun, rid).checkpoint["latest_event"]["content"] == ORIGINAL


def test_staff_actions_and_unconfigured_translation_are_not_queued():
    assert initial_translation(settings(), "accept_handoff") is None
    assert initial_translation(None, "demo_reply") is None


@pytest.mark.postgres
def test_existing_reply_translation_action_on_postgres(postgres_schema):
    command.upgrade(Config("alembic.ini"), "head")
    seed(postgres_schema[1], "staff@forget-lah.example", TEST_PASSWORD)
    test_request_and_read_require_case_scope_and_csrf(make_pending(postgres_schema))
