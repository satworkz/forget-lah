"""Exercise staff changes through authenticated UI endpoints and the real adapters."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from test_bridge_runtime import OmarReplyModel, add_option
from test_bridge_runtime import bridge_runtime as bridge_runtime
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_postgres import postgres_schema as postgres_schema
from test_runtime import drain, event, headers, view
from test_simulator import simulator as simulator

from forget_lah.channel import collect_messages, dispatch_one
from forget_lah.channel_models import ChannelBinding, ChannelOutbox
from forget_lah.db import BridgeEpisode, FollowupCase, uid, utcnow
from forget_lah.runtime.models import SimulatedMessage, StaffAppointmentChange
from forget_lah.whatsapp import MessageReceipt, WhatsAppError


def setup_bridge(bridge_runtime):
    runtime, tools, case_id = bridge_runtime
    runtime[1].app.state.staff_change_tools = tools
    with runtime[0].begin() as db:
        row = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        row.normalized = {**row.normalized, "doctor_notes": ""}
    add_option(runtime, case_id)
    return runtime, tools, case_id


def test_doctor_notes_read_current_bridge_source_without_changing_case(bridge_runtime):
    runtime, tools, case_id = setup_bridge(bridge_runtime)
    client = runtime[1]
    before = view(client, case_id)
    endpoint = f"/api/cases/{case_id}/doctor-notes"
    assert client.get(endpoint).json()["instructions"] == []
    note = "Bring your spectacles.\nArrange someone to accompany you."
    with runtime[0].begin() as db:
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        episode.normalized = {**episode.normalized, "doctor_notes": note}
    result = client.get(endpoint)
    assert result.status_code == 200
    assert result.json()["source"] == "Imported clinic record"
    assert result.json()["instructions"][0]["approved_text"] == note
    assert view(client, case_id) == before
    assert client.get(f"/api/cases/{uid()}/doctor-notes").status_code == 404


def test_doctor_notes_read_approved_clinic_source_and_report_failure(simulated_runtime):
    from test_doctor_actions_dynamic import SCAN_NOTE, set_note
    from test_patient_simulation import source_count
    from test_runtime import start

    runtime, tools, source, source_engine = simulated_runtime
    runtime[1].app.state.staff_change_tools = tools
    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    case_id, _ = start(runtime, "antenatal")
    endpoint = f"/api/cases/{case_id}/doctor-notes"
    result = runtime[1].get(endpoint)
    assert result.status_code == 200
    assert result.json()["instructions"][0]["approved_text"] == SCAN_NOTE
    assert source_count(source_engine) == 0

    from forget_lah.runtime.contracts import ToolResult

    class Unavailable:
        def execute(self, name, binding):
            return ToolResult(
                tool_name=name,
                status="failed",
                error_code="SOURCE_UNAVAILABLE",
                source_version=None,
                data={},
                retryable=True,
            )

    runtime[1].app.state.staff_change_tools = Unavailable()
    assert runtime[1].get(endpoint).status_code == 503


def choose(client, case_id):
    endpoint = f"/api/cases/{case_id}/appointment-change"
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    state = response.json()
    assert not state["blocked"], state
    slot = state["slots"][0]
    return (
        endpoint,
        {
            "expected_case_version": state["case_version"],
            "expected_version": state["episode_version"],
            "expected_source_version": state["source_version"],
            "slot_id": slot["id"],
            "slot_version": slot["version"],
            "reason": "Private administrative reason",
        },
        state,
    )


def apply(client, case_id):
    endpoint, body, state = choose(client, case_id)
    h = headers(client)
    result = client.post(endpoint, headers=h, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "committed", result.text
    return result.json(), endpoint, body, h, state


def test_bridge_staff_change_audit_idempotency_and_yes(bridge_runtime):
    runtime, tools, case_id = setup_bridge(bridge_runtime)
    result, endpoint, body, h, state = apply(runtime[1], case_id)
    # Let a worker tick before the patient responds: there must be no model call,
    # timer wake, duplicate message, or false capability handoff.
    from forget_lah.runtime.engine import claim_run
    from forget_lah.runtime.models import AgentRun

    with runtime[0]() as db:
        run = db.get(AgentRun, db.get(StaffAppointmentChange, result["id"]).run_id)
        assert run.status == "waiting" and run.available_at is None
    assert claim_run(runtime[0]) is None
    assert result["receipt"]["record_owner"] == "forget_lah"
    assert result["receipt"]["old_scheduled_at"] == state["scheduled_at"]
    assert result["receipt"]["scheduled_at"] == state["slots"][0]["starts_at"]
    assert result["receipt"]["status"] == "STAFF_CHANGED_AWAITING_PATIENT"
    assert runtime[1].post(endpoint, headers=h, json=body).json() == result
    assert runtime[1].post(endpoint, headers=headers(runtime[1]), json=body).status_code == 409
    with runtime[0]() as db:
        change = db.get(StaffAppointmentChange, result["id"])
        assert change.actor_id == result["receipt"]["actor_id"]
        assert change.request["input"]["reason"] == body["reason"]
        message = db.scalar(
            select(SimulatedMessage).where(SimulatedMessage.event_id == result["id"])
        )
        assert "changed by the clinic" in message.body and "Please confirm" in message.body
        assert body["reason"] not in message.body
        assert db.scalar(select(func.count()).select_from(StaffAppointmentChange)) == 1
    event(runtime[1], case_id, "demo_reply", "yes").raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel())
    assert view(runtime[1], case_id)["run"]["status"] == "completed"
    assert view(runtime[1], case_id)["handoff"] is None


@pytest.mark.parametrize("failure", ["slot", "case", "patient"])
def test_bridge_stale_or_mismatched_change_is_rejected(bridge_runtime, failure):
    from forget_lah.db import BridgeFollowupSlot

    runtime, tools, case_id = setup_bridge(bridge_runtime)
    endpoint, body, state = choose(runtime[1], case_id)
    with runtime[0].begin() as db:
        if failure == "slot":
            db.get(BridgeFollowupSlot, body["slot_id"]).status = "withdrawn"
        elif failure == "case":
            db.get(FollowupCase, case_id).case_version += 1
        else:
            row = db.scalar(
                select(BridgeEpisode).where(
                    BridgeEpisode.source_episode_ref
                    == db.get(FollowupCase, case_id).source_episode_ref
                )
            )
            row.patient_id = uid()
    response = runtime[1].post(endpoint, headers=headers(runtime[1]), json=body)
    assert response.status_code in {409, 503}
    with runtime[0]() as db:
        assert db.scalar(select(func.count()).select_from(StaffAppointmentChange)) == 0


def test_notification_failure_does_not_rollback_and_retry_is_idempotent(
    bridge_runtime, monkeypatch
):
    runtime, tools, case_id = setup_bridge(bridge_runtime)
    import forget_lah.staff_changes as changes

    real = changes.ensure_notification
    monkeypatch.setattr(
        changes,
        "ensure_notification",
        lambda *a: (_ for _ in ()).throw(RuntimeError("delivery unavailable")),
    )
    result, endpoint, _, _, _ = apply(runtime[1], case_id)
    assert result["notification_status"] == "pending"
    monkeypatch.setattr(changes, "ensure_notification", real)
    retry = f"{endpoint}/{result['id']}/retry"
    for _ in range(2):
        response = runtime[1].post(retry, headers=headers(runtime[1]))
        assert response.status_code == 200, response.text
    with runtime[0].begin() as db:
        assert db.scalar(select(func.count()).select_from(SimulatedMessage)) == 1
        db.add(
            ChannelBinding(
                id="staff-test",
                clinic_id=result["receipt"].get(
                    "clinic_id", "10000000-0000-4000-8000-000000000001"
                ),
                case_id=case_id,
                recipient="whatsapp:+6590000001",
                enabled=True,
                created_at=utcnow() - timedelta(minutes=1),
                inbound_at=utcnow(),
            )
        )
    collect_messages(runtime[0])

    class Failed:
        def send_text(self, *args):
            raise WhatsAppError("FAILED")

    dispatch_one(runtime[0], Failed())
    with runtime[0]() as db:
        assert db.scalar(select(ChannelOutbox)).status == "failed"
        assert db.get(StaffAppointmentChange, result["id"]).status == "committed"
    runtime[1].post(retry, headers=headers(runtime[1])).raise_for_status()

    class Sent:
        def send_text(self, *args):
            return MessageReceipt("SM" + "a" * 32, "sent", None)

    dispatch_one(runtime[0], Sent())
    with runtime[0]() as db:
        assert db.scalar(select(ChannelOutbox)).status == "sent"
        assert db.scalar(select(func.count()).select_from(ChannelOutbox)) == 1


def test_doctor_constraints_require_current_review(bridge_runtime):
    runtime, tools, case_id = setup_bridge(bridge_runtime)
    with runtime[0].begin() as db:
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        episode.normalized = {**episode.normalized, "doctor_notes": "Attend before January 2020"}
    state = runtime[1].get(f"/api/cases/{case_id}/appointment-change").json()
    assert state["slots"] == [] and state["can_review"]


def test_api_source_change_and_lost_receipt_retry(simulated_runtime):
    from forget_lah.db import session_factory
    from services.mock_clinic.store import Confirmation, Episode, Slot, StaffChange

    runtime, tools, source, engine = simulated_runtime
    runtime[1].app.state.staff_change_tools = tools
    with runtime[0]() as db:
        case = db.scalar(select(FollowupCase).where(FollowupCase.specialty == "myopia"))
        case_id, ref = case.id, case.source_episode_ref
    source_factory = session_factory(engine)
    with source_factory.begin() as db:
        row = db.get(Episode, ref)
        row.doctor_note = ""
        db.add(
            Slot(
                id=uid(),
                specialty="myopia",
                starts_at=utcnow() + timedelta(days=4),
                ends_at=utcnow() + timedelta(days=4, minutes=30),
                doctor="Demo doctor",
            )
        )
    endpoint, body, state = choose(runtime[1], case_id)
    actual = tools.staff_change

    def lost(binding, operation):
        actual(binding, operation)
        raise httpx.ReadTimeout("Lost response")

    tools.staff_change = lost
    result = runtime[1].post(endpoint, headers=headers(runtime[1]), json=body).json()
    assert result["status"] == "pending"
    assert event(runtime[1], case_id, "retry").status_code == 409
    tools.staff_change = actual
    response = runtime[1].post(f"{endpoint}/{result['id']}/retry", headers=headers(runtime[1]))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "committed", response.text
    from forget_lah.runtime.engine import claim_run
    from forget_lah.runtime.models import AgentRun

    with runtime[0]() as db:
        run = db.get(AgentRun, db.get(StaffAppointmentChange, result["id"]).run_id)
        assert run.status == "waiting" and run.available_at is None
    assert claim_run(runtime[0]) is None
    with source_factory() as db:
        assert db.scalar(select(func.count()).select_from(StaffChange)) == 1
        assert db.scalar(select(func.count()).select_from(Confirmation)) == 0
        assert db.get(Episode, ref).version == body["expected_version"] + 1


@pytest.mark.parametrize(
    "kind,reply",
    [
        ("demo_reply", "No, I cannot make it"),
        ("demo_reply", "What should I bring?"),
        ("clinical_concern", "Patient reports a clinical concern"),
    ],
)
def test_staff_change_replies_keep_existing_workflows(bridge_runtime, kind, reply):
    from test_adaptation import BarrierModel

    from forget_lah.runtime.models import AgentStep, BridgeConfirmation

    runtime, tools, case_id = setup_bridge(bridge_runtime)
    apply(runtime[1], case_id)
    if reply.startswith("No"):
        # Add a distinct reserved option for the patient's next reschedule request.
        from forget_lah.db import BridgeFollowupSlot, Principal

        with runtime[0].begin() as db:
            episode = db.scalar(
                select(BridgeEpisode).where(
                    BridgeEpisode.source_episode_ref
                    == db.get(FollowupCase, case_id).source_episode_ref
                )
            )
            db.add(
                BridgeFollowupSlot(
                    clinic_id=episode.clinic_id,
                    episode_id=episode.id,
                    starts_at=(utcnow() + timedelta(days=5)).replace(hour=8),
                    ends_at=(utcnow() + timedelta(days=5)).replace(hour=9),
                    doctor="Follow-up team",
                    approved_by=db.scalar(select(Principal.id)),
                )
            )
    event(runtime[1], case_id, kind, reply).raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel() if reply.startswith("No") else None)
    result = view(runtime[1], case_id)
    with runtime[0]() as db:
        assert db.scalar(select(func.count()).select_from(BridgeConfirmation)) == 0
    if kind == "clinical_concern":
        assert result["handoff"]["risk"] == "RED"
    elif reply.startswith("No"):
        assert any(m["kind"] == "options" for m in result["patient_simulator"]["messages"]), result
    else:
        with runtime[0]() as db:
            assert db.scalar(
                select(AgentStep.id).where(
                    AgentStep.run_id == result["run"]["id"], AgentStep.role == "preparation"
                )
            )


@pytest.mark.postgres
def test_concurrent_staff_change_has_one_winner(bridge_runtime):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    runtime, _, case_id = setup_bridge(bridge_runtime)
    if runtime[0].kw["bind"].dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks")
    endpoint, body, _ = choose(runtime[1], case_id)
    barrier = Barrier(2)

    def send():
        barrier.wait()
        return runtime[1].post(endpoint, headers=headers(runtime[1]), json=body).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(), range(2)))
    assert sorted(results) == [200, 409]
    with runtime[0]() as db:
        assert db.scalar(select(func.count()).select_from(StaffAppointmentChange)) == 1


def test_current_doctor_review_excludes_outside_window(bridge_runtime):
    from test_bridge_runtime import begin

    from forget_lah.runtime.models import AgentStep
    from forget_lah.runtime.routes import latest_run

    runtime, tools, case_id = setup_bridge(bridge_runtime)
    with runtime[0].begin() as db:
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        episode.normalized = {**episode.normalized, "doctor_notes": "Attend before January 2020"}
    begin(runtime, tools, case_id)
    with runtime[0].begin() as db:
        run = latest_run(db, case_id)
        case = db.get(FollowupCase, case_id)
        result = tools.execute(
            "get_approved_instructions",
            {k: getattr(case, k) for k in ("clinic_id", "patient_id", "source_episode_ref")},
        )
        evidence_id, review_id = uid(), uid()
        note = result.data["instructions"][0]
        db.add(
            AgentStep(
                id=evidence_id,
                clinic_id=case.clinic_id,
                case_id=case.id,
                run_id=run.id,
                sequence=101,
                case_version=case.case_version,
                role="preparation",
                origin="rule",
                status="completed",
                tool_result=result.model_dump(),
            )
        )
        db.add(
            AgentStep(
                id=review_id,
                clinic_id=case.clinic_id,
                case_id=case.id,
                run_id=run.id,
                sequence=102,
                case_version=case.case_version,
                role="preparation",
                origin="mock",
                status="completed",
                policy={"decision": "ALLOW"},
                decision={
                    "evidence_ids": [evidence_id],
                    "scheduling_review": [
                        {
                            "instruction_id": note["instruction_id"],
                            "quote": note["approved_text"],
                            "effect": "INFORMATION",
                        }
                    ],
                },
            )
        )
        run.checkpoint = {**run.checkpoint, "question_review_step_id": review_id}
    state = runtime[1].get(f"/api/cases/{case_id}/appointment-change").json()
    assert state["blocked"] is None, state
    assert state["slots"] == []


@pytest.mark.postgres
def test_api_competing_staff_changes_share_source_slot_lock(postgres_schema):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from fastapi.testclient import TestClient

    from forget_lah.source import DEMO_CLINIC_ID
    from services.mock_clinic.app import MockSettings, create_app
    from services.mock_clinic.bootstrap import migrate
    from services.mock_clinic.store import Episode, Slot, StaffChange, envelope, seed

    engine, factory = postgres_schema
    migrate(engine)
    seed(factory)
    slot_id = uid()
    requests = []
    with factory.begin() as db:
        db.add(
            Slot(
                id=slot_id,
                specialty="myopia",
                starts_at=utcnow() + timedelta(days=3),
                ends_at=utcnow() + timedelta(days=3, minutes=30),
                doctor="Shared doctor",
            )
        )
        rows = list(db.scalars(select(Episode).limit(2)))
        for row in rows:
            row.specialty = "myopia"
            row.record_type = "appointment"
            row.source_status = "scheduled"
            row.scheduled_at = utcnow() + timedelta(days=2)
        db.flush()
        for row in rows:
            requests.append(
                (
                    row.ref,
                    {
                        "operation_id": uid(),
                        "clinic_id": DEMO_CLINIC_ID,
                        "patient_id": row.patient_id,
                        "actor_id": uid(),
                        "expected_version": row.version,
                        "expected_source_version": envelope(db, row)["source_version"],
                        "slot_id": slot_id,
                        "slot_version": 1,
                    },
                )
            )
    settings = MockSettings(
        mock_database_url="sqlite://",
        mock_clinic_admin_key="test-admin",
        mock_clinic_followup_key="test-followup",
    )
    app = create_app(settings, engine)
    barrier = Barrier(2)

    def change(item):
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.post(
                f"/internal/followup/{item[0]}/staff-change",
                headers={"X-Followup-Key": "test-followup"},
                json=item[1],
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, requests)) == [200, 409]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StaffChange)) == 1


def test_translation_retry_and_changed_appointment_prevents_old_resend(bridge_runtime):
    runtime, _, case_id = setup_bridge(bridge_runtime)
    result, endpoint, _, _, _ = apply(runtime[1], case_id)
    with runtime[0].begin() as db:
        message = db.scalar(
            select(SimulatedMessage).where(SimulatedMessage.event_id == result["id"])
        )
        message.translation = {"language": "ta", "status": "failed", "error": "TEST"}
    state = runtime[1].get(endpoint).json()
    assert state["changes"][0]["notification_status"] == "failed"
    retry = f"{endpoint}/{result['id']}/retry"
    runtime[1].post(retry, headers=headers(runtime[1])).raise_for_status()
    with runtime[0].begin() as db:
        message = db.scalar(
            select(SimulatedMessage).where(SimulatedMessage.event_id == result["id"])
        )
        assert message.translation["status"] == "pending"
        episode = db.scalar(
            select(BridgeEpisode).where(
                BridgeEpisode.source_episode_ref == db.get(FollowupCase, case_id).source_episode_ref
            )
        )
        episode.version += 1
    assert runtime[1].post(retry, headers=headers(runtime[1])).status_code == 409


@pytest.mark.parametrize("fault", ["unauthorized", "patient", "version", "slot", "source"])
def test_api_source_rejects_invalid_authority_and_stale_bindings(simulated_runtime, fault):
    from forget_lah.db import session_factory
    from services.mock_clinic.store import Episode, Slot, StaffChange, envelope

    runtime, _, source, engine = simulated_runtime
    factory = session_factory(engine)
    with factory.begin() as db:
        row = db.scalar(select(Episode).where(Episode.specialty == "myopia"))
        slot = Slot(
            id=uid(),
            specialty="myopia",
            starts_at=utcnow() + timedelta(days=4),
            ends_at=utcnow() + timedelta(days=4, minutes=30),
            doctor="Demo doctor",
        )
        db.add(slot)
        db.flush()
        ref = row.ref
        body = {
            "operation_id": uid(),
            "clinic_id": "10000000-0000-4000-8000-000000000001",
            "patient_id": row.patient_id,
            "actor_id": uid(),
            "expected_version": row.version,
            "expected_source_version": envelope(db, row)["source_version"],
            "slot_id": slot.id,
            "slot_version": slot.version,
        }
        original = row.scheduled_at
    if fault == "patient":
        body["patient_id"] = uid()
    if fault == "version":
        body["expected_version"] += 1
    if fault == "slot":
        body["slot_version"] += 1
    if fault == "source":
        body["expected_source_version"] = "stale"
    response = source.post(
        f"/internal/followup/{ref}/staff-change",
        headers={
            "X-Followup-Key": "invalid" if fault == "unauthorized" else "test-only-followup-key"
        },
        json=body,
    )
    assert response.status_code in {403, 404, 409}
    with factory() as db:
        assert db.get(Episode, ref).scheduled_at == original
        assert db.scalar(select(func.count()).select_from(StaffChange)) == 0


def test_staff_change_requires_csrf_and_current_clinic_membership(bridge_runtime):
    from forget_lah.db import Membership

    runtime, _, case_id = setup_bridge(bridge_runtime)
    endpoint, body, _ = choose(runtime[1], case_id)
    assert runtime[1].post(endpoint, json=body).status_code == 403
    with runtime[0].begin() as db:
        for membership in db.scalars(select(Membership)):
            membership.active = False
    assert runtime[1].get(endpoint).status_code in {403, 404}
    assert runtime[1].post(endpoint, json=body, headers=headers(runtime[1])).status_code in {
        403,
        404,
    }


def test_api_rejection_preserves_existing_waiting_review(simulated_runtime):
    from test_runtime import start

    from forget_lah.db import session_factory
    from services.mock_clinic.store import Episode, Slot

    runtime, tools, _, engine = simulated_runtime
    runtime[1].app.state.staff_change_tools = tools
    with session_factory(engine).begin() as db:
        row = db.scalar(select(Episode).where(Episode.specialty == "myopia"))
        row.doctor_note = ""
        db.add(
            Slot(
                id=uid(),
                specialty="myopia",
                starts_at=utcnow() + timedelta(days=4),
                ends_at=utcnow() + timedelta(days=4, minutes=30),
                doctor="Demo doctor",
            )
        )
    case_id, run_id = start(runtime, "myopia")
    drain(runtime, tools=tools)
    before = view(runtime[1], case_id)
    assert before["run"]["status"] == "waiting"
    endpoint, body, _ = choose(runtime[1], case_id)

    def rejected(*args):
        response = httpx.Response(409, request=httpx.Request("POST", "http://source"))
        response.raise_for_status()

    tools.staff_change = rejected
    result = runtime[1].post(endpoint, headers=headers(runtime[1]), json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "rejected"
    after = view(runtime[1], case_id)
    assert after["run"]["id"] == run_id
    assert after["run"]["status"] == "waiting"
    assert after["patient_simulator"]["messages"] == before["patient_simulator"]["messages"]


@pytest.mark.parametrize("changed", [None, "handoff_accepted", "source_changed"])
def test_repair_unanswered_timer_preserves_receipt_notice_and_error_history(
    bridge_runtime, changed
):
    import json

    from forget_lah.runtime.engine import claim_run
    from forget_lah.runtime.models import AgentRun, StaffHandoff
    from forget_lah.runtime.provider import MockModel, ModelReply
    from forget_lah.seed import seed_automation
    from forget_lah.staff_changes import recover_unanswered_staff_timer

    runtime, tools, case_id = setup_bridge(bridge_runtime)
    seed_automation(runtime[0])
    result, *_ = apply(runtime[1], case_id)
    with runtime[0].begin() as db:
        change = db.get(StaffAppointmentChange, result["id"])
        old_id = change.run_id
        db.get(AgentRun, old_id).available_at = utcnow()  # Reproduce pre-fix INSERT default.
        notice = db.scalar(select(SimulatedMessage).where(SimulatedMessage.event_id == change.id))
        old_notice = (notice.id, notice.body, notice.event_id, notice.created_at)
        receipt = change.receipt

    class TimerModel(MockModel):
        def decide(self, obs, **kwargs):
            if obs["tools"]:
                return ModelReply(
                    json.dumps(
                        {
                            "request_id": obs["request_id"],
                            "expected_case_version": obs["expected_case_version"],
                            "step_type": "ESCALATE",
                            "reason_code": "CAPABILITY_UNAVAILABLE",
                        }
                    )
                )
            return super().decide(obs, **kwargs)

    drain(runtime, tools=tools, model=TimerModel())
    if changed:
        with runtime[0].begin() as db:
            if changed == "handoff_accepted":
                db.scalar(
                    select(StaffHandoff).where(StaffHandoff.run_id == old_id)
                ).accepted_by = db.get(StaffAppointmentChange, result["id"]).actor_id
            else:
                episode = db.scalar(
                    select(BridgeEpisode).where(
                        BridgeEpisode.source_episode_ref
                        == db.get(FollowupCase, case_id).source_episode_ref
                    )
                )
                episode.version += 1
        with runtime[0].begin() as db, pytest.raises(ValueError):
            recover_unanswered_staff_timer(db, result["id"], tools)
        return
    with runtime[0].begin() as db:
        new_id = recover_unanswered_staff_timer(db, result["id"], tools)
    assert claim_run(runtime[0]) is None
    with runtime[0]() as db:
        assert db.get(AgentRun, new_id).status == "waiting"
        assert db.get(AgentRun, old_id).status == "paused"
        assert (
            db.scalar(select(StaffHandoff).where(StaffHandoff.run_id == old_id)).reason_code
            == "CAPABILITY_UNAVAILABLE"
        )
        assert db.get(StaffAppointmentChange, result["id"]).receipt == receipt
        notice = db.scalar(
            select(SimulatedMessage).where(SimulatedMessage.event_id == result["id"])
        )
        assert (notice.id, notice.body, notice.event_id, notice.created_at) == old_notice
        assert db.scalar(select(func.count()).select_from(SimulatedMessage)) == 1
    event(runtime[1], case_id, "demo_reply", "yes").raise_for_status()
    drain(runtime, tools=tools, model=OmarReplyModel())
    assert view(runtime[1], case_id)["run"]["status"] == "completed"
    assert view(runtime[1], case_id)["handoff"] is None
