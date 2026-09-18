# Feature guide: forget-lah

**18 September: patient-level WhatsApp continuity (migration 0009).** Connect the team test phone once using any case for the patient. New cases for the same clinic/patient automatically join the connection; messages created after enrollment are collected once, including a new appointment reminder. Other patients are excluded. Existing pre-enrollment messages are not replayed. A valid reply to a completed case starts a fresh review under the service identity, links to the prior completed run, refreshes source evidence and preserves old history. Paused/escalated cases remain under their existing controls and receive an acknowledgement instead of silently discarding the reply.

When multiple cases can match, signed WhatsApp reply context identifies the appointment. Otherwise an explicitly selected conversation focus is used; the latest successfully sent appointment message establishes that focus. If still ambiguous, the app saves the original request and asks which appointment using last-recorded date/time and a short case reference. Choosing an appointment only routes the original request; it is not booking/cancellation consent. Extra clarification text is retained. More than ten cases requires replying to the relevant original message or its reference. No model guesses appointment identity. Current clinic reads and policy still control all changes. An explicit cancellation request requires a staff handoff and acknowledgement because no source cancellation write exists.

The Sandbox still requires an active inbound messaging window; outside the conservative 23-hour sending window, reminders remain queued until the test phone sends a new message. Approved outbound templates are not implemented. [Twilio reply context](https://www.twilio.com/en-us/changelog/whatsapp-inbound-messages-will-now-include-reply-context) may be absent for replies to messages older than seven days; unresolved identity prompts clarification. Old `needs_staff` replies are not replayed automatically after upgrade. No database reset is required.


**18 September: another appointment for the same patient.** In Clinic simulator, open Alex (or any saved patient) and click **Add another appointment for this patient**, enter its date and visit-specific notes, then **Save new appointment**. Alternatively, choose **New episode** and select an existing patient. The source creates a new reference with the same patient identity, retaining previous appointments, cases and patient preferences. New notes start blank to avoid carrying obsolete visit instructions. Scheduled appointments within the next seven days are detected and start automatically; later appointments wait until eligible. Reload cases after the next worker scan. No reset is needed. The WhatsApp connection now covers this patient across appointments; see the continuity behavior above.


**18 September cloud milestone:** a separate staff workspace, developer reset controls, a restricted WhatsApp test-phone inbox/outbox and saved-language translation are implemented. Migration `0008` preserves channel delivery/replay evidence and original/translated messages. See [team cloud testing](TEAM_CLOUD_TESTING.md) for setup, operational limits and validation steps. This supersedes older statements below about all messages staying local or all non-English preferences requiring staff. Real phone round-trip verification remains separate from offline tests.

Updated 17 September 2026. Start here for the current local demonstration. Older design PDFs contain planned capabilities; this guide distinguishes implementation from plans.

## What the product does

forget-lah follows up with patients using clinic-owned appointment and preparation information. It is not an appointment-management system. The local patient conversation simulator substitutes for real messaging channels; its bookings and attendance updates affect only the synthetic clinic API. Selecting live Claude changes reasoning, not delivery to real patients.

## Implemented feature inventory

| Feature | Current behavior | Where to test |
| --- | --- | --- |
| Automatic follow-up detection | Source-defined overdue recall, upcoming visit and missed-appointment cases; worker starts the review automatically | Overview and full case journey |
| Three-agent runtime | Coordinator delegates to Engagement and Preparation; durable worker executes policy-approved proposals and resumes after replies | Agent review and decision evidence |
| Initial source read | Deterministic application step, no model call needed merely to read the initial context | Journey: application rule |
| Clinic simulator | Edit synthetic episodes, source-approved notes and prerequisites; add available slots | Clinic simulator sidebar |
| Patient conversation simulator | Displays outgoing reminders, options, acknowledgements and entered replies in order | Patient review |
| Attendance confirmation | Natural-language intent is validated, written to the source simulator and acknowledged only with a receipt | Reply that you will attend |
| Alternative slots / recall booking | Lists source slots, interprets natural-language selection, rechecks source availability/version before booking or rescheduling | Request alternatives, then select a listed time |
| Preparation instructions | Exact approved notes are sent after confirmation; missing clinical answers request a clinic callback | Ask what to bring or an unanswered test question |
| Clinical concern | Symptom evidence triggers RED review and an acknowledgement; staff accepts and resolves the clinical task | Report a current symptom in a synthetic test |
| Mixed intentions | Attendance, scheduling, preparation and unsupported questions can coexist; weather/parking limitations are acknowledged without invented answers | Combine confirmation with an unrelated question |
| Clarification | Asks an administrative question for unclear meaning, rather than immediately treating every ambiguity as a staff task | An unclear selection or conditional acceptance |
| Practical constraints | Filters slots in Singapore time; negative availability and unavailable offers can trigger a follow-up question | Explain a time that cannot work |
| Empathy | A reply-bound frustration quote produces an apology | State that repeated unsuitable suggestions are frustrating |
| Preference and concern memory | Typed, attributed records for excluded days/times, language, contact permission, arrival support | See detailed tests below |
| Staff handoffs | Named staff acceptance distinguishes an owned handoff from an unowned escalation | Accept handoff and resolve supported callback tasks |
| Case evidence | Component names, saved inputs/outputs, decisions, policy verdicts, receipts, errors and model usage | View full case journey |
| Operational safeguards | Clinic scoping, authenticated staff sessions, CSRF checks, optimistic versions, durable jobs, bounded decisions/retries and model budgets | Automated tests and journey evidence |
| Fresh review / demo reset | Fresh review retains patient memory and history; explicit full reset clears synthetic cases and memory while preserving identities/usage accounting | Review controls / enabled reset button |
| Team delivery | Windows PowerShell and Ubuntu shell scripts, Docker Compose, migrations, seeded fixtures and GitHub checks | TEAM_START_HERE.md / UBUNTU_QUICK_START.md |

## Coherent patient replies and calendar checks

The Coordinator receives the scheduled date and its calculated weekday in Singapore time from saved clinic source evidence. It distinguishes an appointment preference from an explicit request to change or confirm an appointment. A new day/time restriction that does not conflict with the scheduled visit prompts a factual clarification before searching for alternatives. An explicit request to change the appointment still proceeds to alternatives; it is not overridden merely because the existing visit fits the restriction.

For example, “I already told staff not to schedule on Saturday” when the source shows Friday 18 September produces one reply: an apology when appropriate, acknowledgement of the saved Saturday preference, the actual Friday date, and a question about keeping or changing the appointment. The preference is retained without changing the appointment or escalating the misunderstanding.

Empathy and memory acknowledgements are deferred in the durable run checkpoint until there is a useful reply. They are composed with the final question, options, acknowledgement or callback message. The saved message retains evidence of contributing decision steps. Internal agent steps do not each send a separate patient message. If processing pauses before a reply is ready, pending parts remain internal; pause/retry preserves them for that reply.

Availability has three distinct outcomes: listed matching slots, listed slots that do not match the patient's constraints (clarify availability), or no source slots (request staff help). The empty result never announces that alternatives are available. The UI labels these messages **Clinic availability update**. Existing historical messages remain unchanged; use a fresh review to retest.

## Patient preferences: how it works

1. For each new simulated patient reply, live Claude reviews the whole reply with the recent conversation and effective patient memory. This is the Coordinator's `REVIEW_NEEDS` decision, not a new fourth agent.
2. Claude proposes typed changes with exact supporting quotations, visit/future scope and an optional clarification question. Routine appointment replies produce no memory changes.
3. The gateway checks role, clinic/case/request binding and that quotations occur in the saved reply. The worker persists the allowed changes. This does not prove real patient identity or legal consent; input remains a staff-operated simulator.
4. Deterministic code applies restrictions to slot filtering and proactive reminders. A preference never proves booking consent, changes an appointment by itself or invents clinic information.
5. Later follow-ups for the same clinic/patient reload future-scoped records. This is database memory, not model training. Visit-scoped records apply to the same case only; a fresh review of that case still represents that visit.

The system is extensible through typed keys and handlers. Ordinary questions are per-turn tasks, not patient preferences. The old `other_concern` catch-all is no longer accepted for new memory updates or included in effective planning memory; historical records remain visible for audit. Storing arbitrary prose does not give the application a new capability. Model interpretation can still be wrong, so evidence and correction controls remain visible.

### Team test instructions

Use a fresh synthetic patient/review for each independent example. Ensure Claude mode is configured for natural-language testing; the offline mock model is a deterministic fixture and does not understand arbitrary conversation. Add suitable alternative slots in Clinic simulator first. Allow processing to finish before editing memory.

| Patient message | Expected behavior |
| --- | --- |
| I don't want Saturday | Save a recurring Saturday exclusion; alternatives omit Saturdays. Existing appointments remain unchanged. |
| Not Saturday for this visit only | Save visit scope; do not carry it to a different follow-up case. |
| Don't contact me in English | Save the English restriction, ask which language using the supported multilingual administrative prompt. Do not guess a language. |
| Please use Mandarin | Save language preference and request staff language assistance, with a short Chinese administrative acknowledgement. Full multilingual clinical conversations are not implemented. |
| Don't disturb me | Acknowledge stop, save persistent contact stop, stop proactive reminder generation. This does not cancel the appointment. |
| I will always be late for the appointment | Save a pending arrival-support concern and ask what timing help would work. Do not label the patient or silently move the appointment. |
| I told you several times that 10 won't work; I am frustrated | Apologize, retain the reported time restriction and avoid repeating that time in offers. |
| Saturdays are fine now | Retract the day exclusion through a reply-bound update; inspect the memory record. |

Open **Patient preferences and concerns** to see active/pending records, scope and original patient words. Remove individual preferences there. Contact stop has a separate **Resume reminders with patient agreement** confirmation; an ordinary new reply or deleting the old time-window preference does not opt the patient back in. Resuming allows later reminders; it does not immediately send one or change a booking. Create a fresh review to test the next reminder.

### Current language boundary

English is the implemented full conversation language. Chinese, Malay and Tamil have fixed administrative language acknowledgements; an English exclusion with an unknown preference uses a multilingual language question. Other preferences route to staff rather than automatically translating doctor notes. A recorded preference is not a claim that every language/channel is implemented. Previously saved messages remain visible as history.

### Data and audit trail

Migration `0006` adds `patient_memory`, separate from legacy `patient_preference` time windows. Each row records clinic, patient, case, key, typed value, scope, active/pending/superseded/retracted status, exact quote, reply ID, decision step ID, timestamp and predecessor. Corrections supersede earlier rows; removals retract them. API responses show applicable active/pending records; audit events retain changes. Data does not cross clinic/patient boundaries.

`GET /api/cases/{case_id}/agent` includes `preferences.records`. `POST /api/cases/{case_id}/preferences/{memory_id}/remove` requires staff authentication, CSRF and current case version; contact-stop removal additionally requires `resume_contact: true`. The existing preferences endpoint controls the legacy time window. No preference-removal endpoint silently changes the source appointment.

## Limits and pending work

- WhatsApp, SMS, phone calls, mobile push, calendar integration, Singpass and real patient authentication are not connected by these changes.
- Automatic no-response outreach and real callback delivery remain separate channel/scheduling work. A staff callback request is not proof a call occurred or a guaranteed callback time.
- Full multilingual clinical instruction delivery, caregiver authorization and uploaded paper-note ingestion are not implemented here.
- The organiser endpoint still needs its private contract/credential verification. Direct Anthropic and the labelled local mock remain separate modes.
- High availability, distributed deployment, production retention policies and comprehensive privacy/security review require further work. Existing worker leases and PostgreSQL tests are foundations, not a production certification.
- The case journey stores application evidence, not private model reasoning or a complete byte-for-byte archive of every HTTP request. Older records can lack fields that were added later.

## Other guides

- [Adaptive follow-up](ADAPTIVE_FOLLOWUP.md): timing and preparation walkthrough.
- [Patient simulator](PATIENT_SIMULATOR.md): synthetic confirmations and source receipts.
- [Clinic simulator](CLINIC_SIMULATOR.md): create source fixtures.
- [Case journey](CASE_JOURNEY.md): read evidence.
- [Implementation status](IMPLEMENTATION_STATUS.md): historical milestones.
- [Validation](VALIDATION.md): measured checks and limitations.


## Patient questions and independent confirmation

A reply such as “Yes I confirm, Do I need someone to accompany me?” contains two tasks. Coordinator records the appointment intent separately from exact patient questions. Engagement interprets acceptance and records it through the synthetic clinic API. Preparation reads clinic-approved notes and prerequisites and returns coverage for every question. Their execution order may vary; only Coordinator delegates.

Preparation labels each question as answered by a specific approved instruction, requiring clinic review because the source does not answer it, or unsupported by the product (for example, external traffic conditions). For an answered question, the gateway checks the instruction ID and exact quoted source text. Missing information is never interpreted as “no escort/test is needed.” This source check prevents invented quotations; the model's judgement about relevance can still be wrong.

The patient receives one composed reply containing the confirmation and the answer, limitation or clinic callback acknowledgement. An unanswered clinic question creates a `PATIENT_QUESTION_CALLBACK` staff task; independent attendance confirmation remains recorded. A question alone does not authorize attendance confirmation or a booking change. Conditional acceptance still needs clarification. Clinical symptom and contact-stop controls retain priority.

Test this in a fresh synthetic case:

1. In the mock clinic, set an approved note such as “For this visit, please arrange for an adult to accompany you home.”
2. Reply “Yes I confirm, Do I need someone to accompany me?” in the simulator.
3. Check that the source attendance is confirmed, and the reply includes the approved instruction rather than asking what the concern means.
4. Repeat with a different case whose notes do not answer the question. Check confirmation plus a callback acknowledgement, and a staff question task.
5. Check the full journey: `REVIEW_NEEDS.patient_questions`, Preparation's `RETURN.question_answers`, source evidence and the final displayed message. No question should be saved as a new `other_concern` preference.

Existing conversation messages are history and are not rewritten by this update. Up to three independent questions are supported in one decision contract. The simulator displays messages locally; it does not send real patient messages or place callback calls.


Staff question callbacks use the neutral label **Patient question**, followed by the original patient wording. The heading is not a medical-topic classification. Preparation-help callbacks retain their distinct heading. This also corrects the display of existing callback records without changing their history.
# WhatsApp integration status — 18 September

The optional test-phone adapter validates credentials and sends an explicitly requested setup message. After upgrading and joining the legacy Sandbox, one custom message was confirmed delivered to the team phone. It does not yet deliver case messages or accept patient replies. See [setup and remaining work](WHATSAPP_SETUP.md). This is an integration milestone, not a completed messaging feature.


## Singapore hosted demo (18 September)

The existing developer/testing UI now has an HTTPS Lightsail deployment with fresh synthetic records and its own staff credentials. Direct Anthropic remains the provider. This does not implement the planned redesigned staff UI, multilingual messaging or WhatsApp case channel. See [AWS deployment guide](AWS_DEMO.md).


## Decision validation and repair (18 September)

Provider schemas now describe the canonical length, numeric and collection bounds that the provider cannot enforce natively. Local validation still rejects violations; decisions are never silently truncated or executed merely because a model returned them.

A rejected decision gets one budgeted repair attempt with field-specific validation errors. Migration `0007` retains up to two failed attempts per step: structured JSON proposal, validation field/code/message, response byte count and digest. Unstructured invalid output is not retained, and rejected proposals are not put back into the model prompt. Successful repair keeps its failure evidence alongside the later validated decision.

The developer review has **Inspect rejected proposal and validation errors**. The case journey includes the same evidence under the recorded step outcome. Both use the existing authenticated case scope. Earlier failures have no retrospective proposal details.

Regression coverage includes an overlong delegation goal repaired within the existing 200-character limit, specific feedback reaching the provider, failure persistence after successful repair, and malformed non-JSON responses pausing after two attempts without storing the raw text. This fixes a reproduced Priya delegation failure after “can I come tomorrow?”; it does not invent clinic slots or authorize bookings.


Live recovery verified on the Singapore cloud demo: Priya's existing paused review was retried through the authenticated application action after migration `0007`. All subsequent decisions succeeded. The clinic returned no alternative slots, so the app displayed “Nothing has been booked. The clinic currently lists no alternative slots. I've requested help from the clinic team to find a suitable time.” and created an unowned AMBER `NO_AVAILABLE_SLOTS` task. Existing conversation and failed-step history were preserved. Validation: 291 Linux tests passed, including PostgreSQL checks; Ruff and the frontend production build passed.


### 18 September: appointment context and preparation plans
A successful sent/delivered clinic message establishes the appointment context for a normal reply. The signed inbound webhook saves that context before worker processing, so a later outgoing message cannot reroute a queued reply. Explicit WhatsApp quoted-message context takes precedence. Failed/uncertain sends and appointment-selection prompts do not establish focus; genuinely unresolved identity still asks for clarification.

Coordinator reviews preparation-related statements as well as questions (for example transport, accompaniment and food plans). These are visit tasks, not automatically saved preferences or arrival-support problems. Preparation reads approved instructions and returns an instruction ID plus an exact quote; the gateway validates the evidence. Attendance confirmation remains an independent task and the response combines it with applicable notes. No inferred driving permission, medical prohibition or invented instructions are added. Missing clinic answers still request staff review. The existing trace field `patient_questions` now also carries exact preparation-plan statements for compatibility.


**Reset and WhatsApp continuity:** Reset preserves an enabled test-phone enrollment by clinic/patient identity, rebinds it to a recreated eligible case and queues newly generated reminders through the normal deduplicated outbox. Old queued deliveries are canceled; provider SID tombstones remain. Explicitly disconnected phones stay disconnected. The existing inbound messaging window is preserved, never renewed by reset. No eligible case for that patient means no automatic reconnection.


### Preparation plans versus questions (18 September)
Coordinator now separates neutral visit plans (`preparation_plans`) from actual questions and explicit unmet needs (`patient_questions`). Exact reply quotes and intent are saved. Runtime retains a combined indexed task list plus `patient_task_types` for compatibility; no new database migration is needed. Only Coordinator delegates.

Preparation reasons about the purpose of approved notes rather than demanding matching travel words. For a neutral plan it may return `GUIDANCE` with an instruction ID and exact approved quote, or `NOT_REQUIRED` when no note applies. Both provider schema and gateway restrict these plan outcomes. Questions and explicit inability/refusal retain `ANSWERED`, `CLINIC_REVIEW`, and `UNSUPPORTED`; neutral plans cannot silently become a callback. Source evidence is still mandatory for guidance. Attendance is recorded independently from preparation review. Current symptoms retain their separate clinical escalation path.

Examples: “the clinic is nearby, I can walk” receives the approved accompaniment instruction; “my daughter will walk home with me” receives relevant guidance without inventing a problem; “I cannot find anyone to accompany me” remains a help request. Missing instructions do not create permission or a medical restriction. Answers cite approved wording rather than generating new clinical advice.

Patient reminders greet the recorded name (for example “Hello Alex,”); confirmation acknowledgements address that name too. The demo suffix is removed, titles are never inferred, and greetings enter the existing language-translation flow. Approved notes used in the answer are not repeated in a separate instruction block. Historical messages and existing handoffs are not silently rewritten.

The paid live-flow test is opt-in: `RUN_LIVE_PREPARATION=1` with Anthropic credentials runs `tests/test_live_preparation.py` against isolated synthetic source/database fixtures, without WhatsApp delivery. It checks actual Coordinator, Engagement and Preparation model decisions through confirmation and a single evidence-grounded response. Normal test runs skip it.

Ordinary WhatsApp messages no longer prepend internal case references; the greeting/content is first. Genuine routing clarifications still show appointment labels and selection references. A neutral plan cannot simultaneously be saved as an overlapping arrival-support concern; contradictory proposals must pass the existing bounded repair step before persistence.


**Explicit language requests:** A supported named-language preference resolves the language choice immediately; contradictory clarification proposals cannot ask for it again. A language-only request produces one `language_restatement` of the most recent substantive clinic message, with the original message ID recorded as evidence and the usual budgeted translation/delivery path. Previous language-only acknowledgements and routing notices are skipped. Mixed requests continue through appointment/question handling in the chosen language, rather than replaying old context. Language changes do not authorize booking or attendance writes. Unspecified language refusals still clarify; unsupported languages and contact-stop rules retain their existing handling.


### Current-reply evidence and technical pause recovery

Conversation history helps interpret short replies in any supported language, but REVIEW_NEEDS task items and evidence quotes must come from the current patient reply. Historical tasks must not be copied as new statements. Invalid current-reply task, preference or attendance quotes receive one budgeted model correction attempt with bounded validation feedback. The original proposal is retained in developer evidence; it is never silently edited into consent. The corrected proposal passes all policy checks again before any source write. Authority, stale version, role and tool denials are not retryable through this correction path. Two invalid attempts pause for technical review without claiming a clinical handoff. Incoming replies during a technical pause are saved and receive an accurate pause acknowledgement; they do not bypass the pause or authorize an appointment write. Attendance follow-up now asks one clear yes/no question instead of combining confirmation and rescheduling alternatives.

Retry identity: native model output schemas bind reply_event_id to the original saved patient reply, even when a staff retry/timer has a different event ID. Text-provider instructions carry the same distinction, and the gateway still verifies the binding. Retrying never manufactures a new patient response.

Validation and rollout: the affected runtime, memory, channel, provider, question, simulation and adaptation suites passed (one PostgreSQL-only check skipped without TEST_DATABASE_URL); final provider schema checks passed. Live Anthropic Tamil language-switch/confirmation flows passed both normally and through pause/retry, each with one source confirmation and no handoff. AWS deployment completed, and Alex's original saved Tamil confirmation was resumed through audited staff retry. Source-confirmed outcome completed and the Tamil acknowledgement was delivered over WhatsApp. No reset or fabricated patient reply was used.


### Multilingual provider request budget

The shared default HTTP request cap is now 32,000 UTF-8 bytes, including instructions, output schema, context and JSON envelope. The former 8,000-byte cap rejected a routine Tamil rescheduling request at 8,019 bytes. Settings, Compose and example configuration now agree; the AWS demo explicitly selects 32,000 bytes. Patient evidence is not truncated. Oversized requests still fail before network access; daily call budgets, output token limits, policy and source-write checks are unchanged. Both providers have multilingual and oversize regression tests. Provider booking regressions check the shipped 32,000-byte budget as the scheduling schema evolves.


## Month preferences and broader scheduling concerns

A patient can request a month or date range together with suitable times. “I prefer October and evening time” retains October and asks what evening start time suits the patient. Once clarified, only clinic-provided slots matching the Singapore-local range and time bounds are offered. A preference is not booking consent. If no matching slots exist, the app asks about alternatives rather than offering unrelated dates.

Broader concerns do not need a new phrase-specific rule. Claude can save the patient's exact practical concern and ask a focused question, for example:

| Patient concern | Useful clarification |
| --- | --- |
| I can't travel in hot sun | What times of day would make travel easier for you? |
| I prefer less traffic | What travel times usually work best for you? |
| Avoid office time | Which days and working hours should we avoid? |

The app cannot check forecasts, traffic congestion or infer someone's work schedule. Such concerns remain pending reports until actionable times are clarified. Different concerns are retained separately. They apply to the current visit unless the patient explicitly describes an ongoing preference; future-scoped concerns can inform later follow-ups. Staff can inspect the original quote, scope and status under patient preferences. This is saved context, not model training, and an explicit appointment selection is still required before a source booking update.

Structured needs and scheduling decisions have a bounded 2,048-token Anthropic response allowance for multilingual quotes and constraints; ordinary decisions retain 512 tokens and preparation answers retain 1,024. A truncated response is still rejected and cannot authorize a write.
