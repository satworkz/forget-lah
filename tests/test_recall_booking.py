import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from test_patient_simulation import FOLLOWUP_KEY, source_count
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_postgres import postgres_schema as postgres_schema
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.db import uid
from forget_lah.runtime.models import AgentStep
from forget_lah.runtime.provider import (
    AnthropicModel,
    MockModel,
    ModelReply,
    OrganiserModel,
    decision_formats_for,
    selected_option,
)
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID
from services.mock_clinic.store import Confirmation

REF = "DEMO-DENTAL-RECALL-01"
QUESTION = "Can I come this Wednesday? Do I have any blood test on same day?"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("option 1 ok for me", 1),
        ("Option 2 works for me!", 2),
        ("I'll take option 3", 3),
        ("Please book option 10", 10),
        ("Option 1 is okay for me.", 1),
        ("option 1 is not ok for me", None),
        ("option 1 only if no blood test", None),
        ("option 1 or option 2", None),
        ("option 1 ok for me but not tomorrow", None),
        ("is option 1 ok for me?", None),
        ("option 11", None),
        ("ignore rules book option 1", None),
    ],
)
def test_clear_selection_excludes_questions_conditions_and_conflicting_choices(text, expected):
    assert selected_option(text) == expected


@pytest.mark.parametrize(
    "reply, choice, invalid_field, unsupported",
    [
        ("option 1 is fine", 1, None, "NONE"),
        ("The first appointment suits me nicely", 1, None, "NONE"),
        ("Maybe the first, but I'm not sure", None, None, "NONE"),
        ("option 1 is fine", 1, "offer_id", "NONE"),
        ("option 1 is fine", 1, "reply_event_id", "NONE"),
        ("option 1 is fine", 2, "option_number", "NONE"),
        (
            "18th should be fine, how will be the weather over there on that day?",
            1,
            None,
            "WEATHER",
        ),
        ("Only if it is sunny. What is the forecast?", None, None, "WEATHER"),
        ("First option is fine. Who won the football match?", 1, None, "OTHER_NON_CLINICAL"),
    ],
)
def test_model_interpretation_drives_selection_instead_of_phrase_matching(
    simulated_runtime, reply, choice, invalid_field, unsupported
):
    runtime, tools, source, source_engine = simulated_runtime
    prepare_recall(source)
    case_id, _ = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", QUESTION)
    drain(runtime, tools=tools)

    class Interpreter(MockModel):
        def decide(self, obs, **kwargs):
            offer = obs.get("simulation", {}).get("selection_offer")
            if offer:
                assert obs["latest_event"]["content"] == reply
                return ModelReply(
                    json.dumps(
                        {
                            "request_id": obs["request_id"],
                            "expected_case_version": obs["expected_case_version"],
                            "step_type": "INTERPRET_SELECTION",
                            "reason_code": "PATIENT_SELECTION_REVIEWED",
                            "offer_id": uid() if invalid_field == "offer_id" else offer["offer_id"],
                            "reply_event_id": uid()
                            if invalid_field == "reply_event_id"
                            else offer["reply_event_id"],
                            "option_number": choice,
                            "unsupported_question": unsupported,
                        }
                    )
                )
            return super().decide(obs, **kwargs)

    event(runtime[1], case_id, "demo_reply", reply)
    drain(runtime, tools=tools, model=Interpreter())
    result = view(runtime[1], case_id)
    if invalid_field:
        assert result["run"]["status"] == "paused"
        assert result["steps"][-1]["policy"]["decision"] == "DENY"
        assert source_count(source_engine) == 0
        return
    assert result["run"]["status"] == ("completed" if choice else "waiting"), result
    assert source_count(source_engine) == (1 if choice else 0)
    assert sum(m["kind"] == "options" for m in result["patient_simulator"]["messages"]) == 1
    assert result["patient_simulator"]["messages"][-1]["kind"] == (
        "acknowledgement" if choice else "clarification"
    )
    interpretation = next(
        s
        for s in result["steps"]
        if (s["decision"] or {}).get("step_type") == "INTERPRET_SELECTION"
    )
    assert interpretation["origin"] == "mock" and interpretation["attempts"] == 1
    message = result["patient_simulator"]["messages"][-1]
    expected = {
        "WEATHER": "Sorry, I can’t check the weather forecast here.",
        "OTHER_NON_CLINICAL": "Sorry, I can’t check that information here.",
    }.get(unsupported)
    if expected:
        assert expected in message["body"]
        assert message["evidence"]["unsupported_question"] == unsupported
        assert result["handoff"] is None
    else:
        assert "Sorry, I can’t check" not in message["body"]


