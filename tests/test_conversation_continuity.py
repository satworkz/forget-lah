"""Offline channel-path regressions from the recorded September 23 conversations."""

import json

import httpx
import pytest
from pydantic import ValidationError
from test_channel import ingest_test_reply
from test_patient_memory import NeedsModel
from test_patient_questions import QuestionModel
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator
from test_translations import settings as translation_settings

from forget_lah.runtime.contracts import NeedsDecision
from forget_lah.runtime.provider import ModelReply
from forget_lah.translations import translate

NOTE = "Eyes will be blurry after the appointment; please bring someone to accompany you."
DRIVING = "我会在上午10点到。看诊后我打算自己开车回家。"
ASSISTANCE = "好的，我会请家人陪我来，并送我回家。我不会自己开车。"


class SocialModel(NeedsModel):
    def __init__(self, kind="ACKNOWLEDGEMENT"):
        super().__init__([])
        self.kind = kind

    def decide(self, obs, **kwargs):
        value = json.loads(super().decide(obs, **kwargs).text)
        assert value["step_type"] == "REVIEW_NEEDS", (
            "Social replies must stop after one interpretation"
        )
        value["reply_kind"] = self.kind
        return ModelReply(json.dumps(value))


def plan_model(text, relation):
    return QuestionModel(
        "GUIDANCE",
        NOTE,
        task=text,
        plan=True,
        relation=relation,
        practical_issue="TRANSPORT_OR_ACCOMPANIMENT",
        dependency="DRIVING",
        actions=["FOLLOW_CLINIC_INSTRUCTION", "ARRANGE_ASSISTANCE"]
        if relation == "CONFLICTS"
        else [],
    )


