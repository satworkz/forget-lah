import json

import httpx
import pytest
from sqlalchemy import select

from forget_lah.db import FollowupCase, uid
from forget_lah.detector import detect
from forget_lah.runtime.memory import delivery_block
from forget_lah.runtime.models import AgentRun, ModelBudget, PatientMemory, SimulatedMessage
from forget_lah.runtime.provider import ModelError
from forget_lah.runtime.responses import patient_message
from forget_lah.runtime.simulation import message_dict
from forget_lah.runtime.startup import queue_case_review
from forget_lah.seed import seed_automation
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.translations import normalized_dates, translate, translate_one
from services.mock_clinic.fixtures import candidates


def settings(**kwargs):
    return Settings(
        database_url="sqlite://",
        agent_model_mode="anthropic",
        anthropic_api_key="test-key-not-live",
        multilingual_enabled=True,
        agent_min_interval_seconds=0,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("language", "reply"),
    [
        ("zh", "您的预约为21日10:00。"),
        ("ms", "Janji temu anda pada 21, 10:00."),
        ("ta", "உங்கள் சந்திப்பு 21 அன்று 10:00."),
    ],
)
def test_translation_preserves_numbers_and_target_language(language, reply):
    def respond(request):
        payload = json.loads(request.content)
        assert "Translate" in payload["system"]
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps({"text": reply})}],
            },
        )

    assert (
        translate(
            settings(),
            "Your appointment is on 21 at 10:00.",
            language,
            transport=httpx.MockTransport(respond),
        )
        == reply
    )


def test_translation_rejects_changed_dates():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"text":"预约22日10:00"}'}],
            },
        )
    )
    with pytest.raises(ModelError, match="TRANSLATION_VALIDATION_FAILED"):
        translate(settings(), "Appointment 21 at 10:00", "zh", transport=transport)


def test_english_date_is_unambiguous_before_translation():
    assert normalized_dates("21 September 2026 at 10:00 AM SGT") == "2026-09-21 at 10:00 AM SGT"


def test_language_memory_generates_budgeted_translation_without_changing_source(store):
    _, factory = store
    seed_automation(factory)
    config = settings()
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase))
        run = queue_case_review(db, case, config)
        db.add(
            PatientMemory(
                clinic_id=case.clinic_id,
                patient_id=case.patient_id,
                case_id=case.id,
                key="preferred_language",
                value={"value": "zh"},
                scope="future",
                status="active",
                quote="Please use Chinese",
                message_id=uid(),
                step_id=uid(),
            )
        )
        db.flush()
        assert delivery_block(db, case, settings=config) is None
        assert delivery_block(db, case) == "LANGUAGE_SUPPORT_REQUIRED"
        message = patient_message(
            run,
            clinic_id=case.clinic_id,
            case_id=case.id,
            run_id=run.id,
            event_id=uid(),
            kind="acknowledgement",
            body="Confirmed for 21 at 10:00",
            reply_language="ms",  # Explicit saved Chinese preference takes precedence.
            source_version="1",
            evidence={},
        )
        db.add(message)
        db.flush()
        ident, run_id = message.id, run.id
        initial = db.get(ModelBudget, "organiser").calls
    translate_one(factory, config, translator=lambda *_: "已确认21日10:00。")
    translate_one(factory, config, translator=lambda *_: pytest.fail("Must not translate twice"))
    with factory() as db:
        message = db.get(SimulatedMessage, ident)
        assert message.body == "Confirmed for 21 at 10:00"
        assert message_dict(message)["body"] == "已确认21日10:00。"
        assert db.get(ModelBudget, "organiser").calls == initial + 1
        assert db.get(AgentRun, run_id).status == "queued"


def test_failed_translation_does_not_fall_back_to_english(store):
    _, factory = store
    seed_automation(factory)
    config = settings()
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase))
        run = queue_case_review(db, case, config)
        message = SimulatedMessage(
            clinic_id=case.clinic_id,
            case_id=case.id,
            run_id=run.id,
            event_id=uid(),
            kind="acknowledgement",
            body="Original",
            source_version="1",
            evidence={},
            translation={"language": "ta", "status": "pending"},
        )
        db.add(message)
        db.flush()
        ident = message.id

    def fail(*_):
        raise ModelError("MODEL_UNAVAILABLE")

    translate_one(factory, config, translator=fail)
    with factory() as db:
        message = db.get(SimulatedMessage, ident)
        assert message.translation["status"] == "failed"
        assert message_dict(message)["body"] != "Original"
