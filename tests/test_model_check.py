import json

from forget_lah.db import utcnow
from forget_lah.runtime.check_model import check_model
from forget_lah.runtime.models import ModelBudget
from forget_lah.runtime.provider import ModelError, ModelReply
from forget_lah.settings import Settings


def test_connection_check_reserves_one_call_and_validates_proposal(store):
    factory = store[1]
    config = Settings(
        agent_model_mode="anthropic", anthropic_api_key="test-only", agent_daily_call_limit=1
    )
    calls = []

    class Model:
        def decide(self, observation):
            calls.append(observation)
            return ModelReply(
                json.dumps(
                    {
                        "request_id": observation["request_id"],
                        "expected_case_version": 1,
                        "step_type": "TOOL",
                        "reason_code": "READ_SOURCE",
                        "tool_name": "read_followup_context",
                    }
                ),
                80,
                7,
            )

    result = check_model(config, factory, Model())
    assert result["ok"] and result["code"] == "MODEL_CONNECTION_VERIFIED"
    assert result["input_tokens"] == 80
    assert check_model(config, factory, Model())["code"] == "DAILY_MODEL_BUDGET_EXHAUSTED"
    assert len(calls) == 1 and "patient_id" not in calls[0]
    with factory() as db:
        budget = db.get(ModelBudget, "organiser")
        assert budget.calls == 1 and budget.day == utcnow().date().isoformat()


def test_connection_check_no_mock_fallback_and_no_retry(store):
    class Unavailable:
        def decide(self, observation):
            raise ModelError("MODEL_ACCESS_DENIED")

    config = Settings(agent_model_mode="anthropic", anthropic_api_key="test-only")
    assert check_model(config, store[1], Unavailable()) == {
        "ok": False,
        "code": "MODEL_ACCESS_DENIED",
    }
    assert check_model(Settings(), store[1])["code"] == "SIMULATION_SELECTED"
    assert (
        check_model(Settings(agent_model_mode="anthropic"), store[1])["code"]
        == "MODEL_NOT_CONFIGURED"
    )


def test_connection_check_rejects_wrong_request_binding(store):
    class Model:
        def decide(self, observation):
            return ModelReply(
                json.dumps(
                    {
                        "request_id": "00000000-0000-0000-0000-000000000000",
                        "expected_case_version": 1,
                        "step_type": "TOOL",
                        "reason_code": "READ_SOURCE",
                        "tool_name": "read_followup_context",
                    }
                )
            )

    config = Settings(agent_model_mode="anthropic", anthropic_api_key="test-only")
    assert check_model(config, store[1], Model())["code"] == "MODEL_SCHEMA_INVALID"
