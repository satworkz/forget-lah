# forget-lah agent runtime validation

## Patient confirmation simulator — 14 September 2026

- **191 automated tests passed, zero skips**, including twelve PostgreSQL checks, using the Compose test image. Two existing third-party deprecation warnings remain. Ruff lint/format passed for 74 Python files; TypeScript/Vite and Docker builds passed.
- **Live direct Claude + browser check passed:** Alex review `f852a893-6fe0-4c68-8a07-9bcd6146e55c`, case `2fb36ad6-7298-4670-ad12-1fb7466a9b11`, completed in **13 steps / 11 model attempts**, with no errors and no handoff. Reply: “Yes, I confirm the attendance, What should I bring?” The gateway returned GREEN with `SOURCE_RECEIPT_AND_SIMULATED_DELIVERY_VERIFIED`. Reported usage: 24,017 input and 996 output tokens for this successful review.
- The browser showed the outgoing reminder, entered reply, acknowledgement with the exact approved spectacles note, and completed state. The separate clinic simulator displayed the confirmation while the appointment stayed scheduled. Case Journey showed both outgoing messages and the evidence-backed completion. The final journey captions distinguish simulated completion from staff-owned handoff completion.
- Added persisted outgoing reminders and acknowledgements, a separate source-owned confirmation receipt, and gateway-checked simulated completion. Both specialists contribute evidence. The source stays scheduled; no real attendance, booking or patient delivery is claimed.
- Tests cover the three specialties; plain and preparation-question confirmations; alternate confirmation wording; negative/conditional/ambiguous replies; prerequisite and changed-source blocks; wrong identity/key/version; forged completion; retries without duplicates; late receipts after pause; fresh-review history; and concurrent PostgreSQL confirmation requests.
- Live testing exposed an oversized native Claude request and an unsupported schema array bound. Prompt duplication was reduced; both provider request envelopes are checked against the existing 8,000-byte default. Native schema conversion maps `minItems > 1` to 1 because [Claude only supports 0 or 1](https://platform.claude.com/docs/en/build-with-claude/structured-outputs); local decision validation still requires exactly two evidence IDs and the gateway verifies their provenance. No budget or step limit was increased.
- Application migration `0004` and source migration `sim0002` applied successfully. Builds and Ruff lint/format passed. Earlier reviews retain their recorded outcomes; a fresh simulator review uses the new capability.
- These checks cover synthetic local data. They do not verify real channels, clinical triage, production patient authentication, the organiser's live endpoint or remote GitHub Actions. Changes remain local and uncommitted.

## Unsupported clinical escalation correction — 14 September 2026

- **167 automated tests passed, zero skips**, including eleven PostgreSQL checks, using the Compose test image. New cases cover routine confirmation and confirmation/preparation replies across dental, myopia and antenatal; model response schemas exclude the clinical reason for all three agents; a model that ignores the constraint is denied by the gateway. The staff clinical-flag rule still produces RED without a model call and retains RED after named acceptance.
- Journey coverage verifies that a correction is a separate audit event, preserves the original proposal/verdict and original handoff classification, shows the current classification, and belongs only to its selected review.
- Ruff lint/format (68 Python files), TypeScript/Vite and Docker builds passed. The local app was rebuilt and restarted without resetting cases or changing source records.
- Alex's existing synthetic confirmation was corrected from RED/`CLINICAL_REVIEW_REQUIRED` to AMBER/`CAPABILITY_UNAVAILABLE` in a scoped transaction after checking the saved reply, instructions, prerequisites, disabled write/contact capabilities, case version, current run and absence of staff clinical flags. The handoff remains unaccepted. The original model decision and policy remain unchanged; the journey includes an explicit maintenance correction.
- One paid, budgeted **direct Anthropic replay** of the saved final Coordinator context returned `ESCALATE / CAPABILITY_UNAVAILABLE` (2,201 reported input tokens, 65 output tokens). This checked a single model response; no action was executed and it was not inserted into the original case history. It does not establish general model accuracy or clinical triage quality.
- Two existing third-party test-client deprecation warnings remain. No real patient contact, attendance/booking write, automatic clinical triage, organiser endpoint or remote GitHub Actions verification was added. Changes remain local and uncommitted.

## Dynamic clinic simulator — 13 September 2026

- **156 automated tests passed, zero skips**, including eleven PostgreSQL checks, using the Compose test image. New tests cover isolated source migrations/seed preservation, edited evidence through the existing typed adapter, note approval filtering, timezone conversion, available-slot filtering, duplicate/stale requests, invalid inputs, authenticated editing, detection/deduplication and reset with custom episodes. Competing PostgreSQL editors produce one success and one conflict; migration metadata matches the simulator models.
- Ruff lint/format passed (68 Python files). TypeScript/Vite and Docker builds passed. Bootstrap created the isolated source database and `sim0001` schema; the application schema remains `0003` and existing history was preserved.
- Authenticated browser testing saved a slot and a cancelled patient episode/note through the combined page, reloaded them after restarting the mock service, and verified the approved note and availability through the real HTTP source adapter. The cancelled test episode did not create an application case or trigger paid inference. Temporary test records and the disposable local test login were removed after verification.
- Live database checks confirmed the application user cannot connect to the source database, and the simulator role cannot read application case tables. PostgreSQL, API and source service health checks passed; worker/web are running; bootstrap exited successfully.
- Model tests use test doubles. No real patient messages or appointment writes were tested or enabled. Two existing third-party test-client deprecation warnings remain. These changes are local and uncommitted; remote GitHub Actions is not verified.

## Automatic review startup and initial source read — 13 September 2026

- **146 automated tests passed, zero skips**, including ten PostgreSQL checks, using `./scripts/dev.ps1 test`. New coverage verifies automatic creation without browser requests, atomic foundation completion/run registration, concurrent starters, ready-case catch-up, no restarts of existing reviews, service identity isolation/revocation, blocked service login/sessions, missing configuration and rule-tool lease recovery.
- Existing workflow, provider, gateway, source-failure, pause/retry and shared-budget tests pass. Budget tests now race at an actual model step, after the rule-selected initial read. Model/provider tests use test doubles; they do not consume paid inference.
- Ruff lint/format passed (59 Python files); TypeScript/Vite production build passed. The local Compose app rebuilt and started successfully, with automatic startup enabled and the clinic service identity provisioned. No schema migration or data reset was needed.
- Two previously unreviewed local cases automatically reached waiting after deployment; the existing completed review was preserved. Local catch-up uses the configured provider and its existing budget. The served frontend contains the automatic-start/rule-read explanations and neither start button. Browser navigation reached the sign-in page; the protected dashboard was not visually inspected in this verification session.
- The two existing third-party test-client deprecation warnings remain. Remote GitHub Actions has not been verified for these uncommitted changes.

## Deterministic initial demo wait — 12 September 2026

- **137 automated tests passed, zero skips**, including the nine PostgreSQL checks, using `./scripts/dev.ps1 test`. Eight added cases cover all three provider modes with test doubles, exhausted model budgets, reply resumption, failed/stale source evidence, capability checks and authority revocation.
- Initial wait is stored as an application-rule step with zero attempts. The standard test flow uses two model-adapter decisions (Coordinator read and delegation), then the worker records the wait. Resumed mixed replies still use both specialists and reach a staff handoff.
- Ruff lint/format and TypeScript/Vite build passed. Docker rebuilt and restarted the app successfully. The served frontend contains the new rule explanation and zero-call label. No paid inference was needed for validation; provider-mode tests use a recording test double, not live Claude.
- Existing historical reviews were preserved. This change does not enable patient outreach, alter the manual start control or add a full event journal. The two existing third-party deprecation warnings remain; remote GitHub Actions has not been verified.

## Optional demo reset — 12 September 2026

- **129 automated tests passed, zero skips**, including nine real PostgreSQL checks. Fourteen added checks cover reset defaults, confirmation, flag/session/clinic/Origin/CSRF enforcement, preserved credentials/budget/other-clinic data, source failure, rollback, stale requests, unexpected records, active review rejection, late worker results and competing PostgreSQL resets.
- Ruff lint/format and the TypeScript/Vite Docker build passed. The application rebuilt successfully; the private local flag is enabled while the committed default remains off. No migration was introduced.
- Browser verification covered the visible **Reset demo data** button, the disabled action before confirmation, enabling it by typing `RESET`, and Cancel returning to the unchanged dashboard. Actual deletion/recreation was exercised by automated API/database tests in isolated test data; the current laptop's demo was not reset again during the UI check.
- No Claude calls were required. The two existing third-party test-client deprecation warnings remain. Remote GitHub Actions has not been verified for these uncommitted changes.

See [DEMO_RESET.md](DEMO_RESET.md) for the enable/disable flag and demonstration steps.

## Case Journey page — 12 September 2026

- **115 automated tests passed, zero skips**, including eight real PostgreSQL checks, using `./scripts/dev.ps1 test` after the final backend changes.
- Four new journey tests cover new/legacy detection evidence, chronological staff/decision/handoff records, model-context/proposal/policy/result separation, previous reviews, blocked tools, clinic isolation and unauthenticated access. Repeated reads do not create steps or consume model calls.
- Ruff lint and formatting passed (53 Python files). TypeScript/Vite production build passed in Docker. The Compose app rebuilt and started successfully with existing local cases preserved; no new migration was needed.
- Browser checks passed for dashboard navigation, loading an existing completed dental review, separate handoff creation and acceptance, individual and bulk message expansion, filtering, earlier simulation labels while the app is in direct-Claude mode, refresh and direct case-route reload. Desktop screenshots were inspected; expanded input/output panels had no page-level horizontal overflow at the tested default viewport. No separate mobile browser check was performed.
- This page reads persisted application evidence. No paid Claude calls were made for these checks. Historical missing source payloads, exact prompts and individual HTTP retry responses remain explicitly unavailable; activities within a decision show logical order rather than individual network timestamps.
- The two existing third-party test-client deprecation warnings remain. These results describe the local working tree; they do not establish remote GitHub Actions success.

See [CASE_JOURNEY.md](CASE_JOURNEY.md) to use the page.

## Live direct Claude verification — 11 September 2026

**111 automated tests passed with zero skips**, including eight PostgreSQL cases. Ruff lint/format, TypeScript/Vite and Docker web build passed. The fresh live dental review completed 13 model decisions with no retries or rejected steps, collected both specialists' evidence and required named staff acceptance. See [LIVE_CLAUDE_VALIDATION.md](LIVE_CLAUDE_VALIDATION.md) for the run ID, usage, reproduction steps, earlier failures and limits.

The entries below are historical snapshots taken earlier in development. Statements about no live calls or older test counts apply to those snapshots only.


## Direct Claude addition — 11 September 2026

- Docker suite: **102 tests passed, zero skipped**, including eight real PostgreSQL checks. This includes forward migration from populated `0002`, unchanged existing run mode/usage counter, the new `anthropic` mode, atomic daily budgets and pacing for both live providers.
- Direct Messages API wire/response tests cover separate credentials, workspace header, typed proposals, limits, timeouts, redacted HTTP failures, refusal/truncation and unexpected content. These tests use HTTP test doubles, not paid inference.
- The one-call connection check is tested for request binding, budget reservation and no fallback/retry on denied access.
- Ruff lint and formatting passed (50 Python files). TypeScript/Vite and Docker frontend builds passed. The local Compose application rebuilt successfully and the database is at `0003`; three synthetic cases and four completed reviews are present.
- The installed connection-check command returned `SIMULATION_SELECTED` in the current mock configuration, as expected. No paid provider connection was attempted. Live Claude behavior and organiser compatibility still require configured private credentials and the journey/evaluation checks in [CLAUDE_SETUP.md](CLAUDE_SETUP.md).
- Earlier recorded browser demonstrations below concern the existing M2a simulation; they do not establish direct-Claude model accuracy. The two existing third-party deprecation warnings remain.

Latest recorded local verification: **11 September 2026**, M2a v0.2.0. These results describe the local working tree, not a pushed commit, remote CI run or production deployment.

| Check | Recorded result |
| --- | --- |
| Backend suite in Docker | **74 passed, 0 skipped**, with PostgreSQL 17 available; model HTTP responses simulated, no organiser calls |
| Real PostgreSQL checks | Five passed: foundation job claiming, agent-run claiming, populated M1 → M2a migration/schema alignment, concurrent daily-call reservations and shared pacing |
| Workflow tests | Dental, myopia and antenatal runs reach a durable wait, delegate specialists and require named staff acceptance before automation completion |
| Reliability and policy | Stale leases/results, crash recovery of saved tool proposals, permission revocation before/after reads, idempotency/body binding, pause/retry, source outages, budgets and invalid-model responses covered |
| Gateway adapter | JSON wire format, request/response limits, malformed envelopes, status errors, no redirects, safe errors and token metadata verified with HTTP test doubles |
| Python quality | Ruff lint and formatting checks passed |
| Frontend | TypeScript check and Vite production build passed; final Docker web build passed |
| Schema export | Exported JSON Schema matches the runtime decision contract |
| Local upgrade | Migration `0002` applied; original three cases and six foundation audit events preserved; existing credentials preserved |
| Browser — dental | Both specialists returned source evidence; alternative-date finding visible; handoff remained unowned until staff accepted; automation then completed |
| Browser — myopia | Synthetic spectacles note and prerequisite read visible; unverified attendance intent returned; named handoff accepted and automation completed |
| Browser — antenatal | Explicit staff concern generated rule-origin RED escalation; named acceptance completed automation while retaining RED and an open staff task |
| Browser — recovery/layout | Waiting checkpoint survived worker restart and page reload; session persisted; narrow-screen horizontal overflow corrected and checked |
| Docker startup | Database, API and mock clinic healthy; worker/web running; bootstrap exited 0; localhost-only web binding |
| Secrets | Existing private configuration preserved, default mock mode retained, no team key added; generated files remain ignored |

Open **http://localhost:8080** and follow [AGENT_RUNTIME.md](AGENT_RUNTIME.md). The tested local cases now contain completed demonstration runs; select **Start another demo run** to repeat a flow. Earlier runs remain in the database; the screen displays the latest run.

Reproduce the full backend suite with `./scripts/dev.ps1 test`. Local Python-only tests explicitly skip the five PostgreSQL checks when TEST_DATABASE_URL is absent; this is not equivalent to the complete Docker result. The default Windows pytest temporary folder on this machine had an access restriction; local debugging used a fresh project-cache temporary directory. The team's Docker test route avoids that host-folder issue.

**Not verified:** live organiser Claude access, real patient identity/contact, clinical detection or advice, language quality, booking writes, external providers, GitHub Actions or cloud deployment. The private team API URL/key are still required for live inference verification. This release makes no production-readiness or clinical-safety claim.

These 74 engineering checks are separate from the planned **60 hackathon evaluation scenarios**. Simulation proves application control flow and recovery, not model accuracy, inclusion outcomes or staff time savings. Real-model evaluation remains pending.

Two third-party test-client deprecation warnings (Starlette/httpx and an AnyIO alias) were present without failing tests. No dependency upgrades were introduced to suppress them.
