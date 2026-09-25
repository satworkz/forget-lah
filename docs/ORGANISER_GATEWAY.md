# Organiser model gateway — deployed 25 September 2026

AWS uses `AGENT_MODEL_MODE=organiser`, `LLM_GATEWAY_URL=https://api.softwaresystems.app`, and `LLM_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0`. The private `LLM_GATEWAY_API_KEY` is server-side only, in ignored deployment configuration and the mode-600 cloud environment. No key is included in this document.

## Implemented integration

The existing agent adapter posts Ollama-style JSON to `/api/chat` with `X-API-Key`, one user message, `stream=false`, and temperature zero. Coordinator, Engagement and Preparation retain their existing typed decisions, role permissions, source evidence checks and deterministic policy gates. There is no fallback to direct Anthropic or mock inference when the organiser fails.

Bridge mapping/normalization and both outbound and staff-display translations now select the organiser too. Translation readiness recognizes this provider and new translation metadata identifies it correctly. Existing cached translations remain intact.

Agent output remains bounded to 512 requested tokens. Structured intake/translation uses a tested 1024-token bound; Bridge normalizes one row per call under the organiser provider. The Anthropic path retains its existing ten-row chunks. A profile call plus one normalization call per row means large organiser uploads require more calls/time. Source evidence and staff approval requirements remain unchanged. Structured responses may have a complete JSON Markdown fence, but still undergo strict JSON parsing, duplicate-key rejection and existing semantic validation. Unsupported/malformed/truncated responses fail closed.

Provider HTTP error bodies are no longer printed, preventing echoed credentials or input from entering application logs. Status and bounded error codes remain available.

## Validation

- Live synthetic Coordinator and Engagement decisions validated their request/case bindings.
- Preparation validated after the existing one-time repair path; its initial response included prose outside the JSON. This is recorded as a limitation, not an executed action.
- Live synthetic Malay, Chinese and Tamil translations passed existing checks.
- Live synthetic Bridge profiling/extraction preserved the supplied patient name and doctor note. Nothing was imported into a live case.
- Early 2048/4096-output probes timed out; the final bounded 1024 configuration passed. This is a tested setting, not a claim about the gateway's published maximum.
- Focused offline provider, translation, Bridge and runtime tests: 156 passed, one PostgreSQL-only test skipped on Windows.
- Separate Docker/PostgreSQL/provider run: 33 passed, with two existing dependency deprecation warnings.
- Ruff lint/format and runtime image build passed. No frontend source changed; the existing frontend remains deployed. The full historical regression suite was not rerun for this provider-only change.
- Deployed AWS synthetic check returned `MODEL_CONNECTION_VERIFIED`, provider `organiser`, 921 input tokens, 96 output tokens and 3120 ms measured latency.
- HTTPS readiness, anonymous denial, secure sign-in, audit access and CSRF rejection passed. PostgreSQL has no published host port. A bounded scan of 500 recent lines per service found none of nine configured credential values.

These are bounded integration checks, not a complete live video rehearsal or load test. Gateway availability, quota and semantic model behavior remain external dependencies. Existing repair/failure paths remain active; long structured outputs can still be rejected safely.

## AWS deployment and preservation

Release: `20260925-organiser`. API and worker were replaced; source and frontend images were retained. Application/source revisions remain `0017` and `sim0004`; no migrations or seeding.

Both databases were backed up and dump listings validated. All pre-existing values across 34 tables matched before and after API restart, before the provider switch and worker resumption. Seven existing waiting/paused runs were then changed from `anthropic` to `organiser` with seven append-only security events. Every other run field was explicitly compared and preserved; statuses, replies, appointments, cases and phone bindings were not reset or replayed. This makes subsequent work on existing cases use the new provider while retaining historical evidence. Paused reviews remain paused.

The first attempt to record per-run changes in the case audit table hit its unique case/action constraint and rolled back. A full 34-table comparison verified the rollback. The switch was then recorded using the append-only security-event ledger and succeeded. No partial mode changes survived the failed attempt.

Only the four intended provider environment values changed. Previous direct-provider credentials and all other settings were retained privately; normal organiser operation does not select the direct provider. After preservation checks, the existing worker resumed; the explicit deployed connection check reserved one call through the normal daily budget.

Backups and prior environment/Compose files: `/home/ubuntu/forget-lah/backups/20260925-organiser/`.
Release files: `/home/ubuntu/forget-lah/releases/20260925-organiser/`.
Private local recovery copies: `.cache/aws/release-20260925-organiser/`.
Previous API/worker image tags end in `20260925-organiser` under their rollback names.

Rollback requires stopping API/worker, restoring the prior environment and runtime image, and reverting only the run IDs in `provider-switch.json` to their recorded old provider with an audit event. Preserve existing state and do not restore the whole database merely to change providers. Do not run bootstrap seeding, replay cases, or rotate unrelated secrets.

## Changed source files

- `src/forget_lah/runtime/provider.py`
- `src/forget_lah/bridge.py`
- `src/forget_lah/settings.py`
- `src/forget_lah/translations.py`
- `src/forget_lah/staff_translations.py`
- `tests/test_organiser_integration.py`

No schema migration was added.