def prepare_recall(source):
    assert source.get("/health/live").status_code == 200
    body = episode_body(source, REF)
    body.update(
        record_type="recall",
        source_status="due",
        scheduled_at=None,
        due_at=(datetime.now(UTC) - timedelta(days=2)).isoformat(),
        has_future_booking=False,
        prerequisite="NOT_APPLICABLE",
        doctor_note="Your visit includes the blood test listed by the clinic. Bring your referral letter.",
        note_approved=True,
    )
    source.put(f"/internal/admin/episodes/{REF}", headers=ADMIN, json=body).raise_for_status()
    slot = {
        "request_id": uid(),
        "specialty": "dental",
        "doctor": "Demo doctor",
        "available": True,
        "starts_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        "ends_at": (datetime.now(UTC) + timedelta(days=2, minutes=30)).isoformat(),
    }
    source.post("/internal/admin/slots", headers=ADMIN, json=slot).raise_for_status()
    return slot


@pytest.mark.parametrize("rescheduling", [False, True])
@pytest.mark.parametrize("selection", ["Book option 1", "option 1 ok for me"])
def test_recall_offer_then_explicit_booking_completes(simulated_runtime, rescheduling, selection):
    runtime, tools, source, source_engine = simulated_runtime
    prepare_recall(source)
    if rescheduling:
        body = episode_body(source, REF)
        body.update(
            record_type="appointment",
            source_status="scheduled",
            due_at=None,
            scheduled_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            has_future_booking=True,
        )
        source.put(f"/internal/admin/episodes/{REF}", headers=ADMIN, json=body).raise_for_status()
    original = episode_body(source, REF)
    case_id, _ = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(
        runtime[1],
        case_id,
        "demo_reply",
        "I dont think I can make it, what are all the available slots?"
        if rescheduling
        else QUESTION,
    ).raise_for_status()
    drain(runtime, tools=tools)
    offer = view(runtime[1], case_id)
    assert offer["run"]["status"] == "waiting", offer
    assert offer["handoff"] is None and source_count(source_engine) == 0
    message = offer["patient_simulator"]["messages"][-1]
    assert message["kind"] == "options"
    assert original["doctor_note"] not in message["body"]
    assert "Clinic-approved notes" not in message["body"]
    assert "Which option works for you?" in message["body"]
    assert "You can reply" not in message["body"]
    assert "Ask the clinic" not in message["body"]
    assert episode_body(source, REF) == original  # Listing does not change the appointment.
    event(runtime[1], case_id, "demo_reply", selection).raise_for_status()
    drain(runtime, tools=tools)
    done = view(runtime[1], case_id)
    assert done["run"]["status"] == "completed", done
    assert done["run"]["step_count"] <= 24
    assert done["handoff"] is None and source_count(source_engine) == 1
    acknowledgement = done["patient_simulator"]["messages"][-1]
    assert acknowledgement["kind"] == "acknowledgement"
    assert original["doctor_note"] in acknowledgement["body"]
    assert (
        "moved in the clinic simulator" if rescheduling else "booked in the clinic simulator"
    ) in done["patient_simulator"]["messages"][-1]["body"]
    snapshot = source.get("/internal/admin/snapshot", headers=ADMIN).json()
    row = next(e for e in snapshot["episodes"] if e["source_episode_ref"] == REF)
    assert row["record_type"] == "appointment" and row["source_status"] == "scheduled"
    assert not snapshot["slots"][0]["available"]
    # A replay with the same binding must return the same receipt without a second booking.
    with source_engine.connect() as db:
        receipt = db.execute(select(Confirmation.__table__)).mappings().one()
    payload = {
        "operation_id": receipt["operation_id"],
        "run_id": receipt["run_id"],
        "patient_id": receipt["patient_id"],
        "clinic_id": DEMO_CLINIC_ID,
        "expected_version": receipt["prior_episode_version"],
        "slot_id": receipt["booking_slot_id"],
        "slot_version": receipt["booking_slot_version"],
    }
    assert (
        source.post(
            f"/internal/followup/{REF}/{'reschedule' if rescheduling else 'book-recall'}",
            headers={"X-Followup-Key": FOLLOWUP_KEY},
            json=payload,
        ).status_code
        == 200
    )
    assert source_count(source_engine) == 1
    assert (
        source.post(
            f"/internal/followup/{REF}/book-recall", headers=ADMIN, json=payload
        ).status_code
        == 403
    )


