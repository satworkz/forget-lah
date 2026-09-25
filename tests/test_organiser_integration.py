import json

import httpx
import pytest

from forget_lah.bridge import _anthropic_json
from forget_lah.runtime.provider import ModelError, organiser_json
from forget_lah.settings import Settings
from forget_lah.translations import translate


def settings():
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        agent_model_mode="organiser",
        llm_gateway_url="https://gateway.example",
        llm_gateway_api_key="organiser-test-key",
        anthropic_api_key=None,
    )


def test_translation_uses_organiser_without_anthropic_key():
    def respond(request):
        assert str(request.url) == "https://gateway.example/api/chat"
        assert request.headers["X-API-Key"] == "organiser-test-key"
        payload = json.loads(request.content)
        assert payload["stream"] is False
        assert "source_message" in payload["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"text": "Janji temu pada 25, 10:00."}),
                },
            },
        )

    assert (
        translate(
            settings(), "Appointment on 25, 10:00.", "ms", transport=httpx.MockTransport(respond)
        )
        == "Janji temu pada 25, 10:00."
    )


@pytest.mark.parametrize("response", ['{"text":"x","text":"y"}', "[]", "not JSON"])
def test_organiser_structured_output_rejects_invalid_json(response):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, json={"done": True, "message": {"role": "assistant", "content": response}}
        )
    )
    with pytest.raises(ModelError, match="MODEL_SCHEMA_INVALID"):
        organiser_json(settings(), system="test", context={}, schema={}, transport=transport)


def test_bridge_dispatches_to_organiser_with_evidence_schema(monkeypatch):
    def complete(config, **kwargs):
        assert config.anthropic_api_key is None
        assert kwargs["schema"] == {"type": "object"}
        assert kwargs["context"] == {"rows": ["synthetic"]}
        return {"ok": True}

    monkeypatch.setattr("forget_lah.runtime.provider.organiser_json", complete)
    assert _anthropic_json(
        settings(), system="mapping", context={"rows": ["synthetic"]}, schema={"type": "object"}
    ) == {"ok": True}


def test_organiser_translation_is_configured_without_direct_provider_key():
    config = settings().model_copy(update={"multilingual_enabled": True})
    assert config.translation_configured


def test_organiser_fenced_json_keeps_strict_validation():
    def respond(request):
        assert json.loads(request.content)["options"]["num_predict"] == 1024
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {"role": "assistant", "content": '```json\n{"text":"translated"}\n```'},
            },
        )

    assert organiser_json(
        settings(), system="test", context={}, schema={}, transport=httpx.MockTransport(respond)
    ) == {"text": "translated"}
