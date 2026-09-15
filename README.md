# forget-lah

Patient follow-up with a clear next step. NUS-ISS Show Me Your Agents hackathon.

**Current release: 0.2.0, local agent runtime (M2a). Synthetic records only.** The Coordinator now delegates to Engagement and Preparation, reads source evidence, waits for a fictional reply and reaches an owned staff handoff. Decisions are explicitly simulated by default. Direct Anthropic inference is connected and has been exercised with synthetic dental reviews. The organiser adapter still needs its private endpoint verification. See [live validation](docs/LIVE_CLAUDE_VALIDATION.md) for measured outcomes and limitations. No patient messages or appointment writes are enabled. See [implementation status](docs/IMPLEMENTATION_STATUS.md).

To connect your own Claude account, start with [Claude setup](docs/CLAUDE_SETUP.md). For the existing demo, start with [Run and understand the agents](docs/AGENT_RUNTIME.md) for the new buttons, three demo flows and technical explanation. Use the [team quick-start guide](docs/TEAM_START_HERE.md) for installing the foundation on a new computer, or the [documentation index](docs/README.md) for other references.

## First run on Windows

**Using Ubuntu?** Follow [Ubuntu quick start](docs/UBUNTU_QUICK_START.md). The companion `scripts/dev.sh` supports setup, build, start and local container deployment. Windows commands below are unchanged.

Open this project folder in VS Code. Open Terminal > New Terminal and use PowerShell. Docker Desktop must be running Linux containers.

```powershell
./scripts/dev.ps1 doctor
./scripts/dev.ps1 setup
./scripts/dev.ps1 up
```

`setup` creates a private `.env` with random passwords. Open that file locally and use DEMO_STAFF_EMAIL and DEMO_STAFF_PASSWORD to sign in. Never commit or share `.env`. Existing setup credentials are preserved if you run setup again.

Open **http://localhost:8080**. The first build downloads images and dependencies. The worker detects cases and automatically queues a review when foundation processing finishes; no start button or open browser is needed. Open a patient's agent review to watch it progress and follow [the demonstration steps](docs/AGENT_RUNTIME.md#2-try-the-three-demonstration-flows). Existing `.env` credentials and database records survive the automatic migrations through `0003`.

```powershell
./scripts/dev.ps1 status
./scripts/dev.ps1 logs
./scripts/dev.ps1 test
./scripts/dev.ps1 down
```

`down` preserves the database volume. Do not add `--volumes` unless you intentionally want to erase the local demonstration database. Changing database passwords in `.env` does not change an existing database volume's passwords.

## What runs

Browser → Caddy/React → FastAPI → PostgreSQL. The worker detects follow-up cases, resumes agent runs, calls the configured model adapter and dispatches allowlisted reads through the policy gateway. Three logical agent roles share that worker. Bootstrap applies Alembic migrations and seeds the synthetic clinic/staff login before startup. PostgreSQL has no published port; the web app binds to local loopback only.

The mock clinic is a database-backed simulator. Open **Clinic simulator** in the sidebar to edit schedules and notes, add slots or create fresh synthetic episodes. The existing PostgreSQL server hosts its isolated database/user; forget-lah continues to read the clinic APIs. Dates are seeded once and edits survive restarts. Follow the [simulator guide](docs/CLINIC_SIMULATOR.md). No provider key is required in default simulation mode. Optional organiser mode is described in [AGENT_RUNTIME.md](docs/AGENT_RUNTIME.md#6-organiser-claude-configuration).

## Development without rebuilding containers

Docker is the standard team path. Developers may additionally install Python 3.12, uv 0.12.12, Node 24 and pnpm 11.19.0.

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web build
```

Python tests use temporary SQLite databases with the actual Alembic migrations. Eleven PostgreSQL checks cover job/run claiming, migration preservation, schema alignment, atomic live-call budgets, shared pacing, competing resets/automatic starters and conflicting simulator edits. They run in Compose and GitHub Actions; without TEST_DATABASE_URL they explicitly skip. Model HTTP tests use simulated responses and consume no organiser credits. UI/API contracts remain reviewed TypeScript interfaces; generated OpenAPI types are pending.

## GitHub and team sharing

Repository: https://github.com/satworkz/forget-lah. Each teammate uses their own GitHub account, clones the source, and runs `doctor`, `setup` and `up` to generate their own local environment.

Keep `.env`, credentials, local dependencies and database backups out of Git. Review GitHub Actions for the specific shared commit; a local test result does not establish that CI passed.

## Design and next milestone

Start with [the design index](docs/design/forget-lah_README.md). Then read [current implementation status](docs/IMPLEMENTATION_STATUS.md) and [next milestone](docs/NEXT_MILESTONE.md).

Sources for infrastructure conventions: [FastAPI container deployment](https://fastapi.tiangolo.com/deployment/docker/), [Compose startup conditions](https://docs.docker.com/compose/how-tos/startup-order/). Use the organiser's actual onboarding and API contract before live integration.

Test the new simulated confirmation and acknowledgement flow: [Patient simulator guide](docs/PATIENT_SIMULATOR.md).