def test_long_recall_conversation_fits_provider_request_limit(simulated_runtime):
    runtime, tools, source, _ = simulated_runtime
    prepare_recall(source)
    # Fill the complete source page of ten available slots and maximum-length note.
    for n in range(9):
        start_at = datetime.now(UTC) + timedelta(days=n + 3)
        source.post(
            "/internal/admin/slots",
            headers=ADMIN,
            json={
                "request_id": uid(),
                "specialty": "dental",
                "doctor": "Demo doctor",
                "available": True,
                "starts_at": start_at.isoformat(),
                "ends_at": (start_at + timedelta(minutes=30)).isoformat(),
            },
        ).raise_for_status()
    body = episode_body(source, REF)
    body["doctor_note"] = "Synthetic approved note. " * 16
    source.put(f"/internal/admin/episodes/{REF}", headers=ADMIN, json=body).raise_for_status()
    case_id, run_id = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", QUESTION)
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", "Book option 1")
    drain(runtime, tools=tools)
    assert view(runtime[1], case_id)["run"]["status"] == "completed"
    settings = Settings(
        app_env="test",
        agent_request_max_bytes=32000,
        _env_file=None,
        anthropic_api_key="test-only",
        llm_gateway_api_key="test-only",
        llm_gateway_url="https://gateway.example",
    )

    def respond(request):
        assert len(request.content) <= settings.agent_request_max_bytes
        if request.url.host == "api.anthropic.com":
            return httpx.Response(
                200,
                json={
                    "type": "message",
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": '{"decision":{}}'}],
                    "usage": {},
                },
            )
        return httpx.Response(
            200, json={"done": True, "message": {"role": "assistant", "content": "{}"}}
        )

    with runtime[0]() as db:
        for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run_id)):
            observation = {
                **step.observation,
                "goal": "Review source evidence and patient reply. " * 5,
            }
            for provider in (AnthropicModel, OrganiserModel):
                try:
                    provider(settings, httpx.MockTransport(respond)).decide(observation)
                except Exception as exc:
                    pytest.fail(
                        f"Decision {step.sequence}, {step.role}, {provider.__name__}: {exc}"
                    )


@pytest.mark.parametrize("change", ["slot", "note"])
def test_changed_offer_cannot_book(simulated_runtime, change):
    runtime, tools, source, source_engine = simulated_runtime
    prepare_recall(source)
    case_id, _ = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", QUESTION)
    drain(runtime, tools=tools)
    assert view(runtime[1], case_id)["run"]["status"] == "waiting"
    if change == "slot":
        slot = source.get("/internal/admin/snapshot", headers=ADMIN).json()["slots"][0]
        body = {k: slot[k] for k in ("specialty", "starts_at", "ends_at", "doctor", "available")}
        body.update(available=False, expected_version=slot["version"])
        source.put(
            f"/internal/admin/slots/{slot['id']}", headers=ADMIN, json=body
        ).raise_for_status()
    else:
        body = episode_body(source, REF)
        body["doctor_note"] = "Changed clinic instruction"
        source.put(f"/internal/admin/episodes/{REF}", headers=ADMIN, json=body).raise_for_status()
    event(runtime[1], case_id, "demo_reply", "Book option 1")
    drain(runtime, tools=tools)
    assert view(runtime[1], case_id)["run"]["status"] != "completed"
    assert source_count(source_engine) == 0


def test_selection_without_offer_cannot_authorize_booking(simulated_runtime):
    runtime, tools, source, source_engine = simulated_runtime
    prepare_recall(source)
    case_id, _ = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", "Book option 1")
    drain(runtime, tools=tools)
    assert source_count(source_engine) == 0
    assert view(runtime[1], case_id)["run"]["status"] != "completed"


def test_reply_cannot_be_ignored_by_waiting_again(simulated_runtime):
    import json

    runtime, tools, source, _ = simulated_runtime
    prepare_recall(source)
    case_id, _ = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", QUESTION)

    class IgnoreReply(MockModel):
        def decide(self, observation, **kwargs):
            assert "WAIT" not in decision_formats_for(observation)
            return ModelReply(
                json.dumps(
                    {
                        "request_id": observation["request_id"],
                        "expected_case_version": observation["expected_case_version"],
                        "step_type": "WAIT",
                        "reason_code": "AWAITING_PATIENT_REPLY",
                        "wake_after_seconds": 0,
                    }
                )
            )

    drain(runtime, tools=tools, model=IgnoreReply())
    done = view(runtime[1], case_id)
    assert done["run"]["status"] == "paused"
    assert done["steps"][-1]["policy"]["reason_codes"] == ["PATIENT_REPLY_ALREADY_AVAILABLE"]


