"""Read-only credential check by default; --send-test explicitly sends one message."""

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from forget_lah.whatsapp import WhatsAppClient, WhatsAppError, WhatsAppSettings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send-test", action="store_true")
    parser.add_argument("--status", metavar="MESSAGE_SID")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        config = WhatsAppSettings(_env_file=Path(__file__).resolve().parents[1] / ".env")
    except ValidationError as exc:
        print("Missing or invalid settings:", ", ".join(str(e["loc"][0]) for e in exc.errors()))
        return 1
    client = WhatsAppClient(config)
    try:
        print("Account:", json.dumps(client.check_account()))
        if args.status:
            print("Message:", json.dumps(asdict(client.message_status(args.status))))
        elif args.send_test:
            receipt = client.send_text(
                config.twilio_whatsapp_test_to,
                "forget-lah connection test. This is a setup test only; no appointment has been changed.",
            )
            print("Message:", json.dumps(asdict(receipt)))
            print("Accepted is not delivered. Check the message status before retrying.")
        else:
            print(
                "Credentials verified. No message sent. This does not prove custom-message support."
            )
    except WhatsAppError as exc:
        print("Result:", exc.code)
        if exc.code == "TWILIO_TEMPLATE_REQUIRED":
            print(
                "This sender requires a predefined ContentSid template. Custom agent replies are blocked."
            )
        if exc.delivery_uncertain:
            print(
                "Delivery is uncertain. Check provider logs before retrying; no automatic resend occurred."
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
