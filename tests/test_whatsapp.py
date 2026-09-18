from urllib.parse import parse_qs

import httpx
import pytest

from forget_lah.whatsapp import WhatsAppClient, WhatsAppError, WhatsAppSettings


def config():
    return WhatsAppSettings(
        twilio_account_sid="AC" + "1" * 32,
        twilio_auth_token="not-a-real-token",
        twilio_whatsapp_from="whatsapp:+15550000001",
        twilio_whatsapp_test_to="whatsapp:+15550000002",
    )


def test_account_check_does_not_expose_account_fields():
    def respond(request):
        assert request.url.path == "/2010-04-01/Accounts/AC" + "1" * 32 + ".json"
        return httpx.Response(
            200, json={"type": "Trial", "status": "active", "auth_token": "secret"}
        )

    client = WhatsAppClient(config(), transport=httpx.MockTransport(respond))
    assert client.check_account() == {"type": "Trial", "status": "active"}


def test_unicode_message_and_queued_not_delivered():
    def respond(request):
        params = parse_qs(request.content.decode())
        assert params["Body"] == ["您好 / வணக்கம் / Selamat pagi"]
        assert params["To"] == [config().twilio_whatsapp_test_to]
        return httpx.Response(
            201, json={"sid": "SM" + "2" * 32, "status": "queued", "error_code": None}
        )

    client = WhatsAppClient(config(), transport=httpx.MockTransport(respond))
    assert (
        client.send_text(config().twilio_whatsapp_test_to, "您好 / வணக்கம் / Selamat pagi").status
        == "queued"
    )


def test_trial_template_restriction_is_not_silently_replaced():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(400, json={"code": 21654, "message": "private provider details"})

    client = WhatsAppClient(config(), transport=httpx.MockTransport(respond))
    with pytest.raises(WhatsAppError, match="^TWILIO_TEMPLATE_REQUIRED$"):
        client.send_text(config().twilio_whatsapp_test_to, "Test")
    assert len(calls) == 1


def test_unknown_recipient_never_leaves_application():
    def respond(request):
        pytest.fail("Unapproved recipient reached network")

    with pytest.raises(WhatsAppError, match="TEST_RECIPIENT_NOT_ALLOWED"):
        WhatsAppClient(config(), transport=httpx.MockTransport(respond)).send_text(
            "whatsapp:+15550000003", "Test"
        )


def test_timeout_not_retried_and_marked_uncertain():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("private details")

    with pytest.raises(WhatsAppError, match="^TWILIO_CONNECTION_FAILED$") as exc:
        WhatsAppClient(config(), transport=httpx.MockTransport(respond)).send_text(
            config().twilio_whatsapp_test_to, "Test"
        )
    assert exc.value.delivery_uncertain
    assert len(calls) == 1


def test_status_receipt_includes_failed_delivery():
    sid = "SM" + "2" * 32

    def respond(request):
        assert request.method == "GET"
        assert request.url.path.endswith(f"/Messages/{sid}.json")
        return httpx.Response(200, json={"sid": sid, "status": "failed", "error_code": 63016})

    receipt = WhatsAppClient(config(), transport=httpx.MockTransport(respond)).message_status(sid)
    assert receipt.status == "failed" and receipt.error_code == 63016
