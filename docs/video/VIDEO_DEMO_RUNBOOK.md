> **Updated 23 September:** Priya’s full reschedule is now verified after a deployed routing fix. Her fresh recording start is 30 September 10:00 SGT. Read [the current recording handoff](RECORDING_HANDOFF_2026-09-23.md) first. The report below preserves the earlier rehearsal and its limitations.

# Forget-lah hackathon video — production runbook

Prepared 23 September 2026. All times below are Singapore time (UTC+8). These are synthetic demonstrations, not clinical records or real patient care.

## Source of truth and scope

Use the AWS demo at https://forget-lah.52-220-111-31.sslip.io/ and the current repository. Repository inspected: `96cfa7a` (Add security hardening controls). `docs/AWS_DEMO.md` already had an uncommitted deployment update; this package does not overwrite it. Its 23 September entry records migration 0016 and a deployment from verified runtime images. Do not assume the commit alone uniquely identifies the deployed artifact. The live UI, current source records and saved evidence determine what can be filmed.

No product code, architecture, migrations or deployment changes are part of this package. Earlier design guides contain future scope and older limitations. Consult the current runtime and newer feature notes before using a claim.

The locked story is: dental follow-up origin → why reminders are insufficient → doctor-note intelligence → no-API clinics → Intelligent Intake → generic Forget-lah platform → staff complement and human control → security → technical architecture → future.

Messaging is an interface into durable follow-up. Keep a message on screen only long enough to read its relevant meaning, then show the plan, instruction, policy, source action or journey. Describe Forget-lah as complementing staff so they can focus on critical and complex work.

## Chosen patient cast

| Patient | Exact source and reason | Language | Final footage |
| --- | --- | --- | --- |
| Priya (demo) | Existing seeded patient, antenatal. Her saved approved note already contains the mandatory-scan prerequisite. A separate appointment was added through Clinic simulator because the old 21 September visit had no current eligible case. New episode: `SIM-12ac5378-3b74-4bee-97be-69bb2e8b7cea`; original fixture remains. | English, matching the current reminder; do not force Tamil into this take. | 2:45, within 2:30–3:00 |
| Ms Chen | Existing AWS Bridge patient from `docs/examples/bridge_demo.csv`, source row 4, visit `LEGACY-1003`. Missed 20 September at 09:00; approved instruction: “Bring the referral letter.” This makes a meaningful Chinese request for another appointment possible. | Chinese (`zh`) explicitly saved through Patient preferences. | 1:00, within 0:45–1:15 |
| Mr Calvin | Existing repository synthetic fixture `docs/examples/bridge_demo_1.csv`, source row 3. File explicitly says Malay; appointment 29 September at 14:30. Imported through the normal staff-reviewed intake controls during preparation. No WhatsApp binding. The model's inferred Myopia specialty was corrected to General because the source does not specify specialty. | Malay (`ms`) explicitly saved through Patient preferences. | 0:45, within 0:30–1:00 |

Mr Omar was initially considered, but his completed case is connected to a teammate's active WhatsApp window. Use Calvin to avoid interrupting that connection. Names do not establish a person's language: the fixture language and saved preference are the basis for this cast.

## Before recording

The three selected patients have been left in fresh waiting reviews with one opening reminder each. Chinese and Malay reminders are translated and ready; historical rehearsals remain in the full case journey. **Do not start another fresh review before the first recording.** Priya is staged for recording, but her successful booking ending remains blocked as described below.

