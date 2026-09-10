# re-mind: setup, automation and team delivery

10 September 2026 | v2.1 | Implementation roadmap; commands labelled planned are not yet delivered

## 1. How we will start

Use VS Code as the shared editor, Codex as the coding assistant, GitHub as the private code repository, Docker Compose as the reproducible local runtime, and the organiser's Claude endpoint as the model inside re-mind. These are separate responsibilities. The user has selected Astra Extra High for development; that does not change the product's runtime-model requirement.

Keep one repository and one documented Windows/PowerShell path for beginners. Docker Desktop runs Linux containers; do not mix Windows and WSL Python dependency environments in one checkout. A teammate on another OS can use the same containerised app and equivalent native Git/editor steps.

No infrastructure, accounts, secrets, code or integrations were created by this document revision. The coding phase will implement and execute the commands below, then replace expected results with tested results.

## 2. Setup checkpoints, in order

Run the [Guide 05 early compatibility checks](re-mind_05_Platform_Alignment.md) alongside bootstrap. The first live model/tool round trip and a minimal organiser-hosted HTTPS deployment belong in the first 48 hours once access is available. They must not wait for a polished dental journey or the final DevOps week. If access is delayed, document that dependency and continue local mocks without claiming platform compatibility is proven.

| Step | Action | Evidence before continuing |
|---|---|---|
| 1 | Install VS Code, Git for Windows, uv and Docker Desktop Linux-container support; install Python/Pylance/Ruff extensions | git, uv and docker version checks work in a new terminal; Docker's hello-world works |
| 2 | Each member creates/uses their own GitHub identity with MFA; lead creates private re-mind repository and invites team | Every member can clone and propose a small reviewed PR without shared credentials |
| 3 | Freeze Python 3.12, PostgreSQL 17 and supported Node LTS; lock dependencies | One reviewed set of lockfiles and pinned base images, with same versions in CI and containers |
| 4 | Bootstrap backend/web/mock source, .env.example, Compose and health endpoints | One local command starts empty infrastructure; readiness waits for migrations |
| 5 | Add Alembic migrations and deterministic synthetic seed profiles | An empty database migrates and seeds; running seed twice creates no duplicates |
| 6 | Implement demo auth and enrol team-controlled test contacts privately | Patient can see only their case; staff role and MFA checks pass; no public registration |
| 7 | Implement one dental journey using deterministic provider/model mocks | Start -> reply -> alternative -> explicit confirmation -> source result -> prep acknowledgement -> evidenced closure |
| 8 | Connect the organiser model adapter and validate actual schema response | One recorded real model call, malformed-response rejection and quota/timeout handling |
| 9 | Integrate one real messaging route, then voice/PWA/push/import mode | Actual provider/device results and fallback behaviour, labelled by live vs simulated mode |
| 10 | Deploy the same release to permitted Lightsail | External HTTPS works; database/worker private; restart resumes a pending case |
| 11 | Run evaluation, security, accessibility and restore checks | Versioned reports include failed cases and denominators; final known limitations recorded |
| 12 | Rehearse all three specialties from a clean seed | Two teammates independently run the guide and the full demonstration |

