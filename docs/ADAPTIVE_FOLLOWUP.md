# Adaptive follow-up and preference memory

**Current feature reference:** [Feature guide and patient memory](FEATURE_GUIDE.md) documents implemented behavior, all demo capabilities, preference tests and remaining limitations. Migration `0006` extends time preferences to attributed patient concerns; this supersedes earlier time-only descriptions.

This increment is for the local synthetic patient simulator. Three agents remain: Coordinator, Engagement and Preparation. Live mode uses Claude; offline mode uses explicit test fixtures, not natural-language intelligence. No patient is contacted and no model is trained.

## Try the new flows

Open the clinic simulator and give Alex two future slots: one at 10 am and another at 4 pm Singapore time. Open Alex's review and start a fresh simulator test when the previous review is finished or waiting. Wait for the reminder. Use live Claude for the natural-language examples.

1. Reply: **“Morning is difficult. My daughter can only accompany me after 3 pm.”** The Coordinator saves a quoted constraint, delegates source checks, and offers the afternoon slot. Reply naturally to accept it. Only the source confirmation receipt proves success.
2. Try the same message with only a morning slot available. The system asks whether another day or time works, without changing the appointment or escalating merely because the requested time is unavailable. Reply with a new explicit time window to replan.
3. Try **“Yes I plan to attend, but I have not completed the scan mentioned in my instructions.”** The Coordinator records a patient-reported preparation issue. Preparation retrieves approved instructions and prerequisites. The patient sees a callback acknowledgement; staff gets an AMBER preparation task. This is not evidence that a scan is actually ordered, nor permission to skip it. Accept the task, then record a contact outcome to resolve it. No attendance write occurs on this path.
4. Try **“I don't understand the preparation instructions.”** The same scoped callback flow requests human explanation. Automatic clinical translation or simplification is not implemented.
5. To show memory, open **Preferences for future follow-ups**, enter 15:00 as the preferred start time and tick the explicit simulated-consent checkbox. Save. On a fresh review, ask for available slots without restating the time preference. Only matching slots are offered. Change the times or use **Forget preferences** to revoke their future use.

The plan panel separates source-confirmed attendance, retrieved clinic instructions, source prerequisite status and patient-reported preparation needs. “No issue recorded” never means medically ready. Existing histories are preserved; fresh tests get the new behavior.

## How the intelligence works

Claude can propose `ASSESS_BARRIERS` with exact reply quotes, a Singapore time window, weekdays (Monday=0), an unambiguous calendar date or inclusive date range, a focused timing clarification, a preparation issue, and a next action. The gateway checks role, request/case version, saved reply and quote binding. It does not certify the semantic interpretation as infallible. Current symptoms use the separate clinical-review path.

An approved decision is saved in the run checkpoint and journey. Engagement reads source slots. Application code filters actual source results; Claude cannot invent slots. A current-visit constraint overrides a stored preference. Conflicting or uncertain availability should produce a clarification. Source API checks remain mandatory before booking. A changed selection detected before writing produces a fresh offer and requires a new patient choice; a last-instant write conflict still uses the guarded failure/handoff path.

An incomplete preparation report blocks routine confirmation in this flow. Only clinic staff resolve the callback; resolving it does not certify medical readiness or create an appointment confirmation. The acknowledgement promises no callback deadline.

## What “learning” means here

Implemented: explicit, editable appointment-time preferences in `patient_preference`, keyed by clinic and patient. Consent provenance and timestamp are stored. The simulator's staff identity is not proof of real patient identity. Preferences can affect later reviews and cases for the same source patient, without retraining Claude. Manual time windows require the explicit simulator checkbox. Clearly recurring excluded times or explicit requests to remember them can also be saved from quoted simulator statements as reported operational concerns, without claiming identity or consent verification. Case-specific constraints remain in case history. Full demo reset also removes preferences; starting a fresh review preserves them.

Forgetting removes the active preference used in future decisions. Historical audit records and prior observations remain; this button is not a historical-data erasure mechanism.

Future: explicitly consented communication/language preferences; reviewed aggregate evaluation outcomes to improve prompts and routing; supervised releases after regression evaluation. Do not let the application autonomously rewrite clinical instructions, safety rules, or its own prompts. Do not claim measured clinical benefit from synthetic tests.

