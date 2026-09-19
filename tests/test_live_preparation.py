import os

import pytest
from pydantic import SecretStr
from test_patient_simulation import simulated_runtime as simulated_runtime
from test_patient_simulation import source_count
from test_runtime import drain, event, start, view
from test_simulator import ADMIN, episode_body
from test_simulator import simulator as simulator

from forget_lah.runtime.provider import AnthropicModel


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
def test_live_walking_reply_full_review(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    note = "Eyes will be blurry after the appointment, please bring someone to accompany you"
    body = episode_body(source)
    body["doctor_note"] = note
    source.put(
        "/internal/admin/episodes/DEMO-MYOPIA-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(
        runtime[1], case, "demo_reply", "Sure, clinic is near by I can come by walk"
    ).raise_for_status()
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    drain(runtime, tools=tools, model=AnthropicModel(settings))
    result = view(runtime[1], case)
    print("Live flow status:", result["run"]["status"], "handoff:", bool(result["handoff"]))
    assert result["run"]["status"] == "completed", result["run"]
    assert not result["handoff"]
    for step in result["steps"]:
        decision = step.get("decision") or {}
        if decision.get("step_type") == "REVIEW_NEEDS":
            assert not decision["updates"]
    assert source_count(engine) == 1
    messages = result["patient_simulator"]["messages"]
    assert len(messages) == 2
    assert messages[0]["body"].startswith("Hello Alex,")
    assert messages[-1]["body"].count(note) == 1
    assert "callback" not in messages[-1]["body"]
    print("Patient response:", messages[-1]["body"])


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
def test_live_tamil_confirmation_after_language_switch(simulated_runtime):
    runtime, tools, source, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentRun

    runtime[2].multilingual_enabled = True
    runtime[2].agent_model_mode = "anthropic"
    runtime[2].anthropic_api_key = settings.anthropic_api_key
    with runtime[0].begin() as db:
        db.scalar(select(AgentRun).where(AgentRun.case_id == case)).mode = "anthropic"
    model = AnthropicModel(settings)
    event(runtime[1], case, "demo_reply", "உங்களால் தமிழில் பதிலளிக்க முடியுமா?").raise_for_status()
    drain(runtime, tools=tools, model=model)
    assert view(runtime[1], case)["run"]["status"] == "waiting"
    event(runtime[1], case, "demo_reply", "ஆம்").raise_for_status()
    # Staff pause/retry must preserve the actual patient's evidence binding.
    event(runtime[1], case, "pause").raise_for_status()
    event(runtime[1], case, "retry").raise_for_status()
    drain(runtime, tools=tools, model=model)
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result["run"]
    assert result["handoff"] is None
    assert source_count(engine) == 1


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
def test_live_month_evening_request_searches_without_clarifying(simulated_runtime):
    from datetime import UTC, datetime

    from sqlalchemy import select
    from test_simulator import ADMIN, new_slot

    from forget_lah.runtime.models import AgentRun

    runtime, tools, source, engine = simulated_runtime
    now = datetime.now(UTC)
    year = now.year if now.month <= 10 else now.year + 1
    slot_ids = []
    for month, hour in [(10, 11), (10, 2), (11, 11)]:
        response = source.post(
            "/internal/admin/slots",
            headers=ADMIN,
            json=new_slot(
                specialty="myopia",
                starts_at=f"{year}-{month:02d}-28T{hour:02d}:00:00+00:00",
                ends_at=f"{year}-{month:02d}-28T{hour:02d}:30:00+00:00",
            ),
        )
        response.raise_for_status()
        slot_ids.append(response.json()["id"])
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(
        runtime[1], case, "demo_reply", "எனக்கு அக்டோபர் மாதம் பிடிக்கும்; அதேபோல் மாலை நேரமும் பிடிக்கும்."
    ).raise_for_status()
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    enable_live_translation(runtime, case, settings)
    drain(runtime, tools=tools, model=AnthropicModel(settings))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result
    assert result["handoff"] is None
    assert source_count(engine) == 0
    assert all(r["key"] == "preferred_language" for r in result["preferences"].get("records", []))
    with runtime[0]() as db:
        barriers = db.scalar(select(AgentRun).where(AgentRun.case_id == case)).checkpoint[
            "barriers"
        ]
        assert barriers["date_from"].endswith("-10-01")
        assert barriers["date_to"].endswith("-10-31")
        assert barriers["excluded_minutes"] == []
        assert barriers["next_action"] == "SEARCH_SLOTS"
        assert barriers["earliest_minute"] == 1020
        assert barriers["latest_minute"] == 1439
    offer = result["patient_simulator"]["messages"][-1]
    assert offer["kind"] == "options"
    assert [slot["id"] for slot in offer["evidence"]["slots"]] == [slot_ids[0]]

    # A partial reply refines the time without losing the previously supplied month.
    event(runtime[1], case, "demo_reply", "After 6 pm please").raise_for_status()
    drain(runtime, tools=tools, model=AnthropicModel(settings))
    # A bounded retry for provider-truncated JSON uses the same saved patient event.
    if view(runtime[1], case)["run"].get("pause_reason") == "MODEL_OUTPUT_TRUNCATED":
        event(runtime[1], case, "retry").raise_for_status()
        drain(runtime, tools=tools, model=AnthropicModel(settings))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result["run"]
    assert result["handoff"] is None
    assert source_count(engine) == 0
    with runtime[0]() as db:
        refined = db.scalar(select(AgentRun).where(AgentRun.case_id == case)).checkpoint["barriers"]
        assert refined["date_from"] == barriers["date_from"]
        assert refined["date_to"] == barriers["date_to"]
        assert refined["earliest_minute"] == 1080
        assert refined["next_action"] == "SEARCH_SLOTS"
    offer = result["patient_simulator"]["messages"][-1]
    assert [slot["id"] for slot in offer["evidence"]["slots"]] == [slot_ids[0]]


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
@pytest.mark.parametrize(
    "text", ["I cant travel in hot sun", "I prefer less traffic time", "avoid office time"]
)
def test_live_practical_concern_asks_for_details(simulated_runtime, text):
    runtime, tools, _, engine = simulated_runtime
    case, _ = start(runtime, "myopia")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", text).raise_for_status()
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    drain(runtime, tools=tools, model=AnthropicModel(settings))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result["run"]
    assert result["handoff"] is None
    assert source_count(engine) == 0
    records = result["preferences"]["records"]
    assert any(r["key"] == "other_concern" and r["quote"] in text for r in records)
    assert all(r["key"] == "other_concern" and r["scope"] == "visit" for r in records)
    assert result["patient_simulator"]["messages"][-1]["kind"] == "clarification"


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
def test_live_malay_acceptance_books_missed_followup(simulated_runtime):
    from test_recall_booking import QUESTION
    from test_simulator import ADMIN, new_slot

    runtime, tools, source, engine = simulated_runtime
    source.post(
        "/internal/admin/slots", headers=ADMIN, json=new_slot(specialty="antenatal")
    ).raise_for_status()
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", QUESTION).raise_for_status()
    drain(runtime, tools=tools)
    offered = view(runtime[1], case)
    assert offered["patient_simulator"]["messages"][-1]["kind"] == "options"
    assert len(offered["patient_simulator"]["messages"][-1]["evidence"]["slots"]) == 1
    event(runtime[1], case, "demo_reply", "ya, sahkan").raise_for_status()
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    drain(runtime, tools=tools, model=AnthropicModel(settings))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "completed", result["run"]
    assert result["handoff"] is None
    assert source_count(engine) == 1
    assert result["plan"]["attendance"] == "Source confirmed"


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
def test_live_tamil_comprehension_repair(simulated_runtime):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select
    from test_simulator import ADMIN, episode_body

    from forget_lah.runtime.models import AgentRun

    runtime, tools, source, engine = simulated_runtime
    body = episode_body(source, "DEMO-ANTENATAL-VISIT-01")
    body.update(
        source_status="no_show", scheduled_at=(datetime.now(UTC) - timedelta(days=2)).isoformat()
    )
    source.put(
        "/internal/admin/episodes/DEMO-ANTENATAL-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    runtime[2].multilingual_enabled = True
    runtime[2].agent_model_mode = "anthropic"
    runtime[2].anthropic_api_key = settings.anthropic_api_key
    with runtime[0].begin() as db:
        db.scalar(select(AgentRun).where(AgentRun.case_id == case)).mode = "anthropic"
    for reply in ("எனக்குப் புரியவில்லை.", "எனக்கு ஆங்கிலம் புரியவில்லை."):
        event(runtime[1], case, "demo_reply", reply).raise_for_status()
        drain(runtime, tools=tools, model=AnthropicModel(settings))
        result = view(runtime[1], case)
        assert result["run"]["status"] == "waiting", result["run"]
        assert result["handoff"] is None
        message = result["patient_simulator"]["messages"][-1]
        assert "missed appointment" in message["original_body"]
        assert "Would you like help booking another appointment?" in message["original_body"]
        assert "I'll respond" not in message["original_body"]
        assert message["translation"] == {"language": "ta", "status": "pending"}
    assert source_count(engine) == 0


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PREPARATION") != "1", reason="Explicit paid live-model opt-in required"
)
def test_live_missed_visit_evening_search(simulated_runtime):
    from datetime import UTC, datetime, timedelta

    from test_simulator import new_slot

    runtime, tools, source, engine = simulated_runtime
    body = episode_body(source, "DEMO-ANTENATAL-VISIT-01")
    body.update(
        source_status="no_show", scheduled_at=(datetime.now(UTC) - timedelta(days=2)).isoformat()
    )
    source.put(
        "/internal/admin/episodes/DEMO-ANTENATAL-VISIT-01", headers=ADMIN, json=body
    ).raise_for_status()
    date = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    slots = []
    for hour in (2, 9):
        response = source.post(
            "/internal/admin/slots",
            headers=ADMIN,
            json=new_slot(
                specialty="antenatal",
                starts_at=f"{date}T{hour:02d}:00:00+00:00",
                ends_at=f"{date}T{hour:02d}:30:00+00:00",
            ),
        )
        response.raise_for_status()
        slots.append(response.json()["id"])
    case, _ = start(runtime, "antenatal")
    drain(runtime, tools=tools)
    event(runtime[1], case, "demo_reply", "நான் மாலை நேர சந்திப்பை விரும்புகிறேன்.").raise_for_status()
    settings = runtime[2].model_copy(
        update={
            "anthropic_api_key": SecretStr(os.environ["ANTHROPIC_API_KEY"]),
            "anthropic_model": os.environ["ANTHROPIC_MODEL"],
        }
    )
    enable_live_translation(runtime, case, settings)
    drain(runtime, tools=tools, model=AnthropicModel(settings))
    result = view(runtime[1], case)
    assert result["run"]["status"] == "waiting", result["run"]
    assert not result["handoff"]
    offer = result["patient_simulator"]["messages"][-1]
    assert offer["kind"] == "options"
    assert [slot["id"] for slot in offer["evidence"]["slots"]] == [slots[1]]
    assert "unchanged" not in offer["original_body"]
    assert "not been changed" not in offer["original_body"]
    assert all(r["key"] == "preferred_language" for r in result["preferences"].get("records", []))
    assert source_count(engine) == 0


def enable_live_translation(runtime, case, settings):
    from sqlalchemy import select

    from forget_lah.runtime.models import AgentRun

    runtime[2].multilingual_enabled = True
    runtime[2].agent_model_mode = "anthropic"
    runtime[2].anthropic_api_key = settings.anthropic_api_key
    with runtime[0].begin() as db:
        db.scalar(select(AgentRun).where(AgentRun.case_id == case)).mode = "anthropic"
