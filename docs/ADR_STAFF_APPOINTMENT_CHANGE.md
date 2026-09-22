# ADR: Staff changes preserve follow-up source ownership

Status: accepted, 22 September 2026.

Staff can change an existing future appointment from its patient follow-up details. This is a bounded follow-up action, not a general clinic calendar, appointment-management engine or clinical-advice editor.

## Ownership and authority

* API-backed clinics keep their appointment system as source of truth. The mock clinic represents this integration. Forget-lah reads the configured adapter and calls its authorized `staff-change` endpoint. It never updates external source tables directly.
* Bridge clinics have no capable appointment system. Approved imports create Forget-lah-owned episode state; staff changes update only `bridge_episode` and its patient-scoped reserved `bridge_followup_slot` options. Original imports remain provenance. The Bridge path never calls or changes the mock clinic.
* A staff change is not patient acceptance. Its receipt is `STAFF_CHANGED_AWAITING_PATIENT`, separate from attendance-confirmation receipts. Bridge remains `awaiting_reply` until the existing workflow records patient evidence.

## Validation and audit

Authenticated clinic membership and CSRF protect writes. The server re-reads the bound patient/episode, currently available source slots, episode/source and case versions, and prerequisites. Only a future scheduled appointment can be moved. The current appointment is not offered as an alternative. Sources currently return at most ten options and indicate when additional options exist.

Doctor notes require a completed, policy-allowed Preparation review with complete matching source quotes and current source version. Deterministic date-window enforcement and unresolved patient checks remain applicable. Missing, stale or uncertain reviews block the action; staff-entered reasons cannot override them. Active processing and unresolved handoffs must finish before staff can change the appointment.

Migration `0015` records a durable operation ID, requesting staff identity, timestamp, optional internal reason, old appointment, full selected option, request versions and source receipt in `staff_appointment_change`. Migration `sim0004` adds a separate source-owned API receipt ledger. Concurrent writes lock case/episode/slot rows and reject stale versions. Existing history is retained and a superseded waiting review is paused with provenance; the new conversation starts with refreshed evidence.

## Commit, recovery and delivery

Bridge applies the source write and receipt in one transaction. API-backed changes first save a durable intent; the source commits its appointment and idempotent receipt atomically. A lost response leaves a pending operation that staff retry using the same operation ID. Other case actions and reset cannot discard unresolved intent. A definitive source rejection is recorded; it does not produce a patient notice. If recovery discovers a newer source appointment, the old notice is withheld.

After commit, Forget-lah creates a grounded message: “Your appointment has been changed by the clinic to <verified date/time>. Please confirm if this works for you.” The optional reason is audit-only and is never sent to the patient or used as clinical guidance. Singapore time is explicit. Existing patient-language translation and the durable channel outbox handle delivery to enrolled test phones; a demo conversation entry is distinguished from an actual delivery receipt.

Notification creation, translation or delivery failure does not roll back the appointment. The dashboard shows pending/failed status and supports retry without repeating the source write or duplicating the message. Retry rechecks that the receipt still describes the current appointment. Ambiguous provider outcomes are not automatically resent. Existing channel enrollment and outbound-window restrictions remain in force; this release does not enable real-patient messaging.

The saved notification binds a subsequent acceptance to the changed appointment. Yes proceeds through the existing interpreted confirmation/acknowledgement path and source gates; refusal or a request for another time uses rescheduling; preparation questions use Preparation; clinical concerns retain the existing RED workflow. No patient reply is fabricated by a staff action.

## Staff use

Open a patient's follow-up, select **Change appointment**, choose an available source-provided time, optionally enter an internal reason, then **Confirm change and notify patient**. Refresh availability and delivery status to see the receipt or retry a failed/pending notification. Existing Bridge slot entry remains how staff supplies episode-scoped follow-up options; this action never invents capacity.

## Deployment and validation

Apply both migration chains and deploy API, worker, mock-clinic and web together. Do not reset existing data. Tests exercise real migrated SQLite/PostgreSQL test databases and isolated source adapters; deterministic model replays incur no paid calls. Local and cloud application databases are not modified merely by building or running these tests.


Verification: final focused Docker/PostgreSQL suite: **33 passed, 1 expected skip** (the SQLite variant of a PostgreSQL-only lock test). A broader staff/source-booking/reset/migration/PostgreSQL group passed **122 tests, 1 expected skip**. Docker Ruff lint and formatting, plus the final TypeScript/Vite production build, passed. Two existing dependency deprecation warnings remain. Paid live-model scenarios and physical phone delivery were not used for verification.

