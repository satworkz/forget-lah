# forget-lah foundation validation

Latest recorded local verification: **10 September 2026**, foundation v0.1.0. This replaces the earlier pre-Docker validation snapshot. These are recorded results, not a claim that every teammate or remote environment has been checked.

| Check | Recorded result |
| --- | --- |
| Backend suite in Docker | **20 passed, 0 skipped**, with PostgreSQL 17 available |
| PostgreSQL concurrency | Two workers cannot claim the same job; passed against real PostgreSQL |
| Database bootstrap | Initial Alembic migration and synthetic account setup completed; bootstrap exited successfully |
| Python quality | Ruff lint and formatting checks passed |
| Frontend | Dependency installation, TypeScript check and Vite production build passed |
| Docker build and startup | Container builds passed; database, API and mock clinic healthy; worker and web running |
| Browser | Login, three fictional cases, evidence for each case, reload session persistence and sign-out verified |
| Setup and secrets | Local configuration generated; repeat setup preserves existing credentials; private files excluded from Git |

The web app was verified at `http://localhost:8080`. The Docker route is documented in [TEAM_START_HERE.md](TEAM_START_HERE.md). Each teammate should run the checks in their own clone.

GitHub Actions, cloud deployment, organiser model access, patient messaging and other live provider integrations have **not** been verified by this local result. The 20 engineering tests are separate from the planned 60 agent evaluation scenarios. The full agent runtime remains pending.

Two third-party test-client deprecation warnings (Starlette/httpx and an AnyIO alias) were present without failing tests. A successful frontend production build means the frontend bundled successfully; it does not certify that the application is production-ready.
