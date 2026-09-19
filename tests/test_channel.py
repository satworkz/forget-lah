from datetime import timedelta

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from twilio.request_validator import RequestValidator

from forget_lah.api import create_app
from forget_lah.channel import WEBHOOK, collect_messages, dispatch_one, ingest_one
from forget_lah.channel_models import (
    ChannelBinding,
    ChannelInbox,
    ChannelOutbox,
    ChannelRoutingState,
)
from forget_lah.db import FollowupCase, uid, utcnow
from forget_lah.demo_reset import reset_demo
from forget_lah.detector import detect
from forget_lah.runtime.models import AgentEvent, AgentRun, SimulatedMessage
from forget_lah.runtime.startup import queue_case_review
from forget_lah.seed import seed_automation
from forget_lah.settings import Settings
from forget_lah.source import DEMO_CLINIC_ID, candidates_from_payload
from forget_lah.whatsapp import MessageReceipt, WhatsAppError
from services.mock_clinic.fixtures import candidates

ACCOUNT = "AC" + "1" * 32
TOKEN = "test-signing-token-not-a-live-secret"
SENDER = "whatsapp:+14155238886"
RECIPIENT = "whatsapp:+6590000001"


@pytest.fixture
def channel(store, monkeypatch):
    engine, factory = store
    for key, value in {
        "TWILIO_ACCOUNT_SID": ACCOUNT,
        "TWILIO_AUTH_TOKEN": TOKEN,
        "TWILIO_WHATSAPP_FROM": SENDER,
        "TWILIO_WHATSAPP_TEST_TO": RECIPIENT,
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings(
        database_url="sqlite://",
        whatsapp_enabled=True,
        patient_simulator_enabled=True,
        mock_clinic_followup_key="test-key",
    )
    seed_automation(factory)
    detect(factory, DEMO_CLINIC_ID, candidates_from_payload(candidates()))
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase).where(FollowupCase.specialty == "myopia"))
        run = queue_case_review(db, case, settings)
        run.status, run.available_at = "waiting", None
        case_id, run_id = case.id, run.id
    with TestClient(create_app(settings, engine), base_url=settings.public_origin) as client:
        client.post(
            "/api/auth/login",
            headers={"Origin": settings.public_origin},
            json={"email": "staff@forget-lah.example", "password": TEST_PASSWORD},
        ).raise_for_status()
        headers = {
            "Origin": settings.public_origin,
            "X-CSRF-Token": client.cookies["forget_lah_csrf"],
        }
        response = client.post(
            "/api/channels/whatsapp/binding",
            headers=headers,
            json={"case_id": case_id, "enabled": True},
        )
        assert response.status_code == 200
        yield client, factory, settings, case_id, run_id


def post(client, settings, *, sid=None, body="I confirm my attendance", **extra):
    values = {
        "MessageSid": sid or "SM" + "2" * 32,
        "AccountSid": ACCOUNT,
        "From": RECIPIENT,
        "To": SENDER,
        "Body": body,
        "NumMedia": "0",
        **extra,
    }
    signature = RequestValidator(TOKEN).compute_signature(settings.public_origin + WEBHOOK, values)
    return client.post(WEBHOOK, data=values, headers={"X-Twilio-Signature": signature})


def test_signed_reply_is_durable_deduplicated_and_wakes_bound_case(channel):
    client, factory, settings, case_id, run_id = channel
    assert post(client, settings).status_code == 200
    assert post(client, settings).status_code == 200
    ingest_one(factory)
    ingest_one(factory)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ChannelInbox)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(AgentEvent).where(AgentEvent.run_id == run_id)
            )
            == 1
        )
        run = db.get(AgentRun, run_id)
        assert run.status == "queued"
        assert run.checkpoint["latest_event"]["channel"] == "whatsapp_test"
        assert run.case_id == case_id
    view = client.get(f"/api/cases/{case_id}/agent").json()
    assert view["events"][0]["channel"] == "whatsapp_test"


