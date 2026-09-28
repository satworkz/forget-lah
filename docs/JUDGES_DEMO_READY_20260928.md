# Judge demo set — staged 28 September 2026

The AWS reset clears application follow-up history, not the external Clinic System. This staging deliberately refreshed both synthetic source data and application cases after backing up both databases. Do not reset again before judging: that removes the new journeys and, with the default checkbox, the Intelligent Intake import. Dates below are Singapore time and are a dated demo snapshot, not a rolling seed.

## Current state

10 records; 9 eligible follow-up cases, all waiting for a patient response with one real system-generated initial simulated message. Grace is intentionally outside the seven-day window and has View record only. All other records have Open follow-up and Case journey. No final escalation, booking or confirmation outcome has been fabricated or preplayed.

| Patient | Appointment / recall | Demonstration |
|---|---|---|
| Mr Ahmad | 30 Sep, 10am | Dental; reply in Malay with confirmation plus pain/swelling to demonstrate separation of administrative intent and clinical escalation |
| Priya | 2 Oct, 10am | Mandatory scan prerequisite; explain scan incomplete, provide 5 Oct as completion date, request a later appointment; select only an actual offered option |
| Alex | 1 Oct, 10am | Request Chinese, say you plan to drive home, then change to accompanied travel; demonstrate the doctor-note conflict and its resolution |
| Mr Lim | Recall due 21 Sep | Overdue recall and source-backed follow-up options |
| Mr Daniel | Missed 26 Sep visit | Explicit missed appointment; request a new available visit |
| Mr Calvin | 3 Oct, 10am | Staff dashboard Change appointment; inspect validation and resulting evidence |
| Mrs Nila | 3 Oct, 10am | Approved Intelligent Intake, Tamil preference, scan prerequisite and three staff-reserved alternatives |
| Mr Omar | 4 Oct, 10am | Approved Intelligent Intake, Malay preference and preparation instructions |
| Ms Chen | Missed 26 Sep visit, 9am | Approved Intelligent Intake, Chinese preference and three staff-reserved booking alternatives |
| Ms Grace | 12 Oct, 10am | Future record visibility without premature follow-up |

## How to inspect

Staff workspace > Overview > Open follow-up > Case journey. Doctor notes and Security & Audit appear in each eligible case. Developer testing exposes the synthetic patient reply controls and technical evidence. WhatsApp phone bindings were preserved in their existing disabled state; connect a designated test phone explicitly if you want a live channel demonstration. No new WhatsApp dispatch was made during staging.

Intelligent Intake contains the actual organiser-model analysis and approval of `clinic_followup_import_20260928.csv`, including review provenance. Two uncertain specialty assignments were explicitly reviewed to general instead of accepting an unsupported specialty inference. The original analysis is retained. The CSV is in `docs/examples/`. The successful import is already approved; do not reimport it merely to inspect it.

Availability expanded on 28 September: the Clinic System now has 159 slots across dental, myopia and antenatal, including Tuesday/Thursday 10am, 2pm and 6pm throughout October and November, with 30-minute duration. The existing slots were retained. Each Bridge patient has ten independently reserved options: 6, 8, 10 and 13 October at 10am; 20 October at 2pm; 27 October at 6pm; 5 November at 10am; 12 November at 2pm; 19 November at 6pm; and 26 November at 10am. Bridge's ten-option limit is respected. Appointment dates and conversations were not reset. Actual offers remain subject to patient preferences, doctor instructions, current availability and source validation.

After-hours patient questions can be demonstrated in an active case using recorded appointment/instruction context. Questions unsupported by clinic evidence should go to staff. Waitlist cancellation, mobile companion, voice and other roadmap items remain future capabilities and were not staged as implemented outcomes.

## Evidence and preservation

Backups: `/home/ubuntu/forget-lah/backups/demo-curation-20260928/` (`app.dump`, `source.dump`, verified archive listings). Local verification: `.cache/aws/demo-curation-20260928/verification.json`. Six API-backed cases plus three Bridge cases were verified waiting, with one initial message each. Ten records, nine attention records, no past-scheduled warning, zero enabled phone bindings. Credentials and phone binding records were retained. No Git commit or push.
