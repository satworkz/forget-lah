# Implementation status

## M1: local foundation

Implemented: React staff login/dashboard/evidence view; FastAPI session authentication; Argon2id passwords; HttpOnly session cookies; Origin and CSRF checks; local login limiting; current clinic membership checks; database foreign keys preventing cross-clinic links; a first Alembic migration; idempotent clinic/account setup and source polling; explicit upcoming/no-show/overdue-recall detection; leased jobs with stale-lease recovery; synthetic source API; Compose setup/test scripts; locked application dependencies; backend and frontend CI definitions.

The first schema is a deliberate subset of the v2 design. Principal/password fields are together during this local milestone; the full identity-binding, MFA, consent, patient access, messages, imports, agent run/step/delegation, source snapshot and booking evidence tables have not been implemented. Cases remain NEW. No routine case is reported complete, and no staff handoff is fabricated. The worker's events have decision_origin=rule. Model mode is not_connected. Agent role cards are explicitly planned.

The decision validator currently covers Coordinator delegation and escalation, including strict enums, role boundaries and case-version binding. TOOL, WAIT and COMPLETE contracts and full policy/evidence checks belong to M2. The source service has no appointment-write operation and does not yet use a separate source database.

## Access and deployment boundary

This release is for local synthetic development, with the web port bound to 127.0.0.1. Do not expose it to real patients or publicly host it. Staff MFA, distributed rate limits, patient enrolment/OTP, Singpass, retention/encryption of sensitive source data, provider signature checks and full audit policy remain pending. Local HTTP cookies become Secure when the configured origin is HTTPS; this alone does not make the application production-ready.

No Terraform or cloud resources have been created. No organiser API, WhatsApp, SMS, telephone, browser speech, mobile push or calendar integration has been called. Source-owned bookings, reviewed CSV/TXT imports and the patient UI are still pending. Container base tags and CI action tags need reviewed immutable digests/revisions before a deployment release; application package versions are locked now.

## Verification

See [VALIDATION.md](VALIDATION.md) for the recorded 10 September 2026 checks: Docker build/startup, 20 backend tests with no skips including real PostgreSQL concurrency, and the staff browser flows passed locally. GitHub Actions, cloud deployment and live integrations need separate verification. Use [TEAM_START_HERE.md](TEAM_START_HERE.md) to repeat setup and testing on your own computer.