def test_signature_sender_csrf_and_binding_protection(channel):
    client, factory, settings, case_id, _ = channel
    assert client.post(WEBHOOK, data={"Body": "forged"}).status_code == 403
    assert post(client, settings, From="whatsapp:+6590000002").status_code == 403
    assert (
        client.post(
            "/api/channels/whatsapp/binding",
            headers={"Origin": settings.public_origin},
            json={"case_id": case_id, "enabled": False},
        ).status_code
        == 403
    )
    assert post(client, settings, body="x" * 601).status_code == 200
    with factory() as db:
        assert db.scalar(select(ChannelInbox)).status == "needs_staff"


def test_completed_reply_opens_one_new_review_preserving_history(channel):
    client, factory, settings, _, run_id = channel
    with factory.begin() as db:
        db.get(AgentRun, run_id).status = "completed"
    post(client, settings)
    ingest_one(factory)
    with factory() as db:
        assert db.scalar(select(ChannelInbox)).status == "processed"
        assert db.get(AgentRun, run_id).status == "completed"
        new = db.scalar(select(AgentRun).where(AgentRun.id != run_id))
        assert new.status == "queued" and new.step_count == 0
        assert new.checkpoint["reopened_from_run_id"] == run_id
        assert new.checkpoint["latest_event"]["content"] == "I confirm my attendance"
    post(client, settings)
    ingest_one(factory)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 2


def message(factory, case_id, run_id, *, old=False):
    with factory.begin() as db:
        row = SimulatedMessage(
            clinic_id=DEMO_CLINIC_ID,
            case_id=case_id,
            run_id=run_id,
            event_id=uid(),
            kind="acknowledgement",
            body="Your synthetic appointment is confirmed.",
            source_version="1",
            evidence={},
            created_at=utcnow() - timedelta(days=1) if old else utcnow(),
        )
        db.add(row)
        db.flush()
        return row.id


def test_outbox_deduplicates_and_never_resends_ambiguous_timeout(channel):
    client, factory, settings, case_id, run_id = channel
    post(client, settings)
    message(factory, case_id, run_id, old=True)
    ident = message(factory, case_id, run_id)
    collect_messages(factory)
    collect_messages(factory)

    class Timeout:
        calls = 0

        def send_text(self, recipient, body):
            self.calls += 1
            raise WhatsAppError("TIMEOUT", delivery_uncertain=True)

    sender = Timeout()
    dispatch_one(factory, sender)
    dispatch_one(factory, sender)
    with factory() as db:
        out = list(db.scalars(select(ChannelOutbox)))
        assert len(out) == 1 and out[0].message_id == ident
        assert out[0].status == "uncertain"
    assert sender.calls == 1


def test_provider_queued_is_not_eligible_for_resend(channel):
    client, factory, settings, case_id, run_id = channel
    post(client, settings)
    message(factory, case_id, run_id)
    collect_messages(factory)

    class Sender:
        calls = 0

        def send_text(self, recipient, body):
            self.calls += 1
            return MessageReceipt("SM" + "3" * 32, "queued", None)

    sender = Sender()
    dispatch_one(factory, sender)
    dispatch_one(factory, sender)
    assert sender.calls == 1
    with factory() as db:
        assert db.scalar(select(ChannelOutbox)).status == "provider_queued"


def test_no_send_without_inbound_window_or_after_disconnect(channel):
    _, factory, _, case_id, run_id = channel
    message(factory, case_id, run_id)
    collect_messages(factory)
    dispatch_one(factory, None)  # Would fail if network dispatch were attempted.
    with factory.begin() as db:
        binding = db.scalar(select(ChannelBinding))
        binding.inbound_at, binding.enabled = utcnow(), False
    dispatch_one(factory, None)
    with factory() as db:
        assert db.scalar(select(ChannelOutbox)).status == "queued"


