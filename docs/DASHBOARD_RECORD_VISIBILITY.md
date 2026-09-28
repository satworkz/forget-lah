# Dashboard record visibility

Deployed to AWS on 28 September 2026 as `20260928-dashboard`.

The staff Overview now shows Requires attention first, followed by All records. The read-only inventory combines the configured clinic-source candidate feed, approved Bridge episodes, and saved cases that no longer appear in that feed. It is scoped to the signed-in clinic memberships; viewer names remain masked. Records are appointment/recall episodes, not unique-patient counts. Draft or unapproved intake rows remain in Intelligent Intake.

Attention includes upcoming appointments within seven days, explicit missed visits, overdue recalls, paused/escalated cases and past appointments still marked scheduled (verify status). Future records remain visible without creating cases, messages or model calls. Viewing a record does not infer attendance or no-show. Existing case links open the established follow-up detail. Source failures show a warning while preserving Bridge and saved-case visibility. The source adapter currently supplies up to 500 candidates; larger integrations need pagination.

Validation: 72 targeted dashboard, security and foundation tests passed; one PostgreSQL-only test skipped. Ruff checks and production frontend build passed. AWS readiness returned 200; unauthenticated inventory access returned 401. Live inventory contained 10 records, six requiring attention, including both Priya appointments, Nila and Omar. The served frontend bundle contains both new sections. Both databases were backed up; all 34 tables matched before/after restart, migration revisions remained 0017/sim0004 and environment configuration was unchanged. No records were reset, reimported or replayed. The earlier expired-appointment fix was retained in the base image. No Git commit or push performed.

Local release evidence: `.cache/aws/release-20260928-dashboard/`. Server release and backups: `/home/ubuntu/forget-lah/releases/20260928-dashboard/` and `/home/ubuntu/forget-lah/backups/20260928-dashboard/`.

## Record detail polish (28 September)

Frontend-only AWS release `20260928-record-details` adds View record for every entry, an accessible read-only dialog, source/status filters and clearer priority cards. Details show date, source status, specialty, ownership, follow-up state and next-step guidance; they do not claim access to a conversation where no case exists. Built and browser-checked using a read-only snapshot of the synthetic AWS inventory: Priya past record, Nila future record, future filtering, close and Escape. Live readiness and deployed frontend asset verified. Backend/worker/database untouched by this release. No Git commit or push.