## Implementation and limits

- New forward migration `0005` creates the clinic-scoped preference table. Bootstrap applies it. Windows and Ubuntu launchers remain unchanged.
- Preferences require an authenticated clinic session, CSRF/Origin checks, a current case version and an idle review. A patient-row lock serializes updates across that patient's cases.
- The total step default is 40, capped at 40, to accommodate multi-turn clarification. Per-role/event and daily-call limits remain. This is bounded; indefinitely long chats are not supported.
- The current source returns a bounded slot list. A no-match response describes currently listed slots, not all possible clinic availability.
- Supported memory is time preference only. Caregiver authorisation, real messages, translation, transport/financial service lookup and autonomous learning are not implemented.
- Model mistakes remain possible. Quote binding proves traceability, not correctness. Use adversarial and varied-language evaluations before expanding this synthetic feature.

## Team tests

Windows: `./scripts/dev.ps1 test`. Ubuntu: `bash scripts/dev.sh test`. The suite covers filtering and confirmed booking, no-match clarification, preparation callback ownership/resolution, invalid evidence, preference consent/reuse/revocation and Singapore time conversion. Live Claude checks are separate from the repeatable scripted suite.


## Natural-language scheduling corrections

Claude receives the latest reply, saved visit constraints and a bounded recent patient-facing message. It interprets meaning rather than requiring a fixed reply phrase. Typed decisions distinguish positive availability, excluded times, rejection of the current offer and uncertainty. The gateway still checks reply binding and exact supporting quotes; it does not prove semantic correctness.

The application excludes rejected slots and unavailable times from subsequent suggestions. When only unavailability is known, it asks for suitable dates/times, even if the model proposes searching. A new assessed constraint set can replace earlier constraints when the patient corrects their availability. One-off constraints remain visit-specific. Clearly recurring excluded times can be saved as described below.

Try varied wording: “None of those works”, “Those times clash with work”, “Only after 3 pm please”, then a natural acceptance of a displayed option. Also try an unclear reply: clarification is the intended outcome, not a guessed booking. No system can guarantee understanding every possible message. Clinical concerns and source-confirmed booking safeguards remain separate.

Regression coverage includes exclusions, rejected-offer persistence, clarification without booking, request-size limits, and the existing booking/safety flows. Live Claude checks additionally cover six varied scheduling replies. Historical messages are retained and will not be rewritten by this update.


## Clarification before routine ambiguity handoff

The Coordinator can propose `CLARIFY` with a short administrative question bound to the current saved reply. The simulator displays it and waits without changing appointments. The next reply includes the recent question in Coordinator context. Two general clarification attempts are allowed per review; continued ambiguity may then go to staff. An early `AMBIGUOUS_REPLY` escalation proposal is converted by application policy to a generic clarification, with the original proposal and actual outcome both retained. Symptoms and genuine clinic-authority decisions retain their separate escalation paths. The gateway validates binding and bounds, not the semantic correctness of generated wording.

Previously escalated reviews are not silently reopened. Start a fresh demo to exercise the new path.


## Frustration and recurring scheduling concerns

The Coordinator can quote a patient's expressed frustration in a barrier assessment or clarification. The application verifies that quote against the saved reply, apologizes before asking another question, and preserves the acknowledgement in the journey. It does not create a permanent sentiment/personality label.

A clearly recurring unavailable time (for example, “I told you several times that 10 won't work”) can be saved for the same clinic and source patient. The UI shows **Times to avoid** and the **Reported concern** under **Preferences for future follow-ups**. Saving a replacement manual preference or **Forget preferences** updates future use; historical audit messages remain. A full demo reset clears this memory; **Start fresh test** preserves it.

Future suggestions filter saved excluded times. If an existing source appointment conflicts, the reminder acknowledges that conflict and asks about finding another time. The agent never silently moves or cancels that appointment. Ordinary one-off conflicts are not lasting restrictions. Current implementation covers specific excluded times, not arbitrary learned policies, medical facts or model retraining. All statements here come from the staff-operated synthetic simulator, not authenticated patient channels.

Month/time refinements retain known constraints across replies. General practical concerns such as heat, traffic and working hours are saved as quoted reports and clarified into patient-selected times; the app does not supply forecasts or infer work schedules. See the feature guide for current examples and scope rules.