def test_reset_preserves_patient_and_retains_replay_tombstone(channel):
    client, factory, settings, case_id, run_id = channel
    post(client, settings)
    message(factory, case_id, run_id)
    collect_messages(factory)
    with factory.begin() as db:
        ids = list(db.scalars(select(FollowupCase.id)))
        reset_demo(db, ids, candidates_from_payload(candidates()))
    with factory() as db:
        binding = db.scalar(select(ChannelBinding))
        assert binding.enabled
        assert binding.case_id != case_id
        new_case_id = binding.case_id
        assert db.get(FollowupCase, binding.case_id).specialty == "myopia"
        assert binding.inbound_at is not None
        assert db.scalar(select(ChannelInbox)).body == ""
        assert db.scalar(select(ChannelInbox)).status == "reset"
        assert db.scalar(select(ChannelOutbox)).body == ""
        assert db.scalar(select(ChannelOutbox)).status == "canceled"
    assert post(client, settings).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ChannelInbox)) == 1
    with factory.begin() as db:
        run = queue_case_review(db, db.get(FollowupCase, new_case_id), settings)
        new_run_id = run.id
    message(factory, new_case_id, new_run_id)
    collect_messages(factory)
    collect_messages(factory)
    sent = []

    class Sender:
        def send_text(self, recipient, body):
            sent.append(body)
            return MessageReceipt("SM" + "e" * 32, "delivered", None)

    dispatch_one(factory, Sender())
    dispatch_one(factory, Sender())
    assert len(sent) == 1


@pytest.mark.parametrize("enabled", [True, False])
def test_reset_preserves_expired_window_and_explicit_disconnect(channel, enabled):
    _, factory, _, _, _ = channel
    expired = utcnow() - timedelta(days=2)
    with factory.begin() as db:
        binding = db.scalar(select(ChannelBinding))
        binding.enabled, binding.inbound_at = enabled, expired
        reset_demo(
            db, list(db.scalars(select(FollowupCase.id))), candidates_from_payload(candidates())
        )
    with factory() as db:
        binding = db.scalar(select(ChannelBinding))
        assert binding.enabled == enabled
        assert binding.inbound_at.replace(tzinfo=expired.tzinfo) == expired
    dispatch_one(factory, None)


def another_case(factory, settings):
    from uuid import UUID

    with factory() as db:
        old = db.scalar(select(FollowupCase).where(FollowupCase.specialty == "myopia"))
        patient_id = old.patient_id
    row = next(c for c in candidates_from_payload(candidates()) if c.specialty == "myopia")
    row = row.model_copy(
        update={"source_episode_ref": "SIM-" + uid(), "patient_id": UUID(patient_id)}
    )
    assert detect(factory, DEMO_CLINIC_ID, [row]) == 1
    with factory.begin() as db:
        case = db.scalar(
            select(FollowupCase).where(FollowupCase.source_episode_ref == row.source_episode_ref)
        )
        run = queue_case_review(db, case, settings)
        run.status, run.available_at = "waiting", None
        return case.id, run.id


def test_new_appointment_is_dispatched_for_same_patient_only(channel):
    client, factory, settings, case_id, old_run = channel
    post(client, settings)
    new_case, new_run = another_case(factory, settings)
    ident = message(factory, new_case, new_run)
    with factory.begin() as db:
        other = db.scalar(select(FollowupCase).where(FollowupCase.specialty == "dental"))
        other_run = queue_case_review(db, other, settings)
        other_id, other_run_id = other.id, other_run.id
    message(factory, other_id, other_run_id)
    collect_messages(factory)
    collect_messages(factory)

    class Sender:
        calls = 0

        def send_text(self, recipient, body):
            self.calls += 1
            assert body == "Your synthetic appointment is confirmed."
            return MessageReceipt("SM" + "a" * 32, "delivered", None)

    sender = Sender()
    dispatch_one(factory, sender)
    dispatch_one(factory, sender)
    assert sender.calls == 1
    with factory() as db:
        rows = list(db.scalars(select(ChannelOutbox)))
        assert len(rows) == 1 and rows[0].message_id == ident
        assert rows[0].case_id == new_case
    view = client.get("/api/channels/whatsapp").json()
    assert set(view["case_ids"]) == {case_id, new_case}


def test_ambiguous_reply_asks_appointment_then_processes_original_request(channel):
    client, factory, settings, old_case, old_run = channel
    new_case, new_run = another_case(factory, settings)
    post(client, settings, body="I need to reschedule")
    ingest_one(factory)
    with factory() as db:
        assert db.scalar(select(ChannelInbox)).status == "awaiting_case"
        assert db.get(AgentRun, old_run).status == "waiting"
        assert db.get(AgentRun, new_run).status == "waiting"
        prompt = db.scalar(select(SimulatedMessage))
        assert prompt.kind == "channel_routing"
        assert old_case[:8] in prompt.body and new_case[:8] in prompt.body
        assert "SGT" in prompt.body
    post(client, settings, sid="SM" + "4" * 32, body="2")
    ingest_one(factory)
    with factory() as db:
        assert db.get(AgentRun, new_run).status == "queued"
        assert (
            db.get(AgentRun, new_run).checkpoint["latest_event"]["content"]
            == "I need to reschedule"
        )
        assert db.get(AgentRun, old_run).status == "waiting"
        assert db.get(ChannelInbox, "SM" + "4" * 32).status == "routing_selection"
        assert db.scalar(select(func.count()).select_from(AgentEvent)) == 1


