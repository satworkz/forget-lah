# Expired scheduled appointments: staff review before slot offers

An imported appointment may still be marked `scheduled` after its recorded time has passed. Forget-lah must not infer attendance or automatically convert that record to a no-show.

When a patient requests a change or an alternative-slot search, current source evidence is checked against the clock. A scheduled appointment that is no longer in the future requires an administrative staff handoff before any new offer is sent. The same check blocks an offer that was valid when displayed but whose original appointment expired before selection. Source write, consent, instruction and version checks remain in force.

The rule records `APPOINTMENT_STATUS_REVIEW_REQUIRED` in decision evidence and uses the existing `CAPABILITY_UNAVAILABLE` AMBER handoff. English acknowledgements explain that the original appointment time has passed and that staff must check its status. Other supported languages retain the existing safe static failure acknowledgement when that path applies.

This change does not change appointment status, invent slots, mark attendance/no-show, or reopen existing escalations. A future scheduled appointment and a source-confirmed due/no-show follow-up retain their existing validated rescheduling/booking paths.

Regression coverage includes expiry before a slot request and expiry after an offer, with no source write and no additional offer. Existing Bridge booking/rescheduling and failure-handling tests remain applicable. Release-specific test and preservation results are kept in the local deployment evidence; no GitHub commit or push is part of this change.

## Deployed 28 September 2026

- Release `20260928-expired`, image `forget-lah-expired:20260928`, built from the exact retained AWS runtime with only the three changed runtime modules replaced. All 80 Python source files in the release matched the local checkout after line-ending normalization.
- Full local regression: **668 passed, 77 skipped**, with two existing dependency deprecation warnings. Skipped checks are not claimed as passed.
- Isolated PostgreSQL regressions: **4 passed, 23 deselected** in the Bridge runtime test module; covered both expiry boundaries and ordinary rescheduling/no-show booking. The broader remote batch was stopped because of host slowness; it is not counted as a completed suite.
- Ruff lint/format, whitespace checks and frontend build passed.
- Both databases backed up under `/home/ubuntu/forget-lah/backups/20260928-expired/`. All values across 34 tables matched before and after API restart, before resuming the worker. Migration heads remain `0017` and `sim0004`; no migration, seeding, reset or case replay.
- API and worker image/file identity verified; organiser mode retained. HTTPS `/health/ready` returned 200, anonymous case access 401, sign-in 200 with Secure cookies, missing-CSRF logout 403, and frontend 200. PostgreSQL has no published host port; bounded API/worker log scan found no configured credential values.
- Mrs Nila's existing escalation remains open and unaccepted, with 19 recorded steps and the original 28 September 10:00 SGT appointment unchanged. Deployment does not retroactively resolve a staff-owned review or retry the patient selection.
- Local evidence: `.cache/aws/release-20260928-expired/`. No paid model calls were used for validation. Changes remain local and uncommitted for the user to review and commit later.
