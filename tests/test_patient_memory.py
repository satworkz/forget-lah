import json

import pytest
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_runtime import drain, event, headers, start, view
from test_simulator import simulator as simulator

from forget_lah.runtime.adaptation import matching_slots
from forget_lah.runtime.provider import MockModel, ModelReply


class NeedsModel(MockModel):
    def __init__(self, updates, question=None, invalid=False, intent="UNSPECIFIED", concern=None):
        self.updates, self.question, self.invalid = updates, question, invalid
        self.intent, self.concern = intent, concern

    def decide(self, obs, **kwargs):
        e = obs["latest_event"]
        if obs["role"] == "coordinator" and e["kind"] == "demo_reply" and not obs["needs_reviewed"]:
            return ModelReply(
                json.dumps(
                    dict(
                        request_id=obs["request_id"],
                        expected_case_version=obs["expected_case_version"],
                        step_type="REVIEW_NEEDS",
                        reason_code="PATIENT_NEEDS_REVIEWED",
                        reply_event_id=e.get("reply_event_id", e["id"]),
                        updates=[
                            dict(
                                key=k,
                                value=v,
                                scope=scope,
                                quote="invented quote" if self.invalid else e["content"],
                            )
                            for k, v, scope in self.updates
                        ],
                        question=self.question,
                        appointment_intent=self.intent,
                        appointment_request_quote=e["content"]
                        if self.intent != "UNSPECIFIED"
                        else None,
                        concern_quote=self.concern,
                    )
                )
            )
        return super().decide(obs, **kwargs)


def setup_reply(fixture, text, model):
    runtime, tools, _, _ = fixture
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    drain(runtime, tools=tools, model=model)
    return case, view(runtime[1], case)


def test_stop_persists_and_requires_explicit_resume(simulated_runtime):
    runtime, tools, _, _ = simulated_runtime
    case, result = setup_reply(
        simulated_runtime,
        "Don't disturb me",
        NeedsModel([("contact_permission", "stopped", "future")]),
    )
    assert result["run"]["status"] == "waiting"
    assert "stopped automated reminders" in result["patient_simulator"]["messages"][-1]["body"]
    record = result["preferences"]["records"][0]
    url = f"/api/cases/{case}/preferences/{record['id']}/remove"
    response = runtime[1].post(
        url, headers=headers(runtime[1]), json={"expected_case_version": result["case_version"]}
    )
    assert response.status_code == 422
    runtime[1].post(
        f"/api/cases/{case}/agent/runs",
        headers=headers(runtime[1]),
        json={"expected_case_version": result["case_version"], "fresh_simulation": True},
    ).raise_for_status()
    drain(runtime, tools=tools)
    fresh = view(runtime[1], case)
    assert fresh["patient_simulator"]["messages"] == []
    runtime[1].post(
        url,
        headers=headers(runtime[1]),
        json={"expected_case_version": fresh["case_version"], "resume_contact": True},
    ).raise_for_status()
    assert not view(runtime[1], case)["preferences"].get("records")


@pytest.mark.parametrize(
    "updates,text,expected",
    [
        ([("excluded_weekdays", "5", "future")], "I don't want Saturday", "excluded_weekdays"),
        (
            [("arrival_support", "needs_clarification", "future")],
            "I will always be late",
            "arrival_support",
        ),
        (
            [("excluded_languages", "en", "future"), ("preferred_language", "und", "future")],
            "Don't contact me in English",
            "excluded_languages",
        ),
    ],
)
def test_concerns_saved_and_questioned(simulated_runtime, updates, text, expected):
    case, result = setup_reply(
        simulated_runtime, text, NeedsModel(updates, "What would work better for you?")
    )
    assert result["run"]["status"] == "waiting"
    assert any(
        r["key"] == expected and r["quote"] == text for r in result["preferences"]["records"]
    )
    if expected == "excluded_weekdays":
        assert (
            matching_slots([{"starts_at": "2030-01-05T02:00:00+00:00"}], result["preferences"])
            == []
        )
    if expected == "arrival_support":
        assert result["preferences"]["records"][0]["status"] == "pending"
    if expected == "excluded_languages":
        assert "您" in result["patient_simulator"]["messages"][-1]["body"]


