# WhatsApp integration: account validation milestone

**Current: simultaneous team testing is supported.** Register one phone per demo patient in **Developer testing → WhatsApp team test phones**. The section at the end gives the setup steps and supersedes older single-phone limits.


**18 September: patient-level WhatsApp continuity (migration 0009).** Connect the team test phone once using any case for the patient. New cases for the same clinic/patient automatically join the connection; messages created after enrollment are collected once, including a new appointment reminder. Other patients are excluded. Existing pre-enrollment messages are not replayed. A valid reply to a completed case starts a fresh review under the service identity, links to the prior completed run, refreshes source evidence and preserves old history. Paused/escalated cases remain under their existing controls and receive an acknowledgement instead of silently discarding the reply.

When multiple cases can match, signed WhatsApp reply context identifies the appointment. Otherwise an explicitly selected conversation focus is used; the latest successfully sent appointment message establishes that focus. If still ambiguous, the app saves the original request and asks which appointment using last-recorded date/time and a short case reference. Choosing an appointment only routes the original request; it is not booking/cancellation consent. Extra clarification text is retained. More than ten cases requires replying to the relevant original message or its reference. No model guesses appointment identity. Current clinic reads and policy still control all changes. An explicit cancellation request requires a staff handoff and acknowledgement because no source cancellation write exists.

