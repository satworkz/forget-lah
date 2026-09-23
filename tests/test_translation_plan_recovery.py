import json

import httpx
import pytest
from test_channel import ingest_test_reply
from test_conversation_continuity import ASSISTANCE, DRIVING, NOTE, plan_model
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator
from test_translations import settings

from forget_lah.runtime.provider import ModelError, ModelReply
from forget_lah.translations import translate


@pytest.mark.parametrize("translated", ["您提到：", "You mentioned:", ""])
def test_reject_incomplete_translation_of_full_warning(translated):
    text = f'You mentioned: "{DRIVING}". The clinic advised: "{NOTE}". '
    text += (
        "Please arrange accompaniment before confirmation. Your appointment has not been changed."
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps({"text": translated})}],
            },
        )
    )
    with pytest.raises(ModelError, match="TRANSLATION_VALIDATION_FAILED"):
        translate(settings(), text, "zh", transport=transport)


@pytest.mark.parametrize("source_changed", [False, True])
def test_compatible_plan_without_new_confirmation_resumes_saved_attendance(
    simulated_runtime, source_changed
):
    runtime, tools, source, engine = simulated_runtime
    body = episode_body(source)
    body["doctor_note"] = NOTE
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    ingest_test_reply(runtime, case, DRIVING)
    drain(runtime, tools=tools, model=plan_model(DRIVING, "CONFLICTS"))
    assert source_count(engine) == 0

    if source_changed:
        from datetime import datetime, timedelta

        body = episode_body(source)
        body["scheduled_at"] = (
            datetime.fromisoformat(body["scheduled_at"]) + timedelta(days=1)
        ).isoformat()
        source.put(
            "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
        ).raise_for_status()

    model = plan_model(ASSISTANCE, "SATISFIES")
    original_decide = model.decide

    def classify_new_plan(obs, **kwargs):
        value = json.loads(original_decide(obs, **kwargs).text)
        if value["step_type"] == "REVIEW_NEEDS":
            # Exact live classification; subsequent routing follows the current
            # checkpoint, including any validated resumed attendance intent.
            value.update(appointment_intent="UNSPECIFIED", appointment_request_quote=None)
        return ModelReply(json.dumps(value))

    model.decide = classify_new_plan
    ingest_test_reply(runtime, case, ASSISTANCE)
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)
    if source_changed:
        assert source_count(engine) == 0
        assert result["run"]["status"] != "completed"
        return
    assert result["run"]["status"] == "completed", json.dumps(
        {"run": result["run"], "steps": result["steps"][-5:]}, ensure_ascii=True
    )
    assert source_count(engine) == 1
    assert any(
        s["origin"] == "rule" and (s.get("decision") or {}).get("target") == "preparation"
        for s in result["steps"]
    )
    assert not any(
        (s.get("decision") or {}).get("step_type") == "ASSESS_BARRIERS" for s in result["steps"]
    )
    assert not any(m["kind"] == "clarification" for m in result["patient_simulator"]["messages"])


@pytest.mark.parametrize("recover", [False, True])
def test_invalid_translation_gets_one_budgeted_retry_then_stops(store, recover):
    from sqlalchemy import select

    from forget_lah.db import FollowupCase, uid
    from forget_lah.detector import detect
    from forget_lah.runtime.models import SimulatedMessage
    from forget_lah.runtime.startup import queue_case_review
    from forget_lah.seed import seed_automation
    from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
    from forget_lah.translations import translate_one
    from services.mock_clinic.fixtures import candidates

    _, factory = store
    config = settings()
    seed_automation(factory)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase))
        run = queue_case_review(db, case, config)
        message = SimulatedMessage(
            clinic_id=case.clinic_id,
            case_id=case.id,
            run_id=run.id,
            event_id=uid(),
            kind="plan_conflict",
            body=NOTE,
            source_version="1",
            evidence={},
            translation={"language": "zh", "status": "pending"},
        )
        db.add(message)
        db.flush()
        ident = message.id
    calls = []

    def translator(*_):
        calls.append(1)
        if len(calls) == 2 and recover:
            return "看诊后视力会模糊，请安排陪同者。"
        raise ModelError("TRANSLATION_VALIDATION_FAILED")

    translate_one(factory, config, translator=translator)
    with factory() as db:
        assert db.get(SimulatedMessage, ident).translation["status"] == "pending"
    translate_one(factory, config, translator=translator)
    translate_one(
        factory, config, translator=lambda *_: pytest.fail("A third attempt is not allowed")
    )
    with factory() as db:
        assert db.get(SimulatedMessage, ident).translation["status"] == (
            "ready" if recover else "failed"
        )
    assert len(calls) == 2
