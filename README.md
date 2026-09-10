# forget-lah

Patient follow-up with a clear next step. NUS-ISS Show Me Your Agents hackathon.

**Current release: 0.1.0, local foundation. Synthetic records only.** The staff workspace, login, migrations, source detection and durable background processing are implemented. The three agent roles are specified; live reasoning, patient conversation and outbound contact belong to the next milestone. See [implementation status](docs/IMPLEMENTATION_STATUS.md) for the exact boundary.

Start with the [team quick-start guide](docs/TEAM_START_HERE.md) for setup and flow testing, or use the [documentation index](docs/README.md) to find technical references.

## First run on Windows

Open this project folder in VS Code. Open Terminal > New Terminal and use PowerShell. Docker Desktop must be running Linux containers.

```powershell
./scripts/dev.ps1 doctor
./scripts/dev.ps1 setup
./scripts/dev.ps1 up
```

`setup` creates a private `.env` with random passwords. Open that file locally and use DEMO_STAFF_EMAIL and DEMO_STAFF_PASSWORD to sign in. Never commit or share `.env`. Existing setup credentials are preserved if you run setup again.

Open **http://localhost:8080**. The first build downloads images and dependencies. After startup, allow the worker about ten seconds and refresh cases. You should see three synthetic patients, one for each specialty, and application-rule evidence when you select a case.

```powershell
./scripts/dev.ps1 status
./scripts/dev.ps1 logs
./scripts/dev.ps1 test
./scripts/dev.ps1 down
```

`down` preserves the database volume. Do not add `--volumes` unless you intentionally want to erase the local demonstration database. Changing database passwords in `.env` does not change an existing database volume's passwords.

## What runs

Browser → Caddy/React → FastAPI → PostgreSQL. The worker reads the internal mock clinic API and transactionally creates follow-up cases and leased jobs. The bootstrap container runs Alembic migrations and seeds the synthetic clinic/staff login before the API starts. PostgreSQL has no published port; the web app binds to local loopback only.

The mock clinic currently serves deterministic episode identities with dates relative to today. It is a fixture service, not a real clinic integration or booking system. All aliases are fabricated. No LLM credentials or provider accounts are needed for this milestone.

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

Python tests use temporary SQLite databases with the actual Alembic migration. A separate test uses real PostgreSQL to verify simultaneous workers cannot claim the same job. It runs in the Compose test service and GitHub Actions; without TEST_DATABASE_URL, it is explicitly skipped. UI/API contracts are reviewed TypeScript interfaces in M1; generated OpenAPI types are a tracked M2 task.

## GitHub and team sharing

Repository: https://github.com/satworkz/forget-lah. Each teammate uses their own GitHub account, clones the source, and runs `doctor`, `setup` and `up` to generate their own local environment.

Keep `.env`, credentials, local dependencies and database backups out of Git. Review GitHub Actions for the specific shared commit; a local test result does not establish that CI passed.

## Design and next milestone

Start with [the design index](docs/design/re-mind_README.md). Then read [current implementation status](docs/IMPLEMENTATION_STATUS.md) and [next milestone](docs/NEXT_MILESTONE.md).

Sources for infrastructure conventions: [FastAPI container deployment](https://fastapi.tiangolo.com/deployment/docker/), [Compose startup conditions](https://docs.docker.com/compose/how-tos/startup-order/). Use the organiser's actual onboarding and API contract before live integration.