def test_signed_quoted_message_routes_to_original_appointment(channel):
    client, factory, settings, old_case, old_run = channel
    another_case(factory, settings)
    ident = message(factory, old_case, old_run)
    collect_messages(factory)
    with factory.begin() as db:
        out = db.scalar(select(ChannelOutbox).where(ChannelOutbox.message_id == ident))
        out.status, out.provider_sid = "delivered", "SM" + "9" * 32
        db.get(AgentRun, old_run).status = "completed"
    post(client, settings, body="Can I change the day?", OriginalRepliedMessageSid="SM" + "9" * 32)
    ingest_one(factory)
    with factory() as db:
        incoming = db.scalar(select(ChannelInbox))
        event = db.get(AgentEvent, incoming.event_id)
        assert event.case_id == old_case and event.run_id != old_run
        assert db.get(AgentRun, old_run).status == "completed"


def test_unknown_quote_does_not_guess_among_appointments(channel):
    client, factory, settings, case_id, run_id = channel
    another_case(factory, settings)
    post(client, settings, OriginalRepliedMessageSid="SM" + "f" * 32)
    ingest_one(factory)
    with factory() as db:
        assert db.scalar(select(ChannelInbox)).status == "awaiting_case"
        assert db.scalar(select(func.count()).select_from(AgentEvent)) == 0


def test_paused_case_keeps_pause_and_acknowledges_reply(channel):
    client, factory, settings, case_id, run_id = channel
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        run.status, run.available_at = "paused", None
    post(client, settings)
    ingest_one(factory)
    with factory() as db:
        assert db.get(AgentRun, run_id).status == "paused"
        assert db.scalar(select(ChannelInbox)).status == "needs_staff"
        assert "automated review is temporarily paused" in db.scalar(select(SimulatedMessage)).body
        assert "clinic staff attention" not in db.scalar(select(SimulatedMessage)).body


def test_new_reminder_establishes_reply_context(channel):
    client, factory, settings, old_case, old_run = channel
    post(client, settings)
    ingest_one(factory)
    new_case, new_run = another_case(factory, settings)
    message(factory, new_case, new_run)
    collect_messages(factory)

    class Sender:
        def send_text(self, recipient, body):
            return MessageReceipt("SM" + "a" * 32, "delivered", None)

    dispatch_one(factory, Sender())
    with factory() as db:
        assert (
            db.get(ChannelRoutingState, "whatsapp-test-phone").data.get("active_case_id")
            == new_case
        )
    post(client, settings, sid="SM" + "c" * 32, body="Cancel it")
    ingest_one(factory)
    with factory() as db:
        assert db.get(ChannelInbox, "SM" + "c" * 32).case_id == new_case


def test_routing_keeps_a_changed_request_in_clarification(channel):
    client, factory, settings, old_case, old_run = channel
    new_case, new_run = another_case(factory, settings)
    post(client, settings, body="I need to reschedule")
    ingest_one(factory)
    post(
        client,
        settings,
        sid="SM" + "b" * 32,
        body=f"For {new_case[:8]}, actually please cancel instead",
    )
    ingest_one(factory)
    with factory() as db:
        event = db.scalar(select(AgentEvent).where(AgentEvent.run_id == new_run))
        assert "reschedule" in event.content and "cancel instead" in event.content
        assert db.get(ChannelInbox, "SM" + "2" * 32).body == "I need to reschedule"