1. Read `VERIFICATION_AND_ASSETS.md` for the actual final states and unresolved limits. Dates and slot availability are perishable; check them again if recording on a later day.
2. Sign into AWS using the existing private cloud staff credentials. Keep login, password managers, terminals and the Developer testing phone-registration section out of the capture.
3. Record only synthetic cases. Keep the app's synthetic/simulated labels visible. “Direct Claude API mode” identifies live reasoning; it does not turn simulator input into an authenticated patient channel.
4. Use separate clips. In OBS use a 1920×1080 canvas/output at 30 fps if available, fit the browser without clipping, and check readability. Record without narration. Save a crash-resilient recording and export/remux to MP4 for editing. These are suggested production settings, not claims about captured JPEG dimensions.
5. Pause 2–3 seconds before each action and after each important result. Stop after the designated evidence shot. Model processing may take substantially longer than final screen time; edit out the wait, never fabricate a result.
6. Use Developer testing → **Open agent review → for [patient]** for literal patient input. Use Staff workspace → Overview → patient for the main product view. The developer UI labels the reply **Staff demo input · not an authenticated patient message**; submit with **Submit demo reply**.
7. Do not click global **Reset demo data**. It clears everyone's demo history/preferences and may queue reminders through preserved phone connections. A case's **Start fresh simulator test** (API source) or **Start fresh conversation test** (Bridge) preserves older reviews, but starts a new live review and may consume model calls. Use only the selected, unconnected demonstration cases.

## DEMO-01 — Priya, doctor-note intelligence (2:45)

Purpose: show free text becoming an operational requirement, its answer becoming bound evidence, and an explicit selection becoming a source-verified change.

**Recording gate: the final rescheduling action is currently unstable.** The live rehearsal verified the source note, PATIENT_CHECK, affirmative answer, MET and slot offer. The explicit option-selection message below produced another offer instead of a booking. The appointment stayed 25 September at 10:00. Do not present the desired last two rows as verified success. For the current build, stop the usable hero footage after the offer and show the retained evidence; the full requested successful ending remains blocked. No product fix or repeated selection replay was performed.

Exact approved source note, copied from Priya's existing synthetic appointment:

> Demo clinic note: bring your maternity appointment booklet if you have one. Also  confirm with patient that she has done the mandatory scan before this appointment, if not reschedule.

This note has **no absolute date deadline**. Do not narrate “before October” or reject October merely because an older Priya experiment did so. The simulator's separate prerequisite field is “No prerequisite to check”; the demonstrated PATIENT_CHECK is derived from the approved free-text note, not that coarse source flag.

| Final time | Action / literal input | Required visible result and pause |
| --- | --- | --- |
| 0:00–0:20 | Clinic simulator → Open a saved episode → Priya's episode ending `2e8b7cea`. Show the saved note and synthetic approval checkbox without editing. | Hold the scan sentence 3 seconds. Cut to the same patient's staff case and Current plan. |
| 0:20–0:40 | Developer testing → Priya → Open agent review. Enter **I need to reschedule my appointment. What other times are available?** → Submit demo reply. | Briefly show the request, then Plan and visit readiness. The appointment must remain unchanged. |
| 0:40–1:05 | Wait for the prerequisite question; do not send a second reply while running. Open Decision and tool evidence → the Preparation RETURN → **Inspect validated decision and gateway verdict**. | Rehearsal wording: “Have you completed the mandatory scan? No appointment changes will be made until this is resolved.” Show source quote, PATIENT_CHECK, and allowed unmet action RESCHEDULE. Hold 3 seconds. |
| 1:05–1:25 | Enter **Yes, I have completed the mandatory scan.** → Submit demo reply. | Show `INTERPRET_INSTRUCTION_CHECK`, source-bound answer and `MET` in the validated decision. The answer is evidence of the fictional patient's report, not a medical certification. |
| 1:25–1:50 | Let the original rescheduling request continue. No extra “slots please” message is required if the offer arrives. | Show actual current alternatives and the unchanged existing appointment. The rehearsal offered 30 September, 3 October and 6 November; after a booking those exact options may change. Only select from the newest offer. |
| 1:50–2:10 | BLOCKED ending: the rehearsal entered **Option 1 works for me. Please reschedule my appointment to that time.** once. Do not replay merely for footage. | Actual result: another identical offer; no `INTERPRET_SELECTION` or booking receipt in this selection turn. Capture only as a failure report, not a successful reschedule. |
| 2:10–2:45 | Current-build fallback: show source note, typed check, MET evidence and durable waiting state. Stop after 3 seconds on evidence. | Narrate that prerequisite handling and alternatives were demonstrated. A successful reschedule/acknowledgement ending requires a separately verified future take; it is not available from this rehearsal. |