def test_known_language_handoff_without_english_message(simulated_runtime):
    case, result = setup_reply(
        simulated_runtime,
        "Please speak Mandarin",
        NeedsModel([("preferred_language", "zh", "future")]),
    )
    assert result["run"]["status"] == "escalated"
    assert result["handoff"]["reason_code"] == "LANGUAGE_SUPPORT_REQUIRED"
    assert "语言" in result["patient_simulator"]["messages"][-1]["body"]


def test_invented_preference_quote_is_rejected(simulated_runtime):
    case, result = setup_reply(
        simulated_runtime, "Hello", NeedsModel([("excluded_weekdays", "5", "future")], invalid=True)
    )
    assert not result["preferences"].get("records")
    assert any(
        s["policy"] and "MEMORY_QUOTE_NOT_IN_PATIENT_REPLY" in s["policy"]["reason_codes"]
        for s in result["steps"]
    )


def test_memory_scope_correction_and_clinic_isolation(simulated_runtime):
    from types import SimpleNamespace

    from sqlalchemy import select

    from forget_lah.db import FollowupCase, uid
    from forget_lah.runtime.contracts import NeedsDecision
    from forget_lah.runtime.memory import effective_memory, persist_needs
    from forget_lah.runtime.models import PatientMemory

    runtime, tools, _, _ = simulated_runtime
    case_id, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    with runtime[0].begin() as db:
        case = db.get(FollowupCase, case_id)

        def change(key, value, scope, operation="set"):
            step = uid()
            decision = NeedsDecision(
                request_id=step,
                expected_case_version=case.case_version,
                step_type="REVIEW_NEEDS",
                reason_code="PATIENT_NEEDS_REVIEWED",
                reply_event_id=uid(),
                updates=[
                    dict(key=key, value=value, scope=scope, operation=operation, quote="fixture")
                ],
            )
            persist_needs(db, case, decision, step)

        change("excluded_weekdays", "5", "future")
        change("excluded_minutes", "600", "visit")
        other = SimpleNamespace(id=uid(), clinic_id=case.clinic_id, patient_id=case.patient_id)
        assert effective_memory(db, other) == {"excluded_weekdays": [5]}
        stranger = SimpleNamespace(id=case.id, clinic_id=uid(), patient_id=case.patient_id)
        assert effective_memory(db, stranger) == {}
        change("excluded_weekdays", "5,6", "future")
        assert effective_memory(db, case)["excluded_weekdays"] == [5, 6]
        change("excluded_weekdays", "", "future", "remove")
        assert effective_memory(db, case) == {"excluded_minutes": [600]}
        assert {r.status for r in db.scalars(select(PatientMemory))} == {
            "active",
            "superseded",
            "retracted",
        }


def test_mixed_symptoms_and_stop_contact_are_both_retained(simulated_runtime):
    class ClinicalStop(MockModel):
        def decide(self, obs, **kwargs):
            e = obs["latest_event"]
            if e["kind"] == "demo_reply":
                return ModelReply(
                    json.dumps(
                        dict(
                            request_id=obs["request_id"],
                            expected_case_version=obs["expected_case_version"],
                            step_type="REPORT_SYMPTOMS",
                            reason_code="PATIENT_REPORTED_SYMPTOMS",
                            reply_event_id=e.get("reply_event_id", e["id"]),
                            symptom_quotes=["my eye hurts"],
                            contact_stop_quote="stop reminders",
                        )
                    )
                )
            return super().decide(obs, **kwargs)

    case, result = setup_reply(simulated_runtime, "my eye hurts; stop reminders", ClinicalStop())
    assert result["handoff"]["risk"] == "RED"
    assert any(r["key"] == "contact_permission" for r in result["preferences"]["records"])
    assert "reminders have been stopped" in result["patient_simulator"]["messages"][-1]["body"]
