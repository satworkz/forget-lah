> **Updated 23 September:** Priya’s full reschedule is now verified after a deployed routing fix. Her fresh recording start is 30 September 10:00 SGT. Read [the current recording handoff](RECORDING_HANDOFF_2026-09-23.md) first. The report below preserves the earlier rehearsal and its limitations.

# Demo preparation — verification and asset manifest

Date: 23 September 2026, Singapore time. Read this before filming. This is a production-preparation report, not a claim that the finished video or all desired flows are complete.

## Verified live

| Scene | Observed result | Practical limit |
| --- | --- | --- |
| Priya prerequisite | Existing free-text scan note → Preparation PATIENT_CHECK with `if_not_met: RESCHEDULE`; question asked; affirmative patient answer → INTERPRET_INSTRUCTION_CHECK; alternatives offered. | Final selection re-offered slots instead of rescheduling. Full hero ending is blocked. |
| Chinese — Ms Chen | Saved `zh`; Chinese missed-appointment request; Chinese offer for the staff-supplied 28 September 14:00 slot; waiting for selection. | Booking was intentionally not exercised. Initial historical reminder remains English. |
| Malay — Mr Calvin | Saved `ms`; “Ya, saya akan hadir. Apa yang perlu saya bawa?”; Malay acknowledgement with 29 September 14:30 and spectacles instruction; staff state Completed / Confirmation recorded in Forget-lah. | Response included only the relevant spectacles instruction, not the full source note. This is simulated input and displayed output, not phone delivery. |
| Intake | Existing `bridge_demo_1.csv` analyzed: 95% overall, 2 READY, 1 REVIEW. Calvin specialty corrected Myopia → General with review reason. Row became READY / Staff reviewed. Approval reported 3 source records, 3 immediate cases. | Original raw rows retained. This batch is now imported, not a fresh REVIEW starting state. New model runs can produce different confidence/review outcomes. CSV verified; XLSX support inspected in repository only. |
| Staff appointment change | Separate Alex case: read-only doctor review completed; source changed 25 September 10:00 → 29 September 10:00; committed source receipt, `STAFF_CHANGED_AWAITING_PATIENT`, saved patient notification and new waiting review. | No phone delivery; staff change is not patient acceptance. Ms Ilham's past appointment was correctly blocked by this panel. |
| Human escalation | Ms Ilham: documented staff-flagged synthetic control → RED; named acceptance → `OWNED_STAFF_HANDOFF`; staff task status remains `open`. | Rule-origin event, not model symptom detection. UI Completed describes the finished agent review, not a resolved clinical task. |
| Security & Audit | Alex panel visibly showed actor, timestamp, clinic_api source, committed staff change and exact receipt with old/new dates. Intake summaries showed masked contacts. | No role-change, access-denial staging or production compliance assessment performed. |
| AWS availability | HTTPS readiness returned HTTP 200 / ready. Live staff, developer, source-editor and intake views inspected. | Browser showed intermittent Failed to fetch and one expired sign-in session. Reload recovered saved state; the interrupted intake request had succeeded. No duplicate analysis was submitted. |

## Exact rehearsal messages and outputs

### Priya

1. `I need to reschedule my appointment. What other times are available?`
2. Actual question: `Have you completed the mandatory scan? No appointment changes will be made until this is resolved.`
3. `Yes, I have completed the mandatory scan.`
4. Actual alternatives: 30 September 10:00; 3 October 10:00; 6 November 10:00, all SGT, Demo doctor. No date deadline exists in this source note.
5. `Option 1 works for me. Please reschedule my appointment to that time.`
6. Actual result: the same alternatives were offered again and the message explicitly said the existing appointment was unchanged.

Saved case: `816abd6e-ab28-44c8-af74-e13406ca2357`. New source episode: `SIM-12ac5378-3b74-4bee-97be-69bb2e8b7cea`. Historical rehearsal run: `0871c2aa-96be-44f2-b51f-ef785a673b59`. Preparation step 10 contains the PATIENT_CHECK. Step 11 is INTERPRET_INSTRUCTION_CHECK with outcome MET and exact answer quote. In the failed selection turn, steps 16–26 reviewed needs/barriers, reread source/preparation, delegated Engagement with a slot-search goal and sent options again. Step 20's goal already described the patient as having selected Option 1, but there was no INTERPRET_SELECTION / source write in that turn. This is an observed routing failure, not a confirmed root-cause diagnosis. Preserve this trace; do not patch the product as part of video preparation.

### Ms Chen

Input: `我错过了上次的预约，想重新安排。请问有哪些可选的时间？`

Actual output:

> 未预约任何时间。以下替代诊所时段现在可供选择：
> 选项1：2026-09-28 02:00 PM SGT — Demo clinic team
>
> 哪个选项适合您？我们将在确认您的选择或更改您现有的预约之前检查可用性。

Meaning: no booking yet; the listed alternative is available now; selection will be checked before confirmation/change. Native-language clinical validation is not claimed.

### Mr Calvin

Input: `Ya, saya akan hadir. Apa yang perlu saya bawa?`

Actual output:

> Terima kasih, Encik Calvin. Kami telah merekodkan pengesahan anda untuk 2026-09-29 pada 02:30 PM SGT.
>
> Klinik anda menasihatkan: Bawa cermin mata sedia ada anda.

Meaning: confirmation recorded for the stated appointment; clinic advises bringing existing spectacles. The source also contains a screen-use instruction, but this response did not repeat it. Do not narrate otherwise.

## State changes made for preparation

