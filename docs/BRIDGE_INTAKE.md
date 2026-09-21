# Forget-lah Bridge — Intelligent Follow-up Intake

Forget-lah Bridge is a legacy-clinic interoperability layer for **patient follow-up**. It is deliberately not an appointment-management system.

## Why it exists

Many clinics cannot expose appointment and patient follow-up context through a modern API. Bridge accepts the export the clinic already has and uses AI to understand its meaning instead of requiring a Forget-lah column template.

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
6. Staff may correct the AI in natural language and re-analyse.
7. Staff approves ready records.
8. Approved records become a **read-only Bridge source** in the Forget-lah database.
9. Existing case detection creates `UPCOMING`, `MISSED` and `RECALL_OVERDUE` cases when the source record becomes eligible.
10. Existing agents then run unchanged against the Bridge source contract.

## Important boundary

Bridge stores its own provenance and normalized source rows in Forget-lah tables:

- `bridge_intake_batch`
- `bridge_intake_record`
- `bridge_import_profile`

It does **not** insert or update any `services/mock_clinic` table.

Bridge sources advertise `can_write_appointments=false`. If a patient asks for a change that requires a clinic-system write, the existing bounded workflow must hand that action to staff unless a separately authorised write API is introduced later.

## Intelligence without silent guessing

The model may infer semantic meaning from arbitrary headers, combined columns and clinic-specific terminology. It must also return exact source evidence for extracted values. In particular, doctor instructions are rejected if the proposed text is not present in the uploaded row.

A clinic-specific semantic profile is remembered only after staff approval. On future imports it is supplied as a hint, not as authority. Staff can override it with natural-language correction.

## Source identity

If an export contains a stable clinic visit/episode identifier, Bridge uses it to derive a stable source reference. Otherwise it derives a deterministic reference from the patient and follow-up episode context. This keeps repeated exports from becoming arbitrary new source episodes.

## Safety

- Upload size and row/column counts are bounded.
- Uploaded cell text is treated as untrusted data, never as model instructions.
- AI analysis creates a preview only; no follow-up case is created before staff approval.
- Low-confidence/ambiguous records remain in review.
- Appointment writes are disabled for Bridge sources.
- Existing doctor-note policy, clinical RED escalation, multilingual handling and durable agent runtime remain unchanged.
