"""Explicit test-phone transport. Not yet connected to patient case dispatch."""

import re
from dataclasses import dataclass

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WhatsAppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    twilio_account_sid: str = Field(pattern=r"^AC[0-9a-fA-F]{32}$")
    twilio_auth_token: SecretStr = Field(min_length=1)
    twilio_whatsapp_from: str = Field(pattern=r"^whatsapp:\+[1-9][0-9]{7,14}$")
    twilio_whatsapp_test_to: str = Field(pattern=r"^whatsapp:\+[1-9][0-9]{7,14}$")


class WhatsAppError(Exception):
    """Safe diagnostics: never include credentials, body, phone numbers or provider prose."""

    def __init__(self, code, *, delivery_uncertain=False):
        super().__init__(code)
        self.code = code
        self.delivery_uncertain = delivery_uncertain


@dataclass(frozen=True)
class MessageReceipt:
    sid: str
    status: str
    error_code: int | None


class WhatsAppClient:
    def __init__(self, settings: WhatsAppSettings, *, transport=None, allowed_recipients=None):
        self.settings, self.transport = settings, transport
        self.allowed_recipients = frozenset(
            allowed_recipients
            if allowed_recipients is not None
            else [settings.twilio_whatsapp_test_to]
        )

    def _request(self, method, resource, *, data=None):
        sid = self.settings.twilio_account_sid
        try:
            with httpx.Client(
                auth=(sid, self.settings.twilio_auth_token.get_secret_value()),
                timeout=20,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = client.request(
                    method,
                    f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
                    + (f"/{resource}" if resource else ".json"),
                    data=data,
                )
        except httpx.HTTPError:
            # Never automatically resend: a timed-out POST may have been accepted.
            raise WhatsAppError(
                "TWILIO_CONNECTION_FAILED", delivery_uncertain=method == "POST"
            ) from None
        try:
            value = response.json()
        except ValueError:
            raise WhatsAppError(
                "TWILIO_INVALID_RESPONSE", delivery_uncertain=method == "POST"
            ) from None
        if not isinstance(value, dict):
            raise WhatsAppError("TWILIO_INVALID_RESPONSE", delivery_uncertain=method == "POST")
        if not response.is_success:
            code = value.get("code")
            reason = (
                "TWILIO_TEMPLATE_REQUIRED"
                if code == 21654
                else f"TWILIO_HTTP_{response.status_code}"
            )
            raise WhatsAppError(
                reason, delivery_uncertain=method == "POST" and response.status_code >= 500
            )
        return value

    def check_account(self):
        # Only return non-secret account state, not the full account resource.
        value = self._request("GET", "")
        return {"type": value.get("type"), "status": value.get("status")}

    @staticmethod
    def _receipt(value):
        if not re.fullmatch(r"SM[0-9a-fA-F]{32}", str(value.get("sid", ""))):
            raise WhatsAppError("TWILIO_INVALID_RECEIPT", delivery_uncertain=True)
        status = value.get("status")
        if status not in {
            "accepted",
            "scheduled",
            "queued",
            "sending",
            "sent",
            "delivered",
            "read",
            "failed",
            "undelivered",
            "canceled",
        }:
            raise WhatsAppError("TWILIO_INVALID_STATUS", delivery_uncertain=True)
        error = value.get("error_code")
        return MessageReceipt(value["sid"], status, error if isinstance(error, int) else None)

    def send_text(self, recipient, body):
        if recipient not in self.allowed_recipients:
            raise WhatsAppError("TEST_RECIPIENT_NOT_ALLOWED")
        if not isinstance(body, str) or not body.strip() or len(body) > 1600:
            raise WhatsAppError("MESSAGE_BODY_INVALID")
        value = self._request(
            "POST",
            "Messages.json",
            data={
                "From": self.settings.twilio_whatsapp_from,
                "To": recipient,
                "Body": body,
            },
        )
        return self._receipt(value)

    def message_status(self, sid):
        if not re.fullmatch(r"SM[0-9a-fA-F]{32}", sid):
            raise WhatsAppError("MESSAGE_SID_INVALID")
        return self._receipt(self._request("GET", f"Messages/{sid}.json"))