Narration: “A doctor-defined prerequisite becomes a structured check. The patient's answer is saved against the instruction. The model interprets meaning; policy, evidence and authorized source tools control what happens next.”

Do not substitute “no” for the rehearsed affirmative answer mid-take. The note permits an unmet-condition rescheduling branch, but that is a different scenario and must be checked separately before claiming it was demonstrated.

## DEMO-02 — Ms Chen, meaningful Chinese continuation (1:00)

Starting source: missed appointment, existing Bridge record, clinic note “Bring the referral letter.” Staff supplied an episode-scoped option: **28 September 2026, 14:00–14:30, Demo clinic team**. Adding this option did not move the appointment or send a message.

| Final time | Exact action / input | Required result / cut |
| --- | --- | --- |
| 0:00–0:08 | Staff workspace → Ms Chen → Patient preferences and concerns. Show **中文 · Chinese**, then the missed-appointment state. | Hold 2 seconds; this is a saved preference, not inferred from her name. |
| 0:08–0:20 | Developer testing → Ms Chen → input **我错过了上次的预约，想重新安排。请问有哪些可选的时间？** | Subtitle: “I missed my previous appointment and would like to arrange another time. What options are available?” Submit once. |
| 0:20–0:35 | Show the Chinese offer briefly, then Plan and visit readiness and source option. | Verified output included **选项1：2026-09-28 02:00 PM SGT — Demo clinic team**. It explicitly said no time was booked. Hold 3 seconds. |
| 0:35–0:50 | Open the Preparation/source evidence for “Bring the referral letter” and the allowed option. | Show that the same instruction/evidence checks apply to this language. Do not claim the patient received the instruction unless it appears in the actual outbound message. |
| 0:50–1:00 | Return to staff Current plan / Case journey; show that the workflow is waiting for the patient's selection. | Stop. This shorter demo proves meaningful Chinese scheduling continuation without needing another full booking sequence. |

Optional extended ending, only if another booking is desired: **我选择第一个时间，请帮我安排。** (“I choose the first time; please arrange it.”) Expect a Bridge-owned booking receipt, a Chinese acknowledgement and a state change. This ending is separate from the required one-minute take; see verification notes for whether it was exercised.

Narration: “The language changes; the workflow, source checks and evidence remain the same. For this clinic, Forget-lah manages the approved imported follow-up record.”

## DEMO-03 — Mr Calvin, short Malay workflow (0:45)

Use Mr Calvin, not Mr Omar. Current source appointment: **29 September 2026, 14:30**. Exact source instruction: “Bring your existing spectacles. Avoid screen use for 3 hours before the appointment.” The saved runtime language must show **Bahasa Melayu · Malay**. Intake's language field alone was not sufficient in the observed starting state; staff explicitly saved the preference.

| Final time | Exact action / input | Required result / cut |
| --- | --- | --- |
| 0:00–0:08 | Show Calvin's name, appointment and saved Malay preference. | Hold 2 seconds. |
| 0:08–0:18 | Developer testing → Mr Calvin → input **Ya, saya akan hadir. Apa yang perlu saya bawa?** → Submit demo reply. | Subtitle: “Yes, I will attend. What should I bring?” This combines attendance and preparation. |
| 0:18–0:30 | Briefly show the actual Malay acknowledgement/instruction. | Verified response included the appointment time and **Bawa cermin mata sedia ada anda** (bring your existing spectacles). It did not include the screen-use sentence. Do not claim the full source note was delivered. Translation may vary. |
| 0:30–0:45 | Staff Current plan → attendance evidence / Case journey; open preference again. | Show confirmation recorded in Forget-lah and preserved Malay preference. Completion requires the actual receipt and acknowledgement. Stop after 3 seconds. |

Narration: “A short Malay reply continues the same structured follow-up, with the patient's language preference preserved for future reviews.”

