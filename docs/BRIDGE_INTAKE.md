# Forget-lah Bridge — Intelligent Follow-up Intake

Forget-lah Bridge is the Forget-lah-owned intake and follow-up path for clinics without an appointment system. After approval, Forget-lah owns the imported appointment record and its follow-up lifecycle, including confirmations, supported bookings and rescheduling. Clinics with an existing API-based appointment system use the separate clinic API adapter; the mock clinic represents that integration path.

## Why it exists

Clinics without an appointment system may keep their records in spreadsheets. Bridge accepts those records and uses AI to understand their meaning instead of requiring a Forget-lah column template.

Supported upload formats in this milestone:

- CSV
- TSV
- XLSX (first worksheet; no Excel library/runtime required)

## Flow

1. Staff uploads an existing clinic export.
2. Claude profiles headers **and values** and infers the purpose and semantic mapping.
3. Rows are normalized into a bounded Forget-lah follow-up contract.
4. Deterministic validation checks source grounding, dates and required follow-up fields.
5. Low-confidence or ungrounded rows stay in `REVIEW`; they are never silently imported.
6. Staff may correct the AI mapping in natural language and re-analyse.
7. Any row left in `REVIEW` can be opened and edited directly in the preview; no source-file correction or re-upload is required.
8. Staff-reviewed administrative corrections are recorded with reviewer/time/change provenance. Doctor notes remain source-bound to the original uploaded row.
9. Staff approves ready records.
10. Approved records become **Forget-lah-managed appointment and follow-up records**, retaining the original upload as provenance.
11. Existing case detection creates `UPCOMING`, `MISSED` and `RECALL_OVERDUE` cases when the source record becomes eligible.
12. The existing agents review the reply and preparation evidence, save valid attendance confirmations in Forget-lah, acknowledge them and complete the review using the saved receipt.

## Important boundary

Bridge stores its own provenance and normalized source rows in Forget-lah tables:

- `bridge_intake_batch`
- `bridge_intake_record`
- `bridge_import_profile`
- `bridge_confirmation` (migration `0013`), for durable operation receipts bound to the imported record, case, run and reply
- `bridge_episode` (migration `0014`), for the current owned appointment state, version and follow-up status
- `bridge_followup_slot` (migration `0014`), for staff-reserved alternatives scoped to one follow-up episode

Staff review provenance (`staff_overrides`, reviewer and review time) is stored on `bridge_intake_record` by migration `0012`.

It does **not** insert or update any `services/mock_clinic` table.

The Bridge adapter records attendance confirmations internally without a mock-clinic API key. The current conversation tools retain their simulator names because staff-entered demo replies are simulated input; their Bridge receipts explicitly identify Forget-lah as the record owner. Confirmation requires validated reply evidence, current appointment/version binding and the doctor-instruction preparation gate. Retries reuse the same receipt rather than creating duplicate confirmations.

In the staff workspace, open an imported patient’s follow-up and use **Available slots for this patient**. Enter start/end in Singapore time and a doctor or clinic team, then select **Add available slot**. Staff can add or withdraw reserved follow-up options on an imported case. The agent offers those options under the existing doctor-note and patient-selection checks. Booking a missed/recall follow-up or rescheduling a future appointment updates `bridge_episode` and consumes the selected option atomically. Stale versions and withdrawn options cannot be booked. The original appointment remains on any failed operation. No external API is needed. Missing options may require staff to supply times; they are never invented. Original uploaded rows remain immutable provenance.

This is a bounded follow-up source, not a clinic calendar or EMR: options are reserved for one patient episode, and no general schedule, clinical chart or inferred capacity is introduced. Cancellation remains a staff workflow because the shared runtime does not yet support a cancellation tool.

The staff option endpoints are `POST /api/bridge/cases/{case_id}/options` and `POST /api/bridge/cases/{case_id}/options/{slot_id}/withdraw`. Both require current clinic membership, CSRF, an expected episode version and clinic-scoped case lookup. Adding availability alone never sends a message or changes an appointment.

## Intelligence without silent guessing

The model may infer semantic meaning from arbitrary headers, combined columns and clinic-specific terminology. It must also return exact source evidence for extracted values. In particular, doctor instructions are rejected if the proposed text is not present in the uploaded row.

A clinic-specific semantic profile is remembered only after staff approval. On future imports it is supplied as a hint, not as authority. Staff can override it with natural-language correction.

## Source identity

If an export contains a stable clinic visit/episode identifier, Bridge uses it to derive a stable source reference. Otherwise it derives a deterministic reference from the patient and follow-up episode context. This keeps repeated exports from becoming arbitrary new source episodes.

Tool source versions are stable 40-character receipts derived from the managed episode ID and version, so they fit the existing message storage limit. Runs with older, longer Bridge receipts can resume: message creation compacts the receipt and preserves the original value in message evidence. Saved tool results remain intact. Migration `0014` initializes owned state from existing approved imports without re-import. Later duplicate imports do not overwrite managed state; a visit reference cannot be reassigned to a different patient. A stable visit identifier is recommended when subsequent exports contain changed dates.

## Safety

- Upload size and row/column counts are bounded.
- Uploaded cell text is treated as untrusted data, never as model instructions.
- AI analysis creates a preview only; no follow-up case is created before staff approval.
- Low-confidence/ambiguous records remain in review until a staff member explicitly resolves them in the UI.
- Staff can correct normalized administrative fields in-place without changing the original raw upload; the raw row remains visible for comparison and audit.
- Staff cannot turn the review editor into free-form clinical-note entry: doctor-note text must still be present in the uploaded source row.
- Validated attendance confirmations are owned and stored by Forget-lah. Slot booking/rescheduling uses staff-reserved Bridge options and writes Bridge tables only. Absence of an external API is never an escalation reason.
- Existing doctor-note policy, clinical RED escalation, multilingual handling and durable agent runtime remain unchanged.
- The demo reset confirmation includes Intelligent Intake by default; this clears uploads, managed episodes, options, confirmations and history for the demo clinic. Uncheck the intake option to preserve these records. See [Demo reset](DEMO_RESET.md).
