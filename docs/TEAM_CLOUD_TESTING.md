# Team cloud testing

**18 September: patient-level WhatsApp continuity (migration 0009).** Connect the team test phone once using any case for the patient. New cases for the same clinic/patient automatically join the connection; messages created after enrollment are collected once, including a new appointment reminder. Other patients are excluded. Existing pre-enrollment messages are not replayed. A valid reply to a completed case starts a fresh review under the service identity, links to the prior completed run, refreshes source evidence and preserves old history. Paused/escalated cases remain under their existing controls and receive an acknowledgement instead of silently discarding the reply.

When multiple cases can match, signed WhatsApp reply context identifies the appointment. Otherwise an explicitly selected conversation focus is used; the latest successfully sent appointment message establishes that focus. If still ambiguous, the app saves the original request and asks which appointment using last-recorded date/time and a short case reference. Choosing an appointment only routes the original request; it is not booking/cancellation consent. Extra clarification text is retained. More than ten cases requires replying to the relevant original message or its reference. No model guesses appointment identity. Current clinic reads and policy still control all changes. An explicit cancellation request requires a staff handoff and acknowledgement because no source cancellation write exists.

The Sandbox still requires an active inbound messaging window; outside the conservative 23-hour sending window, reminders remain queued until the test phone sends a new message. Approved outbound templates are not implemented. [Twilio reply context](https://www.twilio.com/en-us/changelog/whatsapp-inbound-messages-will-now-include-reply-context) may be absent for replies to messages older than seven days; unresolved identity prompts clarification. Old `needs_staff` replies are not replayed automatically after upgrade. No database reset is required.


**18 September: another appointment for the same patient.** In Clinic simulator, open Alex (or any saved patient) and click **Add another appointment for this patient**, enter its date and visit-specific notes, then **Save new appointment**. Alternatively, choose **New episode** and select an existing patient. The source creates a new reference with the same patient identity, retaining previous appointments, cases and patient preferences. New notes start blank to avoid carrying obsolete visit instructions. Scheduled appointments within the next seven days are detected and start automatically; later appointments wait until eligible. Reload cases after the next worker scan. No reset is needed. The WhatsApp connection now covers this patient across appointments; see the continuity behavior above.


## Entry points

- Staff workspace: https://forget-lah.52-220-111-31.sslip.io/
- Developer testing: https://forget-lah.52-220-111-31.sslip.io/#/developer
- Clinic simulator: https://forget-lah.52-220-111-31.sslip.io/#/clinic-simulator

Use the separate cloud staff login. Staff Overview offers searchable patient cards; Needs attention shows escalated and paused reviews. A case shows the current plan, attendance evidence, preparation, conversation and staff outcomes. Named ownership and callback/clinical resolution retain authenticated actions. Statistics counts current cases, not historical performance or clinical outcomes. The staff journey covers the current review; earlier reviews and technical evidence remain in Developer testing.

## Reset

In Developer testing choose **Reset demo data**, review the scope, type `RESET` and confirm. This clears follow-up history and preferences and recreates eligible cases from the **current** clinic simulator data. It does not restore edited dates or slots to original defaults. Staff accounts and accumulated model usage remain. Active work prevents reset; pause it first. WhatsApp enrollment is preserved for the same patient’s recreated eligible cases; old pending deliveries are canceled. Disconnected phones stay disconnected. Provider identifiers are retained as replay-prevention tombstones, with message bodies cleared. Fresh reminders use the preserved channel window, which reset does not extend. If the patient has no eligible recreated case, the phone remains disconnected. Enabling reset alone clears nothing. Coordinate resets with other testers.

## Alex and WhatsApp

The channel is restricted to the configured team phone and synthetic clinic. A signed request establishes transport provenance, not real patient identity or consent. All clinic writes remain synthetic.

1. In Twilio's legacy WhatsApp Sandbox settings, set **When a message comes in** to `https://forget-lah.52-220-111-31.sslip.io/api/channels/whatsapp/inbound`, method **POST**, and save.
2. Ensure the phone has joined this Sandbox; rejoin using Twilio's displayed phrase if membership expired.
3. In Developer testing → WhatsApp test phone, connect **Alex**, as selected by the user. Only one patient can be connected at a time; all that patient's cases are included.
4. Read Alex's reminder in the app and send a natural-language reply from the phone. Existing reminders are not resent on connection.
5. Incoming status changes from queued to processed and the case resumes. New replies appear on the phone; provider delivery status appears beside the saved message. Queued/sent is not proof of delivery.

Provider MessageSid deduplicates replies, including across reset. Replies during processing wait in the inbox. Replies after completion start a new review after appointment identity is resolved. Paused/escalated cases retain their status and receive a staff-attention acknowledgement. Media, empty messages and replies longer than 600 characters remain `needs_staff`. The developer channel panel exposes these states.

Dispatch commits an attempt before calling Twilio. Timeouts/interrupted dispatches become uncertain and are never automatically resent. Check Twilio logs before another send. Free-form dispatch requires a verified incoming message within a conservative 23-hour window. Template-initiated proactive reminders and general patient enrollment are not implemented. Provider failures and oversized messages stay visible without silent truncation.

The webhook uses Twilio's SDK signature validator, the configured HTTPS URL and all form parameters, plus account/sender/recipient checks. Staff actions retain session, clinic access, Origin and CSRF checks. See [Twilio webhook security](https://www.twilio.com/docs/usage/webhooks/webhooks-security).

## Language preferences

With `MULTILINGUAL_ENABLED=true` and direct Anthropic, save English, Chinese (`zh`, Simplified), Malay (`ms`) or Tamil (`ta`) under Patient preferences. The choice applies to new messages and future reviews for the same clinic patient. Explicit conversation-derived language preferences use attributed memory. An excluded language without a chosen alternative still needs clarification.

English requires no translation call. Other responses are translated after the evidence-based message is composed. Original text and translation remain separate; booking/source receipts are unchanged. Every translation reserves one call from the shared daily limit. The translator cannot invoke tools. Length and numeric preservation are checked; these do not establish perfect semantic accuracy. Native-language review is required before clinical deployment.

Pending/failed translations are visible in the conversation and withheld from WhatsApp, with no silent English fallback. Translation failure recovery requires developer investigation. The organiser adapter remains usable for decisions, but translation is currently direct-Anthropic only and needs separate verification before switching.

## Before code freeze

Complete the real Alex phone round trip, mixed scheduling/preparation reply, clinical callback, and representative Chinese/Malay/Tamil scenarios with native speakers. Check budget, Sandbox membership and reply window before the presentation. Keep developer evidence available for judges.

## Initial milestone validation record, 18 September

The full Linux-container regression run passed 315 tests including PostgreSQL checks. After further channel/date-validation refinements, all 14 focused channel/translation tests passed. Ruff and the frontend build passed. Automated Edge checks verified staff overview, Statistics, Alex's plain-language case view, Developer testing and Reset visibility; screenshots were visually reviewed. AWS readiness returned 200 and unsigned webhooks returned 403. All three previous cases remain; Alex's test-phone binding is enabled. No case messages were sent as part of deployment.

The user subsequently confirmed the real Alex phone round trip and completion. After the continuity update, AWS showed both Alex cases under the same patient connection and Twilio reported the new-appointment reminder delivered. Reopening is regression-tested with signed webhook requests and a protocol model double; a fresh real-phone reopening reply remains a team acceptance check.

Continuity validation: 15 focused channel tests passed. The full regression run had 325 passes and two request-size failures from extra prompt instructions; shortening and scoping those instructions resolved both. The corrected request-size scenario plus 53 provider checks passed; the second corrected size scenario plus all 15 channel checks passed. PostgreSQL migration and schema comparison were included in the regression run. Ruff, frontend build, AWS health and an Edge inspection of the patient-level connection passed. Migration 0009 was applied after an on-server database backup, without resetting cases or changing the phone binding.

Bounded live Anthropic translation checks succeeded for Chinese, Malay and Tamil after normalizing English date phrases to ISO dates. The first Chinese check was conservatively rejected by numeric validation; the corrected release preserves ISO dates and numeric values. These checks consumed the shared model budget and sent nothing to the phone. Native-language scenario review is still required. Final AWS health was 200, reset enabled, Alex bound, and the channel ledger had no incoming/outgoing case messages yet.


### 18 September: appointment context and preparation plans
A successful sent/delivered clinic message establishes the appointment context for a normal reply. The signed inbound webhook saves that context before worker processing, so a later outgoing message cannot reroute a queued reply. Explicit WhatsApp quoted-message context takes precedence. Failed/uncertain sends and appointment-selection prompts do not establish focus; genuinely unresolved identity still asks for clarification.

Coordinator reviews preparation-related statements as well as questions (for example transport, accompaniment and food plans). These are visit tasks, not automatically saved preferences or arrival-support problems. Preparation reads approved instructions and returns an instruction ID plus an exact quote; the gateway validates the evidence. Attendance confirmation remains an independent task and the response combines it with applicable notes. No inferred driving permission, medical prohibition or invented instructions are added. Missing clinic answers still request staff review. The existing trace field `patient_questions` now also carries exact preparation-plan statements for compatibility.