The full Docker/PostgreSQL regression run also passed, with 14 expected skips: 12 paid live-model opt-ins and two SQLite variants of PostgreSQL-only concurrency checks. The final focused run above verifies the last recovery changes. No local or cloud application deployment was performed.

Local deployment completed on 22 September: migrations `0015` and `sim0004` applied; API, worker, mock-clinic and web restarted. Both databases were backed up, all 31 pre-existing table checksums matched after restart, and readiness/new-route/frontend checks passed. No patient-message or appointment-write smoke test was performed. AWS remains unchanged. This supersedes the earlier pre-deployment verification status.


### Staff instruction-review action (22 September)

When an appointment lacks a current Preparation review, **Change appointment** now offers **Review doctor instructions**. The Coordinator reads the appropriate source and delegates to Preparation; the normal typed review and evidence policy validates every approved note. The panel polls progress, displays eligible times and the exact approved constraints, and supports retry/cancel if the review cannot finish. Patient checks and clinic review remain blocking; this button never fabricates their completion.

This is a bounded read-only review of an existing follow-up. Policy rejects patient messages, source writes and unrelated decisions. The saved conversation checkpoint, active delegation and waiting/completed status are restored when the review completes or is cancelled. Incoming channel replies remain queued during the review, including a paused review, then resume the original workflow. Staff initiation/cancellation and the Preparation evidence are retained in the existing event/step audit. No new schema is required. Adding or changing source options invalidates an old source-version review and exposes the action again. Bridge reads only Forget-lah-owned tables; API cases read their authorized external adapter.


Instruction-review fix verification and local deployment (22 September): all **584 collected tests** ran in four isolated Docker/PostgreSQL test processes, with **570 passed and 14 expected skips** (paid live-model opt-ins and SQLite variants of PostgreSQL-only locks). This includes Bridge/API source reviews, waiting/completed conversation restoration, source-version invalidation, doctor restrictions, retries, cancellation and late model results, queued inbound replies, and the existing staff-change/notification regressions. Docker Ruff lint/format and TypeScript/Vite production build passed. Existing dependency deprecation warnings remain. No paid model calls or live-case replays were used.

Deployed the fix locally at `http://localhost:8080`. Both databases were backed up; all **33 table checksums** matched after restarting API, worker, source and web. Existing migration heads remain `0015` and `sim0004`; this fix needs no schema migration. Readiness passed, both review routes are installed, and the served frontend includes review/retry/cancel actions. No appointments or patient messages were changed during deployment. Refresh the page, select **Change appointment**, then **Review doctor instructions** when prompted. Choose an eligible time and confirm after the review finishes.


### Staff-change waiting timer correction (22 September)

A newly inserted AgentRun receives an immediate available_at default. Staff-change runs must explicitly clear that value after insertion, and API receipt recovery must also clear it when entering waiting. Otherwise the worker wakes before any patient reply and can create a false CAPABILITY_UNAVAILABLE handoff. Waiting for the patient is event-driven; notice creation/delivery is not a reason to run the Coordinator.

Regression coverage now lets the worker attempt a claim between staff change and patient reply for both Bridge and API paths, including lost API receipt recovery. A guarded operator-only repair recognizes exactly the untouched two-step timer/read/escalation trace, checks the current source receipt, and refuses changed source data, accepted handoffs or patient activity. It retains the old run, steps and handoff, records a service-attributed correction, and links the existing notice and committed operation to a fresh waiting run. It neither repeats the appointment write nor creates/resends a notice.

Validation for this correction: 157 related runtime, channel, source-change, review and PostgreSQL tests passed; one SQLite-only variant of a PostgreSQL lock test skipped. Docker lint/format and image builds passed. The previous full-suite result remains the prior baseline. Deployed locally with backups. The affected waiting state was recovered and verified after worker restart with zero automatic steps; appointment data, receipt, notification contents/identity and historical handoff were preserved. Only the six intended workflow tables changed; unrelated tables and all external source tables matched their pre-repair checksums. No paid model call or patient message was used for recovery.


**Deferred UI gap (22 September):** The appointment-change panel can show unanswered patient checks but cannot initiate/resume them directly. This remains open and is explicitly deferred by the user. See [GAP-STAFF-CHANGE-001](STAFF_APPOINTMENT_CHANGE_GAPS.md) for the observed dead end, open instruction-scope decision and future acceptance criteria.