The Sandbox still requires an active inbound messaging window; outside the conservative 23-hour sending window, reminders remain queued until the test phone sends a new message. Approved outbound templates are not implemented. [Twilio reply context](https://www.twilio.com/en-us/changelog/whatsapp-inbound-messages-will-now-include-reply-context) may be absent for replies to messages older than seven days; unresolved identity prompts clarification. Old `needs_staff` replies are not replayed automatically after upgrade. No database reset is required.


18 September 2026. The signed patient-level test-phone channel is implemented. The user confirmed Alex's real phone round trip, and the later new-appointment reminder has a delivered provider receipt. Follow [team cloud testing](TEAM_CLOUD_TESTING.md) for the webhook URL, Alex binding, delivery states and reset behavior.

## Verified so far

- The account is now upgraded and active, with an approved primary profile.
- After joining the legacy WhatsApp Sandbox and updating its sender, one custom setup message to the configured team phone was confirmed **delivered** by Twilio. No case message was sent.
- The earlier new-console trial attempt returned `21654: ContentSid Required` with no message SID; this is historical, not the current blocker.
- Six offline adapter tests pass: account metadata, Unicode content, trial restriction, recipient allowlist, uncertain send without retry, and failed-delivery status.

When explicitly enabled and bound, new case messages are dispatched to the configured test phone. Signed incoming requests are persisted and deduplicated before resolving the appointment and resuming or reopening its synthetic case. The adapter alone does not add multilingual support; the separate budgeted translation stage does.

## Credentials

Keep these only in the untracked project `.env`:

```dotenv
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+sender_number_shown_by_Twilio
TWILIO_WHATSAPP_TEST_TO=whatsapp:+your_verified_test_phone
```

Use the displayed sender for the selected account/testing environment. Changing a `From` number alone does not enroll the account in another Sandbox. Never commit real values or post the token in chat.

## Safe diagnostic commands

From the repository directory, with the development environment installed:

```text
uv run python scripts/check_whatsapp.py
```

This checks authentication only and sends nothing. It prints account type/status without secrets.

After the sender supports custom replies and the test phone is enrolled, an explicit single-message test is available:

```text
uv run python scripts/check_whatsapp.py --send-test
uv run python scripts/check_whatsapp.py --status SM_message_id_from_previous_command
```

`--send-test` sends one fixed setup message to the allowlisted phone each time it is run. It does not enqueue agent work. A queued receipt is not proof of delivery. If a timeout makes the outcome uncertain, inspect Twilio logs before repeating; the adapter never retries automatically. Do not repeatedly test the known template restriction.

## Sandbox setup reference

Try the [legacy Sandbox console](https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn). If it is available, activate and join that specific Sandbox and use its sender. Access is not guaranteed for a new-console account. Otherwise, establish the paid-account sender onboarding requirements before upgrading; payment alone must not be assumed to produce a ready WhatsApp sender.

References: [new-console WhatsApp trial restrictions](https://www.twilio.com/docs/usage/trials/try-out-whatsapp), [legacy Sandbox](https://www.twilio.com/docs/whatsapp/sandbox).

Complete a phone reply-to-case round trip before declaring the integration ready. The Singapore HTTPS deployment is documented in [AWS demo](AWS_DEMO.md). Current setup and limitations are in [team cloud testing](TEAM_CLOUD_TESTING.md).


### 18 September: appointment context and preparation plans
A successful sent/delivered clinic message establishes the appointment context for a normal reply. The signed inbound webhook saves that context before worker processing, so a later outgoing message cannot reroute a queued reply. Explicit WhatsApp quoted-message context takes precedence. Failed/uncertain sends and appointment-selection prompts do not establish focus; genuinely unresolved identity still asks for clarification.

Coordinator reviews preparation-related statements as well as questions (for example transport, accompaniment and food plans). These are visit tasks, not automatically saved preferences or arrival-support problems. Preparation reads approved instructions and returns an instruction ID plus an exact quote; the gateway validates the evidence. Attendance confirmation remains an independent task and the response combines it with applicable notes. No inferred driving permission, medical prohibition or invented instructions are added. Missing clinic answers still request staff review. The existing trace field `patient_questions` now also carries exact preparation-plan statements for compatibility.


**Reset and WhatsApp continuity:** Reset preserves an enabled test-phone enrollment by clinic/patient identity, rebinds it to a recreated eligible case and queues newly generated reminders through the normal deduplicated outbox. Old queued deliveries are canceled; provider SID tombstones remain. Explicitly disconnected phones stay disconnected. The existing inbound messaging window is preserved, never renewed by reset. No eligible case for that patient means no automatic reconnection.

**Reconnect window fix:** Re-enrolling the same configured phone preserves its verified inbound timestamp, including an expired timestamp; connecting a different recipient clears it. Reset preserves that timestamp too. The 20 channel tests pass. For the affected demo, the missing timestamp was recovered from an authenticated Twilio inbound record for the configured sender/recipient, without replaying the patient message or resetting data.


## Simultaneous team WhatsApp testing (19 September)

Multiple team phones can now be registered from **Developer testing → WhatsApp team test phones**. Each phone must represent a different synthetic patient; multiple appointments for that same patient stay under their phone. The existing configured phone is preserved. Additional numbers are stored in the database and do not require environment edits or redeployment.

1. Each teammate joins the same Twilio Sandbox using the displayed `join ...` phrase.
2. Enter their international WhatsApp number (for example `+6591234567`) and select their demo patient. Click **Connect test phone**.
3. After connecting, the teammate sends a message to the Sandbox to open their own reply window. New messages then use that phone. Pre-enrollment reminders are not replayed; a fresh review can generate a new reminder.
4. Check the registered-phone card for connection and reply-window status. Disconnect affects only that phone. To assign it to another patient, disconnect first and register the number with the other patient.

Phone enrollment is an explicit staff action protected by clinic access, Origin and CSRF checks. Incoming messages still require a valid Twilio signature, the configured account/sender, and an enabled registered number. Unknown numbers cannot enter case processing. The transport send allowlist is built from active registrations. Each registration has isolated conversation focus, incoming binding evidence, and inbound-window timestamps. Delivery is paced across the shared Sandbox sender; one closed window does not block the other phones.

Reset preserves all active same-patient registrations and their original window expiry, but clears all demo histories/preferences for everyone. Coordinate resets with teammates. Sandbox membership and the service reply window remain separate: rejoin when membership expires and send a new inbound message when the reply window expires. This adds test-phone enrollment, not production patient identity verification.

Migration `0010` uniquely identifies a recipient within a clinic while retaining the original binding. No demo data reset is required.
