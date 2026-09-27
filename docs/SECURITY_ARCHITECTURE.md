# Security by Architecture

> Control reference with dated deployment history. Earlier statements that AWS was unchanged are historical; later deployment records are in [AWS_DEMO](AWS_DEMO.md) and [Implementation status](IMPLEMENTATION_STATUS.md). Controls and production limitations remain explicit below.

**Local deployment completed, 22 September 2026:** migration `0016` is active locally; API, worker and web use the verified images. Both databases were backed up and all pre-existing column values across 33 tables matched before migration and after API/web restart, before resuming the worker. Readiness, staff authentication, masked summaries, audit access and runtime table grants passed. AWS remains on its existing release. This update supersedes the implementation-time deployment status below.

Decision: retain the existing follow-up architecture and add deterministic access and evidence controls. This is hackathon/demo hardening, not a certification or a claim of production readiness.

## Implemented controls

| Boundary | Implemented behavior |
| --- | --- |
| Least privilege / RBAC | Each active clinic membership has a role. `staff` and `admin` may perform scoped staff actions; `auditor` may read authorized detail/audit views but cannot mutate; `viewer` may read masked case summaries, session and system metadata only. Unknown roles fail closed. There is no role-management UI. Existing memberships migrate to `staff` to preserve established access. |
| Tenant isolation | Authorization filters clinic memberships by the permission needed for each request. The resulting clinic set scopes case, Bridge batch, slot, appointment-change, notification-retry and audit access. A staff role in one clinic never upgrades viewer access in another. Missing and out-of-scope case/batch identifiers both return 404. Database composite relationships bind case/run/patient evidence. These are application checks and relational constraints, not PostgreSQL row-level security. |
| Durable authorization | The worker rechecks active identity, clinic membership and write-capable role before policy/tool execution. Revoking staff write authority affects queued work as well as HTTP requests. The existing demo automation identity cannot log in and remains limited to the demo clinic. |
| Minimum necessary data | Clinic-scoped staff, admin and auditor case summaries show full patient names for identification; summary-only viewers retain name masking, evaluated per clinic membership. Case summaries mask source references; test-phone summaries and Bridge intake lists mask phone numbers. Authorized Bridge review lists show patient names, and expanded review views retain the evidence needed for staff approval. Masking changes presentation/API summaries, not stored patient records or phone bindings. |
| Role-scoped model context | Observations are bound to one clinic/case/run. Structured patient/clinic identifiers, contact details and transport credentials are recursively removed. Coordinator and Preparation do not receive available-slot arrays; Engagement receives a bounded preview. Tool permissions and evidence requirements remain role-specific. Scoped patient replies and approved clinical/task evidence remain available for the established reasoning behavior. Free-text replies and notes can themselves contain personal data; this is minimization, not anonymization. |
| Intake model context | Mapping receives at most ten sampled rows; normalization receives bounded ten-row chunks from the current authorized batch. Previous profiles contribute only field/column mapping, not old rationale or patient examples. Intake necessarily processes the uploaded patient data; it has no database tools or independent authority to approve imports. |
| Policy-gated actions | Model output is a typed proposal. Deterministic identity, consent, case version, source version, instruction and source-capability checks gate tools. The model has no unrestricted SQL, database credentials or arbitrary database-access tool. |
| Source ownership | API-backed clinics retain their external appointment system as source of truth. Bridge clinics own approved follow-up lifecycle state and receipts in Forget-lah PostgreSQL. Bridge never uses or writes mock-clinic tables; staff-supplied options and approved evidence remain required. |
| Human escalation | RED/AMBER escalation, named staff acceptance, owner-only resolution and doctor-instruction gates remain in force. This change adds no clinical advice or autonomous permission overrides. |
| Auditability | The staff case Security & Audit panel combines saved application events, agent policy decisions/tool results, staff events, appointment-change receipts, notification outcomes and Bridge upload provenance. New append-only application events preserve Bridge review changes, approval actors, option changes and notification retry requests. The panel shows actor, action, source, timestamp, decision and available evidence/old-new values. It reads up to 200 entries per source; older records stay stored. |
| Security events | Denied/missing-resource access, invalid/oversized uploads and authentication failures create deterministic events. Three comparable denials within five minutes flag repeated activity. Log lines contain only route templates, status and repetition, never bodies, raw paths/query strings, cookies, passwords or phone numbers. Clinic-scoped events can be inspected at `/api/security/events`; unattributed or multi-clinic attempts remain stored without being assigned to a victim clinic. This is not a SIEM or an alerting service. |
| Session / browser | Existing hashed session tokens, Argon2 password hashes, expiry, origin checks, CSRF validation and strict SameSite cookies remain. HTTPS origins enable Secure cookies. Responses carry no-store and browser security headers. Validation failures no longer echo submitted input. |
| Secrets / infrastructure | Credentials remain backend environment settings wrapped as secrets; errors use bounded codes. Credentials are never sent as agent observations or frontend configuration. Compose publishes only the web entry point; PostgreSQL, API, worker and mock-clinic ports are private. No user secret was rotated by this change. |
| TLS assumptions | Cloud HTTPS terminates at the existing Caddy proxy. Plain HTTP loopback is for local development. Internal single-host container traffic is not separately encrypted; end-to-end internal TLS is not claimed. Cloud firewall, certificate operation and access administration remain deployment responsibilities. |

