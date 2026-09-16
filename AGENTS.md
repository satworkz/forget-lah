# forget-lah engineering instructions

Read README.md, docs/IMPLEMENTATION_STATUS.md, and the current design guides before extending the project.

- This hackathon is Patient Follow-up. Do not add an appointment-management engine or clinical advice.
- Three agents: Coordinator, Engagement, Preparation. Only the Coordinator delegates.
- Model output cannot prove identity, consent, booking success or authority. Validate typed proposals and apply deterministic policy before tools.
- Source APIs own appointments. Uploaded records cannot invent slot availability. A handoff is owned only after named staff acceptance.
- Distinguish rule, mock and live-model events. No simulated integration may be labelled live.
- Keep clinic boundaries in database relationships and request queries. Keep credentials and patient data out of Git and logs.
- Implement and test in small coherent milestones. Do not deploy publicly or contact real patients from this local foundation.
- Do not spawn sub-agents unless the user explicitly requests them.

Checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `pnpm --dir apps/web build`.
The PostgreSQL concurrency test is skipped unless TEST_DATABASE_URL is supplied; never claim SQLite tests prove PostgreSQL locks.
Use migrations for schema changes; never change an already delivered migration to modify a deployed database.