@pytest.mark.parametrize("whatsapp", [False, True])
def test_conflict_waits_through_thanks_then_resolves_before_one_confirmation(
    simulated_runtime, whatsapp
):
    runtime, tools, source, engine = simulated_runtime
    body = episode_body(source)
    body["doctor_note"] = NOTE
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)

    def send(text):
        if whatsapp:
            ingest_test_reply(runtime, case, text)
        else:
            event(runtime[1], case, "demo_reply", text).raise_for_status()

    send(DRIVING)
    drain(runtime, tools=tools, model=plan_model(DRIVING, "CONFLICTS"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    assert result["run"]["wait_reason"] == "AWAITING_COMPATIBLE_PLAN"
    assert source_count(engine) == 0
    assert result["patient_simulator"]["messages"][-1]["kind"] == "plan_conflict"
    assert not any(
        (s.get("decision") or {}).get("step_type") == "INTERPRET_ATTENDANCE"
        for s in result["steps"]
    )

    send("谢谢")
    drain(runtime, tools=tools, model=SocialModel())
    assert source_count(engine) == 0
    assert view(runtime[1], case)["patient_simulator"]["messages"][-1]["body"] == "You're welcome."

    # Mere attendance acceptance must not erase the incompatible transport plan.
    send("Yes I will attend")
    drain(runtime, tools=tools, model=NeedsModel([], intent="CONFIRM"))
    assert source_count(engine) == 0
    assert view(runtime[1], case)["run"]["status"] == "waiting"

    send(ASSISTANCE)
    drain(runtime, tools=tools, model=plan_model(ASSISTANCE, "SATISFIES"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result
    assert source_count(engine) == 1


@pytest.mark.parametrize(
    "text,kind",
    [
        ("thank you", "ACKNOWLEDGEMENT"),
        ("谢谢", "ACKNOWLEDGEMENT"),
        ("terima kasih", "ACKNOWLEDGEMENT"),
        ("hi", "GREETING"),
    ],
)
def test_social_reply_after_completion_never_reconfirms_or_rechecks(simulated_runtime, text, kind):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    ingest_test_reply(runtime, case, "I confirm my attendance")
    drain(runtime, tools=tools)
    before = source_count(engine)
    assert before == 1
    ingest_test_reply(runtime, case, text)
    drain(runtime, tools=tools, model=SocialModel(kind))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed"
    assert result["run"]["outcome"] == "CONVERSATION_ACKNOWLEDGED"
    assert source_count(engine) == before
    assert [m["kind"] for m in result["patient_simulator"]["messages"]] == [
        "conversation_acknowledgement"
    ]


@pytest.mark.parametrize("completed", [False, True])
def test_mixed_thanks_and_cancellation_reaches_staff_without_source_write(
    simulated_runtime, completed
):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    if completed:
        ingest_test_reply(runtime, case, "I confirm my attendance")
        drain(runtime, tools=tools)
    before = source_count(engine)
    ingest_test_reply(runtime, case, "Thank you, but cancel my appointment")
    drain(runtime, tools=tools, model=NeedsModel([], intent="CANCEL"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "escalated"
    assert result["handoff"]["reason_code"] == "CANCELLATION_REQUESTED"
    assert "not been cancelled yet" in result["patient_simulator"]["messages"][-1]["body"]
    assert source_count(engine) == before


def test_social_contract_cannot_hide_a_cancellation():
    with pytest.raises(ValidationError, match="Social-only"):
        NeedsDecision(
            request_id="r" * 36,
            expected_case_version=1,
            step_type="REVIEW_NEEDS",
            reason_code="PATIENT_NEEDS_REVIEWED",
            reply_event_id="a" * 36,
            updates=[],
            reply_kind="ACKNOWLEDGEMENT",
            appointment_intent="CANCEL",
            appointment_request_quote="cancel my appointment",
        )


def test_chinese_translation_includes_quoted_clinic_instruction():
    output = '诊所建议："看诊后视力会模糊，请安排一位陪同者。"'

    def respond(request):
        payload = json.loads(request.content)
        assert "Translate quoted clinic instructions" in payload["system"]
        assert NOTE in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps({"text": output})}],
            },
        )

    assert (
        translate(
            translation_settings(),
            f'The clinic advised: "{NOTE}"',
            "zh",
            transport=httpx.MockTransport(respond),
        )
        == output
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_scan_question_allows_social_reply_or_cancellation_without_answering_check(
    simulated_runtime, cancel
):
    from test_doctor_actions_dynamic import SCAN_NOTE, scan_model, set_note

    from forget_lah.runtime.provider import decision_formats_for

    runtime, tools, source, engine = simulated_runtime
    set_note(source, "DEMO-ANTENATAL-VISIT-01", SCAN_NOTE)
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    ingest_test_reply(runtime, case, "I confirm my attendance")
    drain(runtime, tools=tools, model=scan_model())
    before = view(runtime[1], case)
    assert before["patient_simulator"]["messages"][-1]["kind"] == "doctor_instruction_check"

    class InterruptModel(NeedsModel):
        def decide(self, obs, **kwargs):
            assert "REVIEW_NEEDS" in decision_formats_for(obs)
            if cancel:
                return super().decide(obs, **kwargs)
            return SocialModel().decide(obs, **kwargs)

    ingest_test_reply(runtime, case, "Thank you, cancel my appointment" if cancel else "thank you")
    drain(
        runtime, tools=tools, model=InterruptModel([], intent="CANCEL" if cancel else "UNSPECIFIED")
    )
    result = view(runtime[1], case)
    assert source_count(engine) == 0
    assert (
        sum(
            m["kind"] == "doctor_instruction_check" for m in result["patient_simulator"]["messages"]
        )
        == 1
    )
    assert result["run"]["status"] == ("escalated" if cancel else "waiting")


def test_scan_booking_acknowledgement_does_not_dump_staff_protocol(simulated_runtime):
    from sqlalchemy import select
    from test_doctor_actions_dynamic import test_rich_scan_answer_filters_dates_through_booking

    from forget_lah.runtime.models import SimulatedMessage

    test_rich_scan_answer_filters_dates_through_booking(simulated_runtime, "book", True)
    with simulated_runtime[0][0]() as db:
        messages = list(
            db.scalars(select(SimulatedMessage).where(SimulatedMessage.kind == "acknowledgement"))
        )
        assert messages
        assert all("confirm with patient" not in m.body.lower() for m in messages)


def test_thanks_with_new_symptoms_is_not_social_closure(simulated_runtime):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    ingest_test_reply(runtime, case, "I confirm my attendance")
    drain(runtime, tools=tools)
    before = source_count(engine)

    class SymptomModel:
        def decide(self, obs, **kwargs):
            return ModelReply(
                json.dumps(
                    dict(
                        request_id=obs["request_id"],
                        expected_case_version=obs["expected_case_version"],
                        step_type="REPORT_SYMPTOMS",
                        reason_code="PATIENT_REPORTED_SYMPTOMS",
                        reply_event_id=obs["latest_event"]["id"],
                        symptom_quotes=["I have swelling and pain now"],
                    )
                )
            )

    ingest_test_reply(runtime, case, "Thank you, but I have swelling and pain now")
    drain(runtime, tools=tools, model=SymptomModel())
    result = view(runtime[1], case)
    assert result["handoff"]["risk"] == "RED"
    assert source_count(engine) == before