If the system asks an unanticipated clarification, pauses, or fails translation: stop the take and retain the actual state. Do not translate an English bubble in editing and present it as product-generated output.

## Supporting clip — Intelligent Intake (2:10)

Use the existing repository fixture **bridge_demo_1.csv**: headers `Who / Contact`, `Next thing`, `Free text`, `Language`, `Visit ID`. It combines name/contact, embeds “missed” in a date field and puts “use mobile number” in Visit ID. This is a synthetic export. Source phone strings are fixture values; crop full contacts unless the raw-row comparison needs them.

The preparation run actually produced 95% overall understanding, two READY rows and Calvin in REVIEW (90% row confidence, “Specialty inferred from spectacles context”). These are observed values, not guaranteed outputs on another analysis.

1. **0:00–0:15:** Show the CSV's unusual headers and a small synthetic sample, then Staff workspace → **Intelligent intake** → **Clinic export**. The build supports CSV, TSV and XLSX; this recorded example verifies CSV, not an XLSX upload.
2. **0:15–0:40:** Select the fixture → **Understand this file →**. Cut waiting time. Show **What Forget-lah understood**, especially one source column mapping to name and phone, and the mixed status/date interpretation.
3. **0:40–1:00:** Show **Follow-up preview**, READY versus REVIEW, Calvin's warning and masked phone summary. High confidence does not bypass review.
4. **1:00–1:35:** Calvin → **Review & edit**. Show **Original uploaded row** beside normalized fields. Change **Specialty** from Myopia to General because the source does not identify a specialty. Enter review note: **Synthetic video demo: source does not specify specialty. Use General instead of inferring Myopia from spectacles.** Keep the source-bound doctor note unchanged. Click **Save reviewed row**.
5. **1:35–1:50:** Hold **Row 3 reviewed and ready to import**, READY and Staff reviewed for 3 seconds. This action is staff review; do not attribute the correction to an autonomous agent.
6. **1:50–2:10:** **Approve 3 ready records →**. Show import result and Overview → Mr Calvin. Explain that approval creates owned records; only eligible records create immediate cases. Stop on his structured follow-up view.

This batch was already corrected and imported during verification. Use the supplied before/after screenshots as factual cutaways. For a new continuous recording, analyze the same synthetic fixture in a new preview, but understand that approving it again may skip duplicates rather than create three new cases. Do not reset the shared clinic or promise a REVIEW result from another model run. If a fresh continuous intake-to-new-case take is essential, first agree on a separate synthetic fixture/recording workspace through the documented controls.

## Supporting clip — staff appointment change and notification (1:00–1:20)

Use the separate **Alex (demo)** case `9510ac36-744a-4c44-ba79-c6dc584996aa`, source episode ending `d37e5d`. It was created through **Add another appointment for this patient**, preserving older Alex appointments, with his existing approved source instruction “Demo clinic note: bring your existing spectacles if you have them.” Its WhatsApp connection is disabled. Ms Ilham was unsuitable for this panel because the source appointment is in the past; the actual UI blocks it with “Only a current future appointment can be changed here.”

**Ready-to-record version, no additional mutation needed:** Overview → Alex → **Change appointment** → frame **Appointment updated**, the 25 September 10:00 → 29 September 10:00 receipt, staff actor and notification status. Hold 3 seconds. Close/collapse the panel or scroll to **Case journey** and show the saved message asking for confirmation. Open **Security & Audit**, expand the **staff appointment change** evidence, and show `STAFF_CHANGED_AWAITING_PATIENT`, source `clinic_api`, and committed result. Stop. Use screenshot 06/07 as cutaways if needed.

The exact verification actions already performed were:

1. **Change appointment** → **Review doctor instructions**; wait for source-bound review. No unanswered prerequisite existed. If another patient's checks block the panel, stop: it cannot initiate unanswered checks (GAP-STAFF-CHANGE-001).
2. **Available appointment** → **29 Sept 2026, 10:00 am SGT · Demo doctor**. Internal reason: **Synthetic video demo: clinic staff arranged an alternative follow-up.** This reason is audit-only.
3. **Confirm change and notify patient**. Verified **Appointment updated** and **Saved in demo conversation; no phone delivery receipt**. Do not label this DELIVERED or imply a real phone message.
4. Verify the actual source receipt and outbound message: “Your appointment has been changed by the clinic to 29 September 2026 at 10:00 AM SGT. Please confirm if this works for you.” The new review is waiting; no patient acceptance was fabricated.

For a future continuous click-through take, review instructions again and choose a currently displayed alternative. The previous 29 September option has been consumed; do not reuse the old selection. That would be a new synthetic appointment change, not playback of this recorded event.

Notification failure does not undo a committed appointment change. If shown, use the actual pending/failed status and do not click the change button a second time to retry a notification.

## Supporting clip — human escalation (0:30–0:45)

Use a separate unconnected synthetic case after recording its normal flow. The deterministic **Simulate staff-flagged clinical concern** control is an honest fallback for demonstrating the handoff machinery; label it “staff-flagged synthetic event,” never “AI detected a symptom.”

For a natural-language clinical escalation take, literal input is **I have a new symptom and need to speak with the clinic team.** Only claim model interpretation if the saved evidence labels the step Claude model. This particular wording is not a guaranteed clinical classifier test; use the result actually obtained.

Verified supporting case: **Ms Ilham**, case `1a0949f9-8b38-471e-a9ed-fe8af96cc2a7`. The staff-flagged synthetic control produced RED / CLINICAL_REVIEW_REQUIRED and **Accept handoff as me** recorded ownership by the signed-in demo staff account. It is ready to film through Overview → Ms Ilham → the **CLINICAL REVIEW** owner panel and Case journey acceptance event. Do not re-trigger it merely for a second take.

The staff task remains open. The UI marks the agent review **Completed** after the `OWNED_STAFF_HANDOFF` outcome; that means the automated handoff finished, not that the clinical concern was resolved. Say this explicitly if the Completed label is visible. No contact outcome or real call was recorded. Routine coordination frees staff to handle these concerns.

## Supporting clip — Security & Audit / minimum disclosure (0:50)

1. Intelligent intake → approved batch → masked phone summaries (about 8 seconds). Staff names are intentionally visible; do not claim all staff lists anonymize names.
2. Patient → **Security & Audit** (evidence loads when expanded). Use an actual staff correction, Bridge import or appointment-change event (about 25 seconds). Expand **Evidence, result and recorded changes**. Show actor, time, source, decision and any saved old/new values. Not every event has every field.
3. Briefly show policy ALLOW with an instruction/source-bound action (about 12 seconds), then return to the staff workspace (5 seconds).

Narration: “Clinic-scoped access, minimum necessary summaries, bounded model context, policy-gated tools and recorded evidence make actions inspectable.”

Do not claim legal compliance, medical validation, perfect anonymization, immutable/tamper-proof audit, verified encryption at rest, MFA, SingPass, a security-alert dashboard or production readiness. These are not proved by this demo. Do not change roles/accounts just to stage an access-denied shot.

## Master storyboard / editorial timing