## Secure Bridge intake

Only CSV, TSV and XLSX are accepted. Limits are 1.5 MB decoded content, 200 data rows, 40 columns, and a 2,110,000-byte HTTP request envelope. The envelope limit counts streamed bytes, including requests without Content-Length. Excess rows/columns are rejected rather than silently imported partially.

XLSX is read as ZIP/XML data entirely in memory, without Excel, shell execution, extracting files or fetching external resources. Workbooks are limited to 200 ZIP members and 8 MB total expanded content. Duplicate ZIP parts, encrypted ZIP entries, macro parts, external-link parts, XML DTD/entities and formula cells are rejected. Legacy/encrypted Office containers and malformed workbooks receive a generic safe rejection. Staff should export literal values before uploading formula workbooks. CSV/TSV formula-looking strings remain literal untrusted cell text: they are never evaluated, and no spreadsheet export is introduced.

Original filename metadata, uploader, timestamp and SHA-256 checksum are retained with the existing batch. Raw rows, source quotes, staff review changes and approval/evidence gates remain available. No uploaded file is executed or persisted using a supplied filesystem path. Existing previously accepted imports are preserved; the stronger parser applies to new uploads.

## Audit limits and administration

Historical records are not rewritten to invent missing actors, timestamps or old values. Notification delivery entries show the saved delivery outcome rather than a fabricated history of provider transitions. The current database role can update/delete application tables: this is not a cryptographically tamper-evident or independently immutable audit store. There is no live security-alert dashboard, malware scanner, retention job or new user-management feature.

Role assignment is an explicit administrator database operation against a verified principal/clinic membership. Supported roles are `staff`, `admin`, `auditor`, and `viewer`. Assign the lowest role appropriate to the staff member, retain the clinic scope, and verify access with a separate session. The migration preserves existing staff permissions and does not revoke or reissue sessions.

## Future Production Hardening — NOT YET IMPLEMENTED

The following are future work, not controls delivered by this pass:

- AWS Secrets Manager or SSM Parameter Store, managed secret access and rotation procedures.
- Verified encryption at rest for databases and backups, KMS key ownership, rotation and recovery controls.
- MFA, stronger session controls, session inventory/revocation and workforce identity lifecycle.
- WAF and shared/distributed rate limiting beyond the existing local login limiter.
- Centralized monitoring, security alerts, incident triage and durable security-log retention.
- Retention/deletion policies and verified deletion across operational data, logs and backups.
- Malware/content scanning and stronger upload quarantine where appropriate.
- Secure backup/restore procedures, access separation and regular recovery exercises.
- Incident response, breach assessment and notification procedures.
- Automated vulnerability/dependency scanning, remediation ownership and penetration testing.
- Singapore PDPA and healthcare operational controls requiring organizational/process support: accountability, authorized purposes, access reviews, vendor/data-transfer assessments, staff training, patient request handling and documented incident responsibilities. Implementing software controls alone does not establish compliance.

## Migration and deployment

Migration `0016_security_hardening.py` adds `clinic_membership.role` with a `staff` default and the `security_event` table/indexes. It changes no appointment, case, import, conversation, pending message, binding or mock-clinic table. Readiness now requires application head `0016`; mock-clinic head remains `sim0004`.

Back up the application database, apply the additive migration using the existing owner/bootstrap procedure, verify the runtime role can access the new table through the existing default grants, and deploy API, worker and web from the same revision. Do not reset data, rotate secrets, replay historical cases or send test messages as part of deployment. Existing local/AWS services are not deployed by this implementation task. Running-container port mappings were inspected locally and over the existing pinned SSH connection to the AWS demo: PostgreSQL has no published host port in either environment; cloud web publishes 80/443. Recheck exposure when deploying.

Validation (22 September): the broad Docker/PostgreSQL run passed **624 tests, 14 expected skips**, with two existing dependency deprecation warnings. The skips are twelve paid live-model opt-ins and two SQLite variants of PostgreSQL concurrency checks. The final focused Docker suite passed **63 tests**, covering security, audit evidence and Bridge ingestion after the last parser/provenance-bound refinements. The broader PostgreSQL/security/Bridge group passed **86 tests, one expected skip**. Counts overlap. Ruff, formatting (150 Python files) and the final Docker frontend build passed. The masked list and on-demand audit/evidence panel were visually checked against an isolated synthetic database. Tests use fake source/model responses and consume no paid model calls. No deployment, data reset, secret rotation or patient-message replay was performed.