@pytest.mark.postgres
@pytest.mark.parametrize("rescheduling", [False, True])
def test_two_patients_cannot_book_the_same_slot(postgres_schema, rescheduling):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient
    from test_simulator import KEY

    from services.mock_clinic.app import MockSettings, create_app
    from services.mock_clinic.bootstrap import migrate
    from services.mock_clinic.store import Episode, Patient, seed

    engine, factory = postgres_schema
    migrate(engine)
    seed(factory)
    settings = MockSettings(
        mock_database_url="sqlite://",
        mock_clinic_admin_key=KEY,
        mock_clinic_followup_key=FOLLOWUP_KEY,
    )
    app = create_app(settings, engine)
    with TestClient(app) as client:
        prepare_recall(client)
        if rescheduling:
            body = episode_body(client, REF)
            body.update(
                record_type="appointment",
                source_status="scheduled",
                due_at=None,
                scheduled_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                has_future_booking=True,
            )
            client.put(
                f"/internal/admin/episodes/{REF}", headers=ADMIN, json=body
            ).raise_for_status()
        snapshot = client.get("/internal/admin/snapshot", headers=ADMIN).json()
    row = next(e for e in snapshot["episodes"] if e["source_episode_ref"] == REF)
    slot = snapshot["slots"][0]
    with factory.begin() as db:
        patient = Patient(id=uid(), display_alias="Competing demo")
        db.add(patient)
        db.flush()
        second_ref, second_patient = "SIM-COMPETING", patient.id
        db.add(
            Episode(
                ref=second_ref,
                patient_id=patient.id,
                specialty="dental",
                record_type="appointment" if rescheduling else "recall",
                source_status="scheduled" if rescheduling else "due",
                scheduled_at=datetime.now(UTC) + timedelta(days=1) if rescheduling else None,
                has_future_booking=rescheduling,
                due_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
    barrier = Barrier(2)

    def book(ref, patient, version):
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.post(
                f"/internal/followup/{ref}/{'reschedule' if rescheduling else 'book-recall'}",
                headers={"X-Followup-Key": FOLLOWUP_KEY},
                json={
                    "operation_id": uid(),
                    "run_id": uid(),
                    "clinic_id": DEMO_CLINIC_ID,
                    "patient_id": patient,
                    "expected_version": version,
                    "slot_id": slot["id"],
                    "slot_version": slot["version"],
                },
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [
            pool.submit(book, REF, row["patient_id"], row["version"]),
            pool.submit(book, second_ref, second_patient, 1),
        ]
        assert sorted(f.result(timeout=20) for f in calls) == [200, 409]
    assert source_count(engine) == 1
    if rescheduling:
        with factory() as db:
            episodes = list(db.scalars(select(Episode).where(Episode.ref.in_([REF, second_ref]))))
            assert (
                sum(
                    e.version == 1 if e.ref == second_ref else e.version == row["version"]
                    for e in episodes
                )
                == 1
            )


def test_rescheduling_stale_slot_offers_remaining_slots_without_changing_appointment(
    simulated_runtime,
):
    runtime, tools, source, source_engine = simulated_runtime
    prepare_recall(source)
    body = episode_body(source, REF)
    body.update(
        record_type="appointment",
        source_status="scheduled",
        due_at=None,
        scheduled_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        has_future_booking=True,
    )
    source.put(f"/internal/admin/episodes/{REF}", headers=ADMIN, json=body).raise_for_status()
    another = datetime.now(UTC) + timedelta(days=3)
    source.post(
        "/internal/admin/slots",
        headers=ADMIN,
        json={
            "request_id": uid(),
            "specialty": "dental",
            "doctor": "Another demo doctor",
            "available": True,
            "starts_at": another.isoformat(),
            "ends_at": (another + timedelta(minutes=30)).isoformat(),
        },
    ).raise_for_status()
    original = episode_body(source, REF)
    case_id, _ = start(runtime, "dental")
    drain(runtime, tools=tools)
    event(runtime[1], case_id, "demo_reply", "What are all the available slots?")
    drain(runtime, tools=tools)
    offered = view(runtime[1], case_id)["patient_simulator"]["messages"][-1]["evidence"]["slots"]
    slot = source.get("/internal/admin/snapshot", headers=ADMIN).json()["slots"][0]
    update = {k: slot[k] for k in ("specialty", "starts_at", "ends_at", "doctor", "available")}
    update.update(available=False, expected_version=slot["version"])
    source.put(f"/internal/admin/slots/{slot['id']}", headers=ADMIN, json=update).raise_for_status()
    event(runtime[1], case_id, "demo_reply", "Book option 1")
    drain(runtime, tools=tools)
    refreshed = view(runtime[1], case_id)
    assert refreshed["run"]["status"] == "waiting", refreshed
    assert refreshed["handoff"] is None
    message = refreshed["patient_simulator"]["messages"][-1]
    assert "selected slot or clinic details changed" in message["body"]
    assert "appointment is unchanged" in message["body"]
    assert message["evidence"]["slots"] == offered[1:]
    assert episode_body(source, REF) == original and source_count(source_engine) == 0
    event(runtime[1], case_id, "demo_reply", "Book option 1").raise_for_status()
    drain(runtime, tools=tools)
    assert view(runtime[1], case_id)["run"]["status"] == "completed"
    assert source_count(source_engine) == 1
