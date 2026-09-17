# Feature guide: forget-lah

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
