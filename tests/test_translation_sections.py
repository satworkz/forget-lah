import json

import httpx
import pytest
from test_translations import settings

from forget_lah.runtime.provider import ModelError
from forget_lah.translations import translate

WARNING = (
    'You mentioned: "看诊后我打算自己开车回家". '
    'The clinic advised: "Eyes will be blurry after the appointment; '
    'please bring someone to accompany you." '
    "Your plan conflicts with that instruction. "
    "Before I record your confirmation, please tell us how you will follow it.\n\n"
    "Your appointment has not been changed."
)
TRANSLATED = {
    "part_0": "您提到：“看诊后我打算自己开车回家”。",
    "part_1": "诊所指示：“看诊后视力会模糊，请安排人陪同。”您的计划与此指示冲突。",
    "part_2": "在记录您的确认前，请告诉我们您将如何遵循此指示。",
    "part_3": "您的预约没有更改。",
}


def transport_for(output, *, inspect=None):
    def respond(request):
        payload = json.loads(request.content)
        if inspect:
            inspect(payload)
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(output)}],
            },
        )

    return httpx.MockTransport(respond)


def test_mixed_language_warning_requires_all_sections_and_retains_paragraphs():
    def inspect(payload):
        sections = json.loads(payload["messages"][0]["content"])["source_sections"]
        assert set(sections) == set(TRANSLATED)
        assert set(payload["output_config"]["format"]["schema"]["required"]) == set(sections)
        assert "Eyes will be blurry" in sections["part_1"]
        assert "not been changed" in sections["part_3"]

    result = translate(
        settings(), WARNING, "zh", transport=transport_for(TRANSLATED, inspect=inspect)
    )
    assert result == " ".join(list(TRANSLATED.values())[:3]) + "\n\n" + TRANSLATED["part_3"]


@pytest.mark.parametrize("fault", ["missing", "empty", "label", "wrong_type", "single_field"])
def test_warning_cannot_pass_with_missing_or_truncated_section(fault):
    result = dict(TRANSLATED)
    if fault == "missing":
        del result["part_1"]
    elif fault == "empty":
        result["part_1"] = ""
    elif fault == "label":
        result["part_1"] = "诊所："
    elif fault == "wrong_type":
        result["part_1"] = None
    else:
        result = {"text": "您提到："}
    with pytest.raises(ModelError, match="TRANSLATION_VALIDATION_FAILED"):
        translate(settings(), WARNING, "zh", transport=transport_for(result))


def test_numbers_cannot_move_between_instruction_and_appointment_sections():
    source = (
        "Your scan is on 2026-10-05 and must be completed before your appointment. "
        "Your appointment is on 2026-10-10 and has not been changed."
    )
    output = {
        "part_0": "您的扫描日期是2026-10-10，必须在预约之前完成。",
        "part_1": "您的预约日期是2026-10-05，没有更改。",
    }
    with pytest.raises(ModelError, match="TRANSLATION_VALIDATION_FAILED"):
        translate(settings(), source, "zh", transport=transport_for(output))


def test_trailing_newline_does_not_create_empty_required_section():
    result = translate(settings(), WARNING + "\n\n", "zh", transport=transport_for(TRANSLATED))
    assert result.endswith("您的预约没有更改。\n\n")


def test_short_message_keeps_existing_contract():
    assert (
        translate(
            settings(), "You're welcome.", "zh", transport=transport_for({"text": "不客气。"})
        )
        == "不客气。"
    )