Official setup references: [VS Code Python](https://code.visualstudio.com/docs/python/python-tutorial), [uv](https://docs.astral.sh/uv/getting-started/installation/), [Docker Desktop Windows](https://docs.docker.com/desktop/setup/install/windows-install/), [GitHub repository creation](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository). Recheck installers/system prerequisites during implementation rather than pasting unverified installation commands.

## 3. Proposed repository layout

```text
re-mind/
  README.md
  AGENTS.md                     # product boundaries and commands for coding assistants
  pyproject.toml / uv.lock / .python-version
  .env.example                  # names only; no live credentials
  compose.yaml
  apps/
    web/                        # React/TypeScript/Vite
      src/patient/              # optional PWA and accessible conversation
      src/staff/                # imports, handoffs, evidence
      src/shared/               # typed API client and UI primitives
      public/                   # manifest and public shell assets only
  src/remind/
    api/                        # auth, patient, staff, imports and webhooks
    domain/                     # follow-up state, evidence and source contracts
    agents/                     # coordinator, engagement, preparation
    runtime/                    # runner, context builder, budgets, detector, worker
    policy/                     # authority, consent, tool and state gates
    adapters/
      model/                    # organiser JSON and test fixture providers
      sources/                  # connected API, reviewed import
      channels/                 # WhatsApp/SMS/telephone/portal/push
      identity/                 # demo/OTP and Singpass staging adapter
    imports/                    # parsers, preview, publish, source freshness
    persistence/                # SQLAlchemy repositories
    observability/              # redacted logs, metrics and evaluation exports
  migrations/                   # Alembic
  services/mock_clinic/          # realistic source API with atomic slot operations
  config/
    specialties/                # dental, myopia, antenatal YAML
    policies/                   # reviewed demo contact/escalation rules
    prompts/                    # versioned role instructions
  contracts/                    # exported JSON schemas / OpenAPI
  fixtures/                     # synthetic only, fixed reference clock
  tests/unit/ tests/integration/ tests/e2e/
  evals/cases/                   # named golden and adversarial scenarios
  infra/terraform/lightsail/
  deploy/                       # proxy config, release and backup scripts
  scripts/                      # dev, seed, checks, deploy, restore
  docs/                         # current design, runbooks and decision log
  .github/workflows/            # checks and gated releases
```

Keep business rules out of UI components and provider adapters. Agent tool handlers call application services; all effects still cross the gateway. Frontend API types are generated from the reviewed OpenAPI schema so Python/TypeScript do not drift. Do not create a new framework or service for each specialty.

## 4. Automation contract to implement

The following are intended user-facing commands. They will only become runnable when the implementation supplies these scripts. Use one documented entry point per operation; scripts print progress, validate prerequisites, propagate non-zero exits and never echo secrets.

```powershell
# Planned commands in the future re-mind checkout
./scripts/dev.ps1 doctor
./scripts/dev.ps1 setup
./scripts/dev.ps1 up
./scripts/dev.ps1 migrate
./scripts/dev.ps1 seed -Profile minimal
./scripts/dev.ps1 test
./scripts/dev.ps1 e2e
./scripts/dev.ps1 evaluate -Mode mock
./scripts/dev.ps1 down
```

`setup` creates local configuration from names-only templates, generates dev secrets and installs locked dependencies. `up` starts bounded containers. `migrate` runs a single migration job, not one migration per API replica. `seed` uses an environment/database allowlist and idempotent fixtures; a destructive reset is a separate explicit command. `test` uses disposable PostgreSQL and fake providers with no live contacts. `evaluate -Mode live` will be an explicit, quota-bounded opt-in once the endpoint is available.

Expected local URLs will be fixed and verified during coding: one frontend origin, /patient and /staff views, same-origin API through the dev proxy, local API docs for developers only. Mobile tests need a reachable trusted HTTPS origin; a phone's localhost refers to the phone, not the laptop. Do not solve microphone/push problems by disabling browser security.

## 5. What DevOps starts now and what waits

| Phase | Required work | Why it belongs there |
|---|---|---|
| First implementation | Git review, locked dependencies, containers, secrets exclusions, schema validation, migrations, auth skeleton, CI checks, test fakes, correlation IDs | These shape the code and prevent incompatible work or secret leaks |
| Integration week | Image builds, Terraform draft/plan, deployment rehearsal, health checks, queue metrics, budget limits, backup/restore scripts | Find hosting/provider problems while there is time to fix them |
| Final week | Release/rollback rehearsal, restore test, access review, dependency/container scans, load checks, full evaluations, runbook and demo freeze | Stabilise and prove the product already works |

No need for every enterprise DevOps tool. Use the smallest set that proves reproducibility, security and recovery. Kubernetes, service mesh, complex GitOps and a multi-environment platform are outside the MVP.

PR CI: locked install; Ruff format/lint; selected static typing; backend unit/integration tests; JSON/OpenAPI schema validation; frontend typecheck/build and relevant UI tests; secret scanning and dependency checks. Add Playwright flows after the first vertical slice. Mocks must fail closed if a test attempts real outbound contact. Untrusted PR jobs do not receive deployment or provider secrets.

Release CI: build versioned container images tagged by commit and record digests; create a dependency inventory; run a smoke suite; produce the deployable release. Use a protected release environment where supported; otherwise document the manual reviewed control. Pin trusted CI actions to reviewed revisions. A green build is not proof that every external integration works.

## 6. Lightsail and Terraform plan

The latest organiser clarification requires platform testing/hosting and inference with approximately USD 100 shared across Lightsail and LLM/API usage. Baseline stays within the permitted shape: one Linux instance, reverse proxy/web, API, worker, PostgreSQL and mock source. Select the instance bundle and region after confirming account permissions and measuring memory needs. The user can fund supplementary personal AWS development, subject to organiser acceptance; this does not increase the team endpoint allowance.

Terraform should describe the **permitted** instance, static IP/attachment and firewall rules if that account allows them. Commit .tf configuration and dependency lock; keep state, plans containing secrets and tfvars outside Git. Prefer short-lived AWS credentials. If GitHub-to-AWS federation/IAM rights are not permitted, a designated owner runs plan/apply locally with organiser-supplied credentials; no assumption that a custom OIDC role can be created.

Do not provision S3 just to host Terraform state if S3 is outside the allowed resources. A single-writer encrypted local state with secure backup is the constrained hackathon fallback; explicitly prevent concurrent applies. If an approved state backend becomes available, migrate under a reviewed procedure. If organisers pre-provision the server or do not give resource API access, record that constraint and automate application deployment onto the supplied host; never represent an unexecuted Terraform plan as provisioned infrastructure.

Keep secrets out of user_data, Terraform values/state and image layers. Bootstrap installs required runtime components only. Inject runtime secrets separately into owner-readable environment/files; keys are distinct for app encryption, HMAC, session and push purposes. A managed secrets service is a future option only if allowed.

Networking: public HTTPS 443; HTTP 80 only as needed for redirect/certificate issuance; SSH restricted to authorised administrator IPs. Check both IPv4 and IPv6 rules. Lightsail's public firewall does not filter every private-network path, so also restrict host/container bindings. PostgreSQL has no public port; mock source is internal; only necessary API/webhook routes are exposed. [AWS firewall behaviour](https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-firewall-and-port-mappings-in-amazon-lightsail.html).

Deployment flow: inspect plan -> provision allowed resources -> configure DNS/HTTPS -> transfer/pull immutable release -> inject secrets -> take pre-migration backup -> migrate once -> start/update services -> smoke test -> record release. Domain/DNS access is an early dependency for Singpass redirects, callbacks and mobile HTTPS. Do not wait until demo day.

A new image must not overwrite the working release before health checks. Keep the previous image digest/config available. Prefer backward-compatible schema additions; an old app image may not work after a destructive migration, so rollback must specify schema compatibility or restore. A failed migration blocks rollout and retains evidence.

Backup is an encrypted logical PostgreSQL backup plus required uploads/config metadata, copied off the instance to a permitted secure location. Keep encryption keys separate. If snapshots are allowed, they supplement rather than replace an application-consistent restore test. Restore into an isolated environment, reapply revocations/deletion records, run invariant checks and record recovery time. Use synthetic data only.

Budget control: daily combined hosting/model usage review, bounded prompt context and model decisions, global outbound pause and removal of unused authorised resources. Alerts are not automatically a hard spending cap. Keep external messaging/voice costs visible separately unless coverage is confirmed. The organiser model key is not an AWS console credential. Personal-account spending and organiser competition acceptance are separate matters; credits do not automatically transfer.

Account portability: keep separate Terraform state and environment configuration per account, check the expected account ID before any apply, and deploy identical container digests. Create fresh organiser resources; seed synthetic fixtures or perform an encrypted logical database/upload restore. Inject destination secrets separately and preserve required data-encryption keys through an explicit protected migration. Keep the old worker and scheduler paused during a stateful cutover so queued reminders cannot be sent twice. Verify DNS/HTTPS, provider callbacks, login redirects, sessions and push subscriptions before enabling outreach. The detailed plan and acceptance evidence are in Guide 05; no migration has been executed.

## 7. Team of four

| Owner | Primary responsibility | First reviewable delivery |
|---|---|---|
| 1 - technical lead | Agent contracts/loops, coordinator, gateway, model adapter, integration ownership | Typed AgentStep, failed-tool adaptation and evidence-backed closure against mocks |
| 2 - data/backend | PostgreSQL/migrations, source API mocks, import review/publish, idempotency and leases | Empty-database bootstrap plus replay-safe detector/import and atomic mock booking |
| 3 - experience/channels | React patient/staff views, messaging/voice/push adapters, accessibility and calendar | One patient reply reaches the same case from portal and provider; staff can claim a task |
| 4 - platform/quality | CI, Compose/Terraform/release, test fixtures/evaluations, auth/Singpass access spike with lead review | Reproducible startup, passing access tests and working provider/auth spike report |

These are workstream owners, not isolated silos. Lead pairs with owner 4 on authentication and owner 3 on channel security; owner 2 reviews source/evidence integrity. All members learn the full demo. Do not assign one beginner to all security and deployment without review.

## 8. Schedule against the actual slide dates

The shortlisting window is 7-28 September 2026. This redesign is dated 10 September, so the plan must fit the remaining window rather than restarting a fresh three weeks. Exact submission time and the claimed 30-minute slot still need coordinator confirmation.

| Window | Usable increment | Exit evidence |
|---|---|---|
| 10-13 September | Freeze current contracts, scaffold/CI/auth, migrate/seed, one dental path using mocks; actual model/tool round trip, provider/auth access spikes and minimal organiser HTTPS deployment | One teammate runs clean startup; adaptive tool loop and tenant denial pass; largest realistic prompt and destination deployment checked, or exact access blockers recorded |
| 14-20 September | Full organiser integration, provider outreach/voice; PWA text/voice/push/calendar; import preview/publish; myopia and antenatal; deployment/restore rehearsal | End-to-end journeys work; no-API change request becomes an owned handoff; actual device/provider results and destination restart evidence recorded |
| 21-27 September | Stabilise; complete DevOps automation, all evaluations, security/accessibility tests, recovery/load checks, final demo | Frozen release, measured report, tested run guide, backup/restore and rehearsal |
| 28 September | Submit within confirmed deadline | Submitted artefacts match the tagged tested release |

Planning assumption: four members can contribute roughly three focused hours on most remaining days, with overlap for integration/review. This is a capacity assumption, not a guaranteed estimate. The core slice comes first. External-access tasks run early; cut OCR, full calendar sync and other stretch items before weakening identity checks, evidence or the primary journey. If a committed channel cannot be made reliable, explicitly revise the demo promise rather than conceal a simulation.

## 9. Testing and evaluation

Separate deterministic engineering tests from model-quality evaluation. Unit tests validate policy/date/state rules. PostgreSQL integration tests validate concurrency and persistence. Playwright tests exercise patient/staff flows. Controlled real-device/provider tests validate behaviour a browser emulator cannot prove.

Retain the planned **60 evaluation scenarios**, organised as 20 routine, 20 edge/integration and 20 safety/adversarial. Allocate 20 to dental, 20 to myopia and 20 to antenatal; each specialty includes all three categories. Suggested category splits are dental 7/7/6, myopia 7/6/7 and antenatal 6/7/7. Use English and reviewed Mandarin examples within that set. Additional infrastructure/unit tests are not falsely counted as independent clinical validation.

Each case declares: initial source/identity state, channel/event sequence, expected allowed/blocked actions, required evidence, timeout/failure injections, expected final outcome and forbidden effects. Pin model/prompt/schema/policy/fixture versions. CI mock runs validate deterministic behaviour; a bounded live-model run validates interpretation/tool choice. Label both separately. Do not hard-code the agent to the demonstration inputs and report that as live general reasoning.

Required cases include slot conflicts, source timeout with unknown result, no reply, shared phone, wrong patient, unauthorised caregiver, tenant mismatch, source cancellation, import replay/staleness/invalid notes, prompt injection, malformed model JSON, clinical question, staff not accepting, preference revocation, PWA/WhatsApp duplicate reply, expired session, denied push/microphone, old calendar export and worker restart.

| Metric | Definition and reporting |
|---|---|
| Routine completion | Eligible routine cases with verified intended outcome / eligible routine cases attempted; report import-mode and API-mode separately |
| Agent action quality | Expected permitted next action and correct adaptation after observed result / evaluated decisions; show errors and example traces |
| Safety invariants | Count unauthorised reads/writes, invented instructions, unconfirmed bookings and duplicate effects; target zero in tested set, never universal safety claims |
| Escalation handling | Expected escalations created and accepted within configured demo targets / expected escalations; report false escalations separately |
| Efficiency | Human active minutes and manual touches per identical scripted case compared with a measured staff baseline; show sample size |
| Accessibility | Completion and user errors by tested device/language/channel; disclose unsupported speech/push modes |
| Reliability | Resume success, duplicate-effect count, queue age and p50/p95 processing latency under stated workload |
| Usage | Actual model calls/tokens if supplied; provider sends/calls; cost only with verified rates; unknown values stay unknown |

Proposed release bar: all deterministic access/consent/idempotency tests pass, all demo-critical journeys complete twice from clean data, at least 90% of eligible routine live evaluation cases reach the expected outcome, and zero observed safety-invariant violations in the test set. Report actual results; missing the target requires fixing or stating the limitation, not changing the denominator quietly.

Local load target: seed 1,000 synthetic candidates, simulate 20 concurrent inbound events and compare one vs two workers with mocked external services; verify no duplicate business effect. This is a test specification, not proven capacity. Do not use organiser model credits for an uncontrolled load test. Release report records hardware, dataset, provider mode, latency and limitations.

## 10. Thirty-minute presentation proposal

Use this schedule only if the coordinator confirms the available slot; otherwise shorten it without changing the product scope.

| Minutes | Content |
|---|---|
| 0-3 | Dental problem, manual baseline, senior inclusion and completion definition |
| 3-7 | Three agents, persistent state, policy/tool boundary and allowed platform |
| 7-12 | Dental live path: flexible-date request, slot conflict/adaptation, explicit confirmation and verified source booking |
| 12-16 | Myopia: patient PWA voice/text, exact approved instruction, permission-based push and calendar export |
| 16-20 | Antenatal: routine reminder then a synthetic clinical concern; automation pauses and named staff accepts |
| 20-23 | Clinic without APIs: upload/review, bounded follow-up and date-change handoff; show authentication/privacy controls |
| 23-27 | Evaluation, failure recovery, CI/deployment evidence and measured staff effort |
| 27-30 | Final pitch, limitations and questions if Q&A is included |

A separate short branch shows no response -> allowed voice fallback. Keep a clearly labelled recording of a real successful provider run if venue connectivity fails; do not silently replace the live model with canned output. Keep test-phone permission, fresh seed data and a supported push device ready.

## 11. Final delivery package in the coding phase

Deliver source code and lockfiles; .env.example; migrations and synthetic seeds; local setup/run/troubleshooting guide; actual organiser adapter with secrets excluded; CI and permitted Terraform/deployment scripts; backup/restore/rollback runbook; versioned evaluation fixtures and measured results; source/privacy/identity assumptions; three demo scripts; and a tagged reproducible release. The team should be able to start from an empty database and reproduce the demonstrated outcome without undocumented manual edits.