| Time | Story beat | Picture / narration direction |
| --- | --- | --- |
| 00:00–00:40 | Dental origin | Explain the dental follow-up problem. Use clearly labelled illustration or a synthetic dental case; do not invent patient outcome statistics. |
| 00:40–01:15 | Reminders are insufficient | Requests, preparation conditions, language needs and exceptions require state and decisions. Keep any illustrative messages visibly separate from real product footage. |
| 01:15–04:00 | Doctor-note intelligence | Priya hero, 2:45. Source note → PATIENT_CHECK → answer/evidence → slot offer. Successful reschedule ending is currently blocked; use the documented honest fallback. |
| 04:00–04:25 | No-API clinics | “Some clinics start with a spreadsheet.” Show the two source paths without claiming live external EMR integrations. |
| 04:25–06:35 | Intelligent Intake | Messy export → semantic mapping → staff correction → import. |
| 06:35–07:35 | Chinese follow-up | Chen's meaningful slot request and durable waiting state, 1:00. |
| 07:35–08:20 | Malay follow-up | Calvin's concise confirmation/preparation flow, 0:45. |
| 08:20–09:00 | Generic platform | Dental, antenatal and other implemented follow-ups share the runtime. Say “shared follow-up platform,” not “supports every industry” as an implemented claim. |
| 09:00–10:40 | Staff complement / human control | Staff change and notification, then owned escalation. Routine work is coordinated; critical/complex work remains with people. |
| 10:40–11:30 | Security | Masked contact summaries, scoped staff access, real evidence. |
| 11:30–13:00 | Technical architecture | Candidate detection → durable worker → Coordinator delegates Engagement/Preparation → typed proposal → policy/tool gateway → source receipt → saved state → next event. |
| 13:00–14:00 | Future, clearly labelled | Five roadmap pillars below. |
| 14:00–14:15 | Close | “Intelligent follow-up. Bounded action. Human control.” |

Timing is an edit target, not a claim that live inference responds within these intervals. Screenshots are cutaways, not recorded motion. Leave the real UI labels intact; annotations can point to evidence but must not replace or manufacture it.

## Technical narration boundaries

The candidate detector identifies eligible source records. The persistent worker leases and resumes saved work. The Coordinator delegates to Engagement and Preparation; it is the only delegating agent. Models propose typed decisions. The gateway verifies authority, case/request binding, allowed tools, source/instruction evidence and applicable versions. A message is not proof of a booking: a source receipt is required. PostgreSQL stores durable state and evidence; the model is not the database or the authority.

For API-backed clinics, the demo's separate synthetic clinic API represents the external source. For clinics without an API, approved Bridge records, episode-scoped staff options and receipts live in Forget-lah-owned tables. Bridge does not write mock-clinic tables. Explain both paths accurately without calling the synthetic API a production EMR connection.

Language translation follows evidence-based response composition and cannot invoke booking tools. Language and conversation history persist independently of the model. Do not imply that all clinical translations are certified accurate.

## Future roadmap — NOT IMPLEMENTED in this demo

- Patient companion app: offline reminders and calendar integration.
- Follow-up Pattern Intelligence: repeated missed preventive visits and operational follow-up gaps; staff outreach insight, **not medical-risk prediction**.
- Voice-enabled channel, especially for seniors and accessibility.
- SingPass / trusted identity and consent.
- Caregiver-authorized support, directed and authorized by the patient.

Do not headline weather, traffic or events. Do not turn current developer controls or illustrative roadmap graphics into claims of shipped functionality.

## Stop conditions and repeat-take rules

- A source error, paused review, unavailable slot, failed translation, stale version or no valid appointment is a stop condition. Record the evidence and report it; this package does not authorize a product patch.
- After a network error, reload and inspect persisted state before resubmitting. An analysis or appointment action may have succeeded even when its browser response failed.
- A fresh review preserves history but does not undo appointments or free consumed slots. Record the current source date/options before each take. Never select an option from an earlier offer.
- Do not increase model budgets, enable phone delivery, erase histories or run global reset to make a scene look successful.
- A successful rehearsal is evidence of that run only. Future takes can differ. Use screenshots/current journeys when continuous motion cannot be obtained cleanly, and label them as such.

## Local implementation references

Read alongside `docs/AWS_DEMO.md`, `docs/DOCTOR_INSTRUCTIONS.md`, `docs/BRIDGE_INTAKE.md`, `docs/TEAM_CLOUD_TESTING.md`, `docs/PATIENT_SIMULATOR.md`, `docs/ADR_STAFF_APPOINTMENT_CHANGE.md`, `docs/STAFF_APPOINTMENT_CHANGE_GAPS.md`, `docs/SECURITY_ARCHITECTURE.md` and `docs/CASE_JOURNEY.md`. The live UI supplies the current labels when older documents differ.
