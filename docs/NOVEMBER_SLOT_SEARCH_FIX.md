# Date-window slot search and staff attention

28 September 2026. The synthetic clinic source previously returned its first ten future slots before the runtime filtered by the patient date range. This made November look unavailable when earlier October slots filled that list. Validated persisted date constraints now travel with the source read; the source filters by Singapore calendar dates before returning ten options. Its source version covers all available slots independently of the requested window, preserving consistent confirmation and staff-change validation. Bridge remains separately owned and has at most ten reserved alternatives per patient.

An empty patient-preference match is no longer labelled a doctor-instruction conflict. Actual doctor constraints still filter offered slots and source receipts are still required for successful changes. This patch does not infer a scan completion date or remove prerequisite checks.

The staff Needs attention tab again shows only escalated or paused cases. Overview retains the wider due-follow-up list and all records. Escalated cases and Paused reviews are explicit filter choices. Browser preview with the current synthetic snapshot showed only Priya in staff attention; the escalated filter was verified.

Verification: 98 passed / 1 skipped in scheduling, adaptation, simulator, patient simulation and dashboard coverage; two additional regressions passed (end-to-end later-month offer and booking beyond ten earlier slots; patient-time mismatch is not a doctor conflict); 24 passed / 19 skipped in staff appointment changes. Total 124 passed / 20 skipped. The skipped cases require optional database/environment configuration; this run does not establish PostgreSQL concurrency behavior. Ruff and frontend build passed. Tests used local simulated models, not paid provider replay.

AWS release: 20260928-month-search. No migration, reset or replay is part of this deployment. Priya's existing historical handoff is preserved; the patch affects subsequent processing, not the contents of historical messages. No Git commit or push.