- Added a separate synthetic appointment for the existing Priya through **Add another appointment for this patient**, dated 25 September 10:00, with her existing approved scan note. Her old visit remains. No architecture/product change.
- Added one reserved Bridge option for Ms Chen, 28 September 14:00–14:30, Demo clinic team. Saved Chinese explicitly. Submitted one Chinese availability request; no selection/booking.
- Analyzed and staff-reviewed the existing second CSV fixture; imported Mrs Jolene, Mr Calvin and Ms Ilham through normal approval. Calvin's unsupported specialty inference was corrected to General; doctor-note text was not edited.
- Saved Malay explicitly for Calvin and rehearsed one attendance/preparation reply. The receipt belongs to Forget-lah's Bridge source.
- Mr Omar's language was initially saved as Malay during candidate preparation. His WhatsApp connection was not disconnected and no new Omar reply/review was initiated. Final handling of this preference is recorded in the handoff section.
- Added a separate 25 September 10:00 appointment for existing Alex using his current approved note, then performed the requested supporting staff-change verification to 29 September 10:00. Old Alex episodes remain. The resulting source receipt names `clinic_api` as owner.
- Added a synthetic reserved option for Ms Ilham, 28 September 15:00–15:30. No appointment change was allowed because the original visit is past. The option remains available. Used the documented staff-flagged escalation and accepted ownership; no clinical resolution was entered.
- Started one fresh review for each of Priya, Chen and Calvin after retaining/capturing the rehearsal evidence. This is a new review, not history deletion or reversal of source receipts.
- No global reset, database edits, secret changes, code patch, deployment, budget increase or real-patient communication was performed. Bound teammates' cases were not used for rehearsal.

## Asset use

JPEG files are direct browser captures, not fabricated UI or motion recordings. The package contains no MP4. Use OBS for motion takes; the runbook supplies exact clicks, patient text, pauses, expected states and stop conditions. Preserve simulated/synthetic labels in the edit.

The screenshot contact values visible in the intake raw-row editor are from the repository's synthetic fixture. Team phone enrollment panels and credentials are excluded from deliverable images. Do not use broad developer-page captures that include that panel.

## Final handoff state — verified at approximately 14:55 SGT

| Patient | Case ID | State left for recording |
| --- | --- | --- |
| Priya (demo) | `816abd6e-ab28-44c8-af74-e13406ca2357` | Fresh review `ff4d8fce-0900-4d89-b101-4e42bbebd80c`, waiting, 3 initial steps, one English reminder for 25 September 10:00. No reply submitted in this review. Full reschedule ending still flagged unstable. |
| Ms Chen | `d90bf175-d18a-436e-a055-0e7c54b879f5` | Fresh review `07dca980-05e7-4ac9-be76-5c93a49e116b`, waiting, one Chinese reminder, translation ready, saved future preference zh. Her 28 September 14:00 option remains available. |
| Mr Calvin | `4099aeb8-ef24-471a-ac82-60fbe632c148` | Fresh review `52aa3418-d351-4061-a251-7090b6b622e9`, waiting, one Malay reminder, translation ready, saved future preference ms. Appointment remains 29 September 14:30. Historical completed rehearsal/confirmation remains in the journey. |
| Alex (demo) | `9510ac36-744a-4c44-ba79-c6dc584996aa` | Staff-changed appointment 29 September 10:00; waiting for patient confirmation; receipt and simulated notification ready to film. |
| Ms Ilham | `1a0949f9-8b38-471e-a9ed-fe8af96cc2a7` | Owned RED handoff, task open. Automated review completed with OWNED_STAFF_HANDOFF. |

All three hero reviews have `available_at: null` and AWAITING_PATIENT_REPLY. Prior histories are retained. Calvin's completed rehearsal is `ca321a9d-adcb-4ca1-8cc0-07a43bbb20d7` with SIMULATED_ATTENDANCE_CONFIRMED. Do not describe the new waiting review as if it were that earlier completed run.

Mr Omar's unused language change was restored to English; the preference-edit audit remains. His phone connection and conversation were left intact. Mr Lim was untouched. No temporary disconnection is needed for the selected cast.

## Files in the delivered asset folder

| JPEG | Evidence / suggested use |
| --- | --- |
| `01-priya-patient-check.jpg` | Real Preparation decision: PATIENT_CHECK, exact condition, neutral question and RESCHEDULE consequence. Technical evidence cutaway; zoom in during editing. |
| `02-chen-chinese-offer.jpg` | Chinese meaningful request and actual offer in Case journey. |
| `03-calvin-malay-confirmation.jpg` | Malay confirmation/preparation reply and actual translated acknowledgement. |
| `03b-calvin-completed-state.jpg` | Historical completed review and Forget-lah-owned confirmation state, before staging the fresh review. |
| `04-intake-review-before.jpg` | Actual REVIEW row, original source and editor before correction. The form extends beyond the viewport; the shown comparison and specialty field are usable, but this is not a capture of every editor field. |
| `05-intake-ready.jpg` | READY / Staff reviewed result before approval. |
| `06-staff-change-receipt.jpg` | Actual old/new dates, actor and explicit no-phone-delivery status. |
| `07-security-audit.jpg` | Committed source receipt and actor; staff change waiting for patient. |
| `08-owned-human-handoff.jpg` | Named staff ownership of the synthetic clinical-review task. |
| `09-masked-intake-summary.jpg` | Imported synthetic patient summaries with masked contacts and staff-reviewed Calvin row. |

Screenshots were captured from the browser at its available viewport, not as 1080p video. No screenshots were regenerated or altered to fake a state. The runbook is the editable master storyboard and recording script. Only documentation is added to the repository; no product test suite was rerun for these documentation-only additions. Live checks above are bounded examples, not reliability guarantees.
