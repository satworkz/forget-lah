# Forget-lah recording handoff — verified 23 September 2026

Priya's rescheduling blocker is fixed and deployed to both local and AWS. The complete AWS rehearsal succeeded. No phone disconnection or global reset is needed.

## Current recording starts

Use https://forget-lah.52-220-111-31.sslip.io/ for these prepared cases. Local has the same fix, but these specific recording states are on AWS.

| Patient | Current starting state | Target final footage |
| --- | --- | --- |
| Priya (demo) | Fresh English reminder; appointment **30 September 2026, 10:00 AM SGT** | 2:45 |
| Ms Chen | Fresh Chinese reminder for the missed visit; 28 September 14:00 option was staged in the original package | 1:00 |
| Mr Calvin | Fresh Malay reminder; appointment **29 September 2026, 14:30 SGT** | 0:45 |

Each review is waiting for a patient reply, with exactly one opening reminder and no wake timer. Chen and Calvin's full case views match the pre-deployment snapshots. Their Chinese/Malay translations are ready. Their previous successful rehearsals were not replayed during this fix.

Do not start another fresh review before the first take. Dates and availability can change; always use the newest displayed offer. Priya's previously offered 30 September slot has now been consumed by the successful rehearsal. A fresh review preserves that appointment change; it does not rewind it.

## Record Priya first

1. Start a separate silent recording. Suggested settings: 1920 × 1080, 30 fps; pause 2–3 seconds around important results. Keep synthetic/demo labels visible.
2. Clinic simulator → open Priya's saved episode ending **2e8b7cea**. Show the approved free-text note: bring the maternity booklet; confirm the mandatory scan is completed; otherwise reschedule. Do not edit it. There is no absolute date deadline in this note.
3. Staff workspace → Overview → Priya: show her current appointment and plan. Then Developer testing → Priya → Open agent review.
4. Submit once: **I need to reschedule my appointment. What other times are available?**
5. Wait for the mandatory-scan question. Show Preparation evidence / PATIENT_CHECK before continuing.
6. Submit once: **Yes, I have completed the mandatory scan.** Show the source-bound answer and MET result. Let the original rescheduling request continue.
7. Show the newest offer. If Option 1 is a suitable currently displayed alternative, submit: **Option 1 works for me. Please reschedule my appointment to that time.** Do not hard-code the date from the earlier take.
8. Show INTERPRET_SELECTION, the permitted source action and successful receipt, then the acknowledgement and completed review. A message alone is not proof of booking.
9. Stop on Current plan / Case journey. Cut inference waits during editing; never replace product output with invented results.

If a source/model error occurs, inspect the persisted run before retrying. Do not resubmit the patient message while the worker is already processing or retrying. A paused/failed take is not a successful booking.

Narration direction: “A doctor-defined prerequisite becomes a structured check. The answer is saved against the instruction. The patient selects an offered alternative, and authorized source tools verify and record the change.”

## Chinese and Malay takes

**Ms Chen — 1 minute**

Show the saved Chinese preference and missed-visit state. Submit:

> 我错过了上次的预约，想重新安排。请问有哪些可选的时间？

Subtitle: “I missed my previous appointment and would like to arrange another time. What options are available?”

Show the actual Chinese alternatives, source-provided availability, referral-letter evidence and durable waiting state. Stop before booking; the Chinese booking ending has not been verified.

**Mr Calvin — 45 seconds**

Show the saved Malay preference and appointment. Submit:

> Ya, saya akan hadir. Apa yang perlu saya bawa?

Subtitle: “Yes, I will attend. What should I bring?”

Show the actual Malay acknowledgement, structured attendance confirmation and preserved preference. The earlier rehearsal included the spectacles instruction but did not repeat the screen-use restriction; narrate only the output actually visible in this take. Use Calvin, not Omar.

## Supporting clips and edit

The existing storyboard targets **14:15**, not the earlier proposed 30 minutes. Continue its dental origin → reminder limitations → doctor-note intelligence → no-API intake → multilingual follow-up → shared platform → staff control → security → architecture → future story.

- Intake: use the original REVIEW/READY screenshots as historical cutaways. The batch is already imported. Re-analysis may differ and re-approval may skip duplicates; do not reset the shared clinic for a shot.
- Alex: film the existing staff change receipt and simulated notification. It is not phone delivery or patient acceptance.
- Ms Ilham: film the existing named RED handoff. The staff task remains open; Completed refers to the automated review.
- Security: masked summaries and actual audit evidence. No production compliance certification is implied.
- Move quickly from chat bubbles to the plan, doctor instructions, evidence, source receipt or staff ownership. Position Forget-lah as supporting clinic staff.
- Add narration and explanatory visuals after reviewing the Priya footage. Label the companion app, pattern intelligence, voice, SingPass and caregiver support as future features.

**No MP4, narration track or new screenshot was produced in this repair.** The revised ZIP includes the original ten JPEGs under `original-package/assets/`; they remain historical, unaltered captures. Its original gallery/runbook retain the earlier blocked-state report. This handoff supersedes that report for Priya's current readiness and starting appointment.

## Verified repair and retained evidence

The failure was routing: CHANGE / SEARCH_SLOTS suppressed the existing selection offer, and search guidance could override selection handling. The fix keeps the saved offer available to Engagement and removes conflicting search guidance while interpreting or completing a validated selection. Interpretation still passes the existing policy, offer/reply binding, doctor-instruction and source/version checks.

- Complete offline suite: **638 passed, 14 expected skips**, including PostgreSQL tests. Twelve skips are paid live-model opt-ins; two are SQLite variants of PostgreSQL-only checks. Ruff, formatting, diff checks and production web build passed.
- The same runtime image is deployed to API and worker locally and on AWS. No schema migration or frontend deployment was required.
- Both databases were backed up in each environment. All pre-existing values across **34 tables per environment** matched before/after deployment, before workers resumed. AWS configuration checksum was unchanged. No global reset, history deletion, phone-binding change or secret rotation.
- AWS live rehearsal submitted the three Priya messages once each. One transient model connection failure recovered through the existing bounded retry; no duplicate patient submission.
- Step 11: source-bound scan answer, MET. Step 25: model-origin INTERPRET_SELECTION, Option 1, policy ALLOW. Step 26: successful source receipt. Step 32: acknowledgement. Step 33: completed, SIMULATED_ATTENDANCE_CONFIRMED. Exactly one offer and one rescheduling receipt.
- Independently read the source episode: appointment changed from **25 September 10:00 to 30 September 10:00 SGT**, source episode version 2. This is a synthetic clinic source, not real patient care or phone delivery.
- A fresh Priya recording review was then created without reversing the source change. Chen and Calvin were left untouched.

### Case/review references

| Reference | ID |
| --- | --- |
| Priya case | `816abd6e-ab28-44c8-af74-e13406ca2357` |
| Priya source episode | `SIM-12ac5378-3b74-4bee-97be-69bb2e8b7cea` |
| Original failed rehearsal, retained | `0871c2aa-96be-44f2-b51f-ef785a673b59` |
| Successful full rehearsal, retained | `ff4d8fce-0900-4d89-b101-4e42bbebd80c` |
| Source receipt | `3628a4e9-3c52-4224-8e59-cecc2e8e6456` |
| Fresh Priya recording review | `7e1567c3-76d2-4657-9d72-ad824b572e36` |
| Chen case | `d90bf175-d18a-436e-a055-0e7c54b879f5` |
| Calvin case | `4099aeb8-ef24-471a-ac82-60fbe632c148` |

A successful rehearsal verifies this run, not guaranteed future model behavior. Review the first recorded Priya take before capturing the remaining scenes.
