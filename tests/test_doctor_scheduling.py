import json
from datetime import UTC, datetime, timedelta

import pytest
from test_adaptation import BarrierModel, add_slot
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import ModelReply
from forget_lah.runtime.scheduling import compatible, normalize_review


class ReviewedModel(BarrierModel):
    def __init__(self, bound, fault=None):
        super().__init__()
        self.bound, self.fault = bound, fault

    def decide(self, obs, **kwargs):
        response = super().decide(obs, **kwargs)
        value = json.loads(response.text)
        if obs["role"] == "preparation" and value["step_type"] == "RETURN":
            review = value["scheduling_review"]
            for item in review:
                item.update(effect="DATE_WINDOW", date_to=self.bound)
            if self.fault == "duplicate":
                review.append({**review[0], "effect": "INFORMATION", "date_to": None})
            if self.fault == "missing":
                value.pop("scheduling_review")
            if self.fault == "quote":
                review[0]["quote"] = "Invented clinic permission"
            return ModelReply(json.dumps(value))
        return response


@pytest.mark.parametrize("allowed", [False, True])
def test_doctor_deadline_filters_offer_before_any_booking(simulated_runtime, allowed):
    runtime, tools, source, engine = simulated_runtime
    slot = add_slot(source, 17)
    bound = (datetime.now(UTC) + timedelta(days=4 if allowed else 2)).date().isoformat()
    body = episode_body(source)
    body["doctor_note"] = (
        "Bring your booklet. This mandatory appointment must be completed by " + bound + "."
    )
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only after 3 pm please").raise_for_status()
    drain(runtime, tools=tools, model=ReviewedModel(bound))
    result = view(runtime[1], case)
    message = result["patient_simulator"]["messages"][-1]
    assert source_count(engine) == 0
    if allowed:
        assert result["run"]["status"] == "waiting"
        assert [s["id"] for s in message["evidence"]["slots"]] == [slot]
        assert message["evidence"]["scheduling_review_step_id"]
    else:
        assert result["run"]["status"] == "escalated"
        assert message["evidence"]["slots"] == []
        assert body["doctor_note"] in message["original_body"]
        assert "requested a call" in message["original_body"]
        assert "Option 1" not in message["original_body"]
        assert result["handoff"]


@pytest.mark.parametrize("fault", ["missing", "quote"])
def test_unreviewed_or_forged_notes_cannot_authorize_offer(simulated_runtime, fault):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 17)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only after 3 pm please").raise_for_status()
    bound = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
    drain(runtime, tools=tools, model=ReviewedModel(bound, fault))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "paused"
    assert not any(m["kind"] == "options" for m in result["patient_simulator"]["messages"])
    assert source_count(engine) == 0


def test_date_bounds_use_singapore_days_and_unknown_restrictions_fail_closed():
    slots = [
        {"id": "last", "starts_at": "2026-09-30T15:59:00Z"},
        {"id": "late", "starts_at": "2026-09-30T16:00:00Z"},
    ]
    review = [
        {
            "effect": "DATE_WINDOW",
            "quote": "Timing",
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
        }
    ]
    assert [s["id"] for s in compatible(slots, review)] == ["last"]
    assert not compatible(slots, None)
    assert not compatible(slots, [{"effect": "CLINIC_REVIEW", "quote": "Timing uncertain"}])


@pytest.mark.parametrize("change", ["doctor_note", "legacy_offer"])
def test_booking_requires_current_reviewed_offer(simulated_runtime, change):
    from sqlalchemy import select

    from forget_lah.runtime.models import SimulatedMessage
    from forget_lah.runtime.provider import MockModel

    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 17)
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only after 3 pm please").raise_for_status()
    drain(runtime, tools=tools, model=BarrierModel())
    bound = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    if change == "doctor_note":
        body = episode_body(source)
        body["doctor_note"] = "The visit must be completed by " + bound
        source.put(
            "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
        ).raise_for_status()
    else:
        with runtime[0].begin() as db:
            offer = db.scalar(
                select(SimulatedMessage).where(
                    SimulatedMessage.case_id == case, SimulatedMessage.kind == "options"
                )
            )
            offer.evidence = {
                k: v for k, v in offer.evidence.items() if k != "scheduling_review_step_id"
            }
    event(runtime[1], case, "demo_reply", "option 1 is fine").raise_for_status()

    class SelectionReview(MockModel):
        def decide(self, obs, **kwargs):
            response = super().decide(obs, **kwargs)
            value = json.loads(response.text)
            if (
                change == "doctor_note"
                and obs["role"] == "preparation"
                and value["step_type"] == "RETURN"
            ):
                for r in value["scheduling_review"]:
                    r.update(effect="DATE_WINDOW", date_to=bound)
            return ModelReply(json.dumps(value))

    drain(runtime, tools=tools, model=SelectionReview())
    result = view(runtime[1], case)
    assert source_count(engine) == 0
    assert result["run"]["status"] == ("escalated" if change == "doctor_note" else "waiting")


@pytest.mark.parametrize(
    "phrase,lower,upper",
    [
        ("before October 2027", None, "2027-09-30"),
        ("by October 2027", None, "2027-10-31"),
        ("not before October 2027", "2027-10-01", None),
        ("after February 2028", "2028-03-01", None),
        ("before 2027-10-01", None, "2027-09-30"),
        ("on or before 15 October 2027", None, "2027-10-15"),
    ],
)
def test_explicit_source_date_boundaries_override_model_omissions(phrase, lower, upper):
    review = normalize_review([{"effect": "INFORMATION", "quote": "Appointment " + phrase}])
    assert review[0]["effect"] == "DATE_WINDOW"
    assert review[0].get("date_from") == lower
    assert review[0].get("date_to") == upper


def test_multiple_requirements_in_one_note_do_not_drop_deadline(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    add_slot(source, 17)
    bound = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    body = episode_body(source)
    body["doctor_note"] = "Bring your booklet. Complete appointment by " + bound
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "Only after 3 pm please").raise_for_status()
    drain(runtime, tools=tools, model=ReviewedModel(bound, "duplicate"))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "escalated"
    assert result["patient_simulator"]["messages"][-1]["evidence"]["slots"] == []
    assert source_count(engine) == 0