def test_reopened_request_reads_fresh_source_and_acknowledges_handoff(channel):
    import json

    from forget_lah.runtime.engine import claim_run, process_run
    from forget_lah.runtime.models import AgentStep, StaffHandoff
    from forget_lah.runtime.provider import ModelReply
    from tests.test_runtime import source_tools

    client, factory, settings, case_id, old_run = channel
    settings.agent_min_interval_seconds = 0
    with factory.begin() as db:
        db.get(AgentRun, old_run).status = "completed"
    post(client, settings, body="Please cancel my appointment")
    ingest_one(factory, settings)

    class CancelDecision:
        def decide(self, observation, *, repair=False):
            # This is a protocol test double, not a claim of live Claude interpretation.
            assert observation["tools"][0]["result"]["tool_name"] == "read_followup_context"
            if not observation.get("needs_reviewed"):
                return ModelReply(
                    json.dumps(
                        {
                            "request_id": observation["request_id"],
                            "expected_case_version": observation["expected_case_version"],
                            "step_type": "REVIEW_NEEDS",
                            "reason_code": "PATIENT_NEEDS_REVIEWED",
                            "reply_event_id": observation["latest_event"]["reply_event_id"],
                            "updates": [],
                        }
                    )
                )
            return ModelReply(
                json.dumps(
                    {
                        "request_id": observation["request_id"],
                        "expected_case_version": observation["expected_case_version"],
                        "step_type": "ESCALATE",
                        "reason_code": "CAPABILITY_UNAVAILABLE",
                    }
                )
            )

    for _ in range(5):
        claim = claim_run(factory)
        if not claim:
            break
        process_run(factory, settings, *claim, model=CancelDecision(), tools=source_tools())
    with factory() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.id != old_run))
        assert run.status == "escalated"
        assert db.get(AgentRun, old_run).status == "completed"
        assert db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == run.id))
        first = db.scalar(
            select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.sequence)
        )
        assert first.origin == "rule" and first.attempts == 0
        assert "not changed or cancelled" in db.scalar(select(SimulatedMessage)).body


def test_inbound_focus_is_frozen_before_worker_runs(channel):
    client, factory, settings, old_case, old_run = channel
    with factory.begin() as db:
        db.add(
            ChannelRoutingState(
                id="whatsapp-test-phone",
                clinic_id=db.get(FollowupCase, old_case).clinic_id,
                data={"active_case_id": old_case},
            )
        )
    new_case, new_run = another_case(factory, settings)
    post(client, settings, body="Yes I will attend")
    with factory.begin() as db:
        db.get(ChannelRoutingState, "whatsapp-test-phone").data = {"active_case_id": new_case}
    ingest_one(factory)
    with factory() as db:
        reply = db.scalar(select(ChannelInbox))
        assert reply.case_id == old_case
        assert reply.status == "processed"


def test_reset_does_not_rebind_to_another_patient_when_no_eligible_case(channel):
    _, factory, _, _, _ = channel
    rows = [
        c.model_copy(update={"source_status": "completed"}) if c.specialty == "myopia" else c
        for c in candidates_from_payload(candidates())
    ]
    with factory.begin() as db:
        reset_demo(db, list(db.scalars(select(FollowupCase.id))), rows)
    with factory() as db:
        assert not db.scalar(select(ChannelBinding)).enabled
        assert db.scalar(select(func.count()).select_from(FollowupCase)) == 2


def test_reconnect_same_phone_preserves_verified_inbound_window(channel):
    client, factory, settings, case_id, _ = channel
    post(client, settings)
    with factory() as db:
        original = db.scalar(select(ChannelBinding)).inbound_at
    headers = {
        "Origin": settings.public_origin,
        "X-CSRF-Token": client.cookies.get("forget_lah_csrf"),
    }
    for enabled in [False, True]:
        response = client.post(
            "/api/channels/whatsapp/binding",
            headers=headers,
            json={"case_id": case_id, "enabled": enabled},
        )
        assert response.status_code == 200
    with factory() as db:
        assert db.scalar(select(ChannelBinding)).inbound_at == original


def test_patient_message_is_not_prefixed_with_internal_case_reference(channel):
    _, factory, _, case_id, run_id = channel
    message(factory, case_id, run_id)
    collect_messages(factory)
    with factory() as db:
        outgoing = db.scalar(select(ChannelOutbox))
        original = db.get(SimulatedMessage, outgoing.message_id)
        assert outgoing.body == original.body
        assert "Appointment reference:" not in outgoing.body


SECOND_PHONE = "whatsapp:+6590000002"


