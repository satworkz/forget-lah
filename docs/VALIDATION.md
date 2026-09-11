# forget-lah agent runtime validation

## Latest: live direct Claude verification — 11 September 2026

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
