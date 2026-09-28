# Priya prerequisite date and completion correction — 28 September 2026

> Superseded for date interpretation by [Natural reply recovery](NATURAL_REPLY_RECOVERY_20260928.md). The strict date parser described below was removed later the same day. Historical deployment and reset details below are retained for traceability.

## Change

A successful appointment receipt now drives a deterministic Coordinator continuation: refresh Preparation evidence against the new source version, acknowledge only when the existing evidence/policy checks pass, and complete only after acknowledgement. Failed source calls retain the existing bounded retry/handoff path; source writes are not replayed.

When an unmet doctor instruction explicitly requires rescheduling after completion, the workflow asks for a prerequisite completion date before offering slots. The answer is recorded as patient-reported evidence, not clinical certification. It accepts YYYY-MM-DD or an explicit English day/month/year date, does not guess a date from an appointment preference, and hands uncertain answers to staff after a bounded clarification. Offers and booking checks enforce dates after the reported completion date. The source query uses that lower bound before its result limit.

## Validation

100 passed, 16 skipped across doctor-action, doctor-scheduling, patient-simulation and Bridge-runtime tests. New regressions cover date collection, unknown dates, appointment-preference ambiguity, eligible slots, one source write, acknowledgement and completion without a post-receipt model decision. Historical failure tests explicitly reproduce pre-rule behavior. Ruff check and format check passed. No full production or paid-model rehearsal was performed.

## AWS release and reset

Release: 20260928-priya-completion-v2. Initial packaging attempt rolled back due to file permissions; corrected image passed import preflight and readiness. Both databases backed up, 34 tables compared unchanged before/after deployment, revisions 0017/sim0004 unchanged. API/worker use the same verified image; all three changed runtime files match local SHA-256 values. No frontend change.

Only Priya was reset through the authenticated simulator and fresh-run APIs. Restored appointment: 2 October 2026, 10:00 SGT. Released only the slot held by her old receipt. Old run and receipts retained as history. Fresh run 1c3d9f20-059e-46e0-b488-b7aa9f34cb67 is waiting with one reminder, no handoff. All five other current case details, other source episodes/slots and channel state matched the pre-reset snapshot. No active Priya phone binding; no WhatsApp messages were sent.

## Rehearsal

Open Priya in Developer testing / patient simulator. Reply that she can attend. Answer no to the mandatory-scan question. When asked the completion date, enter 2026-10-03. Choose an offered appointment after that date. The original appointment must remain unchanged until an eligible option is selected and the source confirms it.

No Git commit or push was made. Private deployment/reset evidence remains under ignored .cache/aws/release-20260928-priya-completion; server backups are under backups/20260928-priya-completion-v2.