def register_second(channel):
    client, factory, settings, _, _ = channel
    with factory.begin() as db:
        case = db.scalar(select(FollowupCase).where(FollowupCase.specialty == "antenatal"))
        run = queue_case_review(db, case, settings)
        run.status, run.available_at = "waiting", None
        case_id, run_id = case.id, run.id
    headers = {"Origin": settings.public_origin, "X-CSRF-Token": client.cookies["forget_lah_csrf"]}
    r = client.post(
        "/api/channels/whatsapp/binding",
        headers=headers,
        json={
            "case_id": case_id,
            "enabled": True,
            "recipient": SECOND_PHONE.removeprefix("whatsapp:"),
        },
    )
    r.raise_for_status()
    return case_id, run_id, r.json()["id"], headers


def test_team_phones_route_collect_and_send_independently(channel):
    client, factory, settings, first_case, first_run = channel
    second_case, second_run, _, _ = register_second(channel)
    assert post(client, settings, body="First patient reply").status_code == 200
    assert (
        post(
            client, settings, sid="SM" + "4" * 32, From=SECOND_PHONE, body="Second patient reply"
        ).status_code
        == 200
    )
    ingest_one(factory)
    with factory() as db:
        assert (
            db.get(AgentRun, first_run).checkpoint["latest_event"]["content"]
            == "First patient reply"
        )
        assert (
            db.get(AgentRun, second_run).checkpoint["latest_event"]["content"]
            == "Second patient reply"
        )
    first_msg = message(factory, first_case, first_run)
    second_msg = message(factory, second_case, second_run)
    collect_messages(factory)
    collect_messages(factory)

    class Sender:
        calls = []

        def send_text(self, recipient, body):
            self.calls.append(recipient)
            return MessageReceipt("SM" + str(len(self.calls)) * 32, "delivered", None)

    sender = Sender()
    dispatch_one(factory, sender)
    dispatch_one(factory, sender)
    dispatch_one(factory, sender)
    assert set(sender.calls) == {RECIPIENT, SECOND_PHONE} and len(sender.calls) == 2
    with factory() as db:
        rows = {r.message_id: r for r in db.scalars(select(ChannelOutbox))}
        assert rows[first_msg].recipient == RECIPIENT
        assert rows[second_msg].recipient == SECOND_PHONE
        assert len(rows) == 2


def test_disconnect_and_expired_window_do_not_block_other_phone(channel):
    client, factory, settings, case, run = channel
    second_case, second_run, second_id, headers = register_second(channel)
    post(client, settings)
    post(client, settings, sid="SM" + "4" * 32, From=SECOND_PHONE)
    message(factory, case, run)
    message(factory, second_case, second_run)
    collect_messages(factory)
    with factory.begin() as db:
        db.get(ChannelBinding, "whatsapp-test-phone").inbound_at = utcnow() - timedelta(days=2)

    class Sender:
        calls = []

        def send_text(self, recipient, body):
            self.calls.append(recipient)
            return MessageReceipt("SM" + "5" * 32, "delivered", None)

    sender = Sender()
    dispatch_one(factory, sender)
    assert sender.calls == [SECOND_PHONE]
    client.post(
        "/api/channels/whatsapp/binding",
        headers=headers,
        json={"case_id": second_case, "enabled": False, "binding_id": second_id},
    ).raise_for_status()
    with factory() as db:
        assert db.get(ChannelBinding, "whatsapp-test-phone").enabled
        assert (
            db.scalar(select(ChannelOutbox).where(ChannelOutbox.case_id == case)).status == "queued"
        )
        assert db.get(ChannelInbox, "SM" + "4" * 32).status == "disconnected"
    assert post(client, settings, sid="SM" + "6" * 32, From=SECOND_PHONE).status_code == 409
    assert (
        post(client, settings, sid="SM" + "7" * 32, From="whatsapp:+6590000099").status_code == 403
    )


def test_team_registration_rejects_duplicate_patient_and_invalid_phone(channel):
    client, factory, settings, case, _ = channel
    second_case, _, ident, headers = register_second(channel)
    for number, target, status in [
        ("+6590000003", case, 409),
        (SECOND_PHONE, case, 409),
        ("90000003", second_case, 422),
    ]:
        assert (
            client.post(
                "/api/channels/whatsapp/binding",
                headers=headers,
                json={"case_id": target, "enabled": True, "recipient": number},
            ).status_code
            == status
        )
    assert (
        client.post(
            "/api/channels/whatsapp/binding",
            headers={"Origin": settings.public_origin},
            json={"case_id": second_case, "enabled": False, "binding_id": ident},
        ).status_code
        == 403
    )
    assert len(client.get("/api/channels/whatsapp").json()["bindings"]) == 2


def test_reset_preserves_all_registered_patients(channel):
    client, factory, settings, _, _ = channel
    register_second(channel)
    post(client, settings)
    post(client, settings, sid="SM" + "4" * 32, From=SECOND_PHONE)
    with factory.begin() as db:
        before = {
            b.recipient: (db.get(FollowupCase, b.case_id).patient_id, b.inbound_at)
            for b in db.scalars(select(ChannelBinding))
        }
        reset_demo(
            db, list(db.scalars(select(FollowupCase.id))), candidates_from_payload(candidates())
        )
    with factory() as db:
        after = {
            b.recipient: (db.get(FollowupCase, b.case_id).patient_id, b.inbound_at)
            for b in db.scalars(select(ChannelBinding))
            if b.enabled
        }
        assert before == after and len(after) == 2


def test_team_dispatch_is_paced_across_all_phones(channel, monkeypatch):
    from forget_lah.channel import channel_tick

    client, factory, settings, case, run = channel
    second_case, second_run, _, _ = register_second(channel)
    post(client, settings)
    post(client, settings, sid="SM" + "4" * 32, From=SECOND_PHONE)
    message(factory, case, run)
    message(factory, second_case, second_run)
    calls = []

    class Sender:
        def __init__(self, config, *, allowed_recipients):
            assert set(allowed_recipients) == {RECIPIENT, SECOND_PHONE}

        def send_text(self, recipient, body):
            calls.append(recipient)
            return MessageReceipt("SM" + str(len(calls)) * 32, "delivered", None)

    monkeypatch.setattr("forget_lah.channel.WhatsAppClient", Sender)
    channel_tick(factory, settings)
    channel_tick(factory, settings)
    assert len(calls) == 1
    with factory.begin() as db:
        db.get(ChannelRoutingState, "whatsapp-send-clock").data = {
            "reserved_at": utcnow().timestamp() - 4
        }
    channel_tick(factory, settings)
    assert len(calls) == 2 and set(calls) == {RECIPIENT, SECOND_PHONE}


def test_new_registration_waits_for_next_transport_allowlist(channel):
    client, factory, settings, case, run = channel
    post(client, settings)
    message(factory, case, run)
    collect_messages(factory)

    class NotYetAllowed:
        allowed_recipients = frozenset()

        def send_text(self, recipient, body):
            pytest.fail("Stale allowlist must not dispatch or fail the queued message")

    dispatch_one(factory, NotYetAllowed())
    with factory() as db:
        assert db.scalar(select(ChannelOutbox)).status == "queued"


@pytest.mark.parametrize("owned", [False, True])
def test_staff_wait_notice_reflects_ownership_and_cancellation(channel, owned):
    from forget_lah.db import Principal
    from forget_lah.runtime.models import StaffHandoff

    client, factory, settings, case_id, run_id = channel
    with factory.begin() as db:
        run = db.get(AgentRun, run_id)
        run.status, run.available_at = "escalated", None
        run.checkpoint = {**run.checkpoint, "cancellation_request": {"status": "requested"}}
        owner = db.scalar(select(Principal).where(Principal.email == "staff@forget-lah.example"))
        db.add(
            StaffHandoff(
                clinic_id=DEMO_CLINIC_ID,
                case_id=case_id,
                run_id=run_id,
                reason_code="CANCELLATION_REQUESTED",
                risk="AMBER",
                accepted_by=owner.id if owned else None,
                accepted_at=utcnow() if owned else None,
            )
        )
    post(client, settings, body="What is happening with my request?")
    ingest_one(factory)
    with factory() as db:
        message = db.scalar(select(SimulatedMessage)).body
        assert ("staff have accepted" if owned else "awaiting assignment") in message
        assert "not been cancelled yet" in message
        assert db.get(AgentRun, run_id).status == "escalated"
        assert db.scalar(select(ChannelInbox)).status == "needs_staff"
