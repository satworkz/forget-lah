# M1 validation record

Records the checks run for the M1 contract, with results and labelled unknowns. Anything not checked
is marked **NOT RUN** or **UNVERIFIED** rather than inferred.

## Revision under test

| Artifact | Revision |
|---|---|
| `corpus/schema/corpus.schema.json`, `docs/corpus/m1/runtime_semantics_map.md` | `c227dfc` |
| `src/forget_lah/corpus/comparison_projection.py` + tests | `fa7867e` |
| M1 exit docs (this file, rubric, decision log, fixture contract) | this commit |
| Repository / branch | `/workspace/forget-lah`, `feat/multilingual-corpus-contract` |

Line citations in the map were re-derived against the working tree; no runtime code changed in this
milestone beyond the new pure projection module.

## Checks

| Check | Command | Result |
|---|---|---|
| Schema JSON syntax | `python3 -m json.tool corpus/schema/corpus.schema.json` | **OK** |
| Schema self-consistency | assertion over required-vs-properties (recursive) | **0 mismatches**; 37 `x-cross-field-rules` present |
| Lint | `uv run ruff check .` | **All checks passed** |
| Format | `uv run ruff format --check .` | **219 files already formatted** |
| Projection unit tests | `uv run pytest tests/test_comparison_projection.py` | **7 passed**, 2 warnings |
| Full suite | `uv run pytest` | **in progress** — see below |
| Web build | `pnpm --dir apps/web build` | **NOT RUN** — `pnpm` is not installed in this environment; no frontend or API-contract change in this revision |
| PostgreSQL concurrency | — | **skipped** without `TEST_DATABASE_URL`; SQLite results do not establish PostgreSQL locking behaviour |

### Full-suite status (honest)

A first detached `uv run pytest` run reached **100%**; its progress lines contained only `.` and `s`
markers — no `F` (failure) or `E` (error) — but the detached shell lost pytest's final count line
(the only stray `F` in the log is the word "AbstractContextManager" in the warnings summary). A second
detached run with an `EXIT=` marker is still running. **No failure has been observed, but the exact
passed/skipped counts are not asserted here until the marker lands.** This is a long suite
(>10 min) in this environment.

## Unresolved items (labelled)

| Item | Label | Consequence |
|---|---|---|
| Permitted authorship / licences; stricter per-stratum gate | **UNRESOLVED (human)** | M1 may record `licence: pending`; pending rights are never treated as approved |
| Contract tests (`tests/test_corpus_contract.py`, `tests/fixtures/corpus_m1/*`) | **HELD back pending standup** | the 37 `x-cross-field-rules` are **not enforced**; a schema-valid item is *not* evidence of correct semantics |
| Unaccepted-handoff `escalated` runtime evidence | **UNVERIFIED** | the arm is authored from `engine.py:200-215`; no live run has yet produced the required `handoff_evidence` |
| zh/ms/ta delivery path | **UNVERIFIED at M1** | `translation_configured` requires `agent_model_mode == "anthropic"`; the 60-repetition benchmark is an evaluation cost, not an M1 check |
| Wrong-number / third-party runtime path | **ABSENT** | those strata stay `UNSCORED` and are never reported as passing |
| Clock freezing | **RESOLVED IN CONTRACT, NOT IN CODE** | `db.utcnow` has no override seam; replay must monkeypatch it or a seam must be added |
| Web build | **NOT RUN** | `pnpm` unavailable here |
| Benchmark ownership / replacement-holdout procedure | **UNRESOLVED (human)** | open per the programme PRD |

## Provenance

- **Read from source** while writing the map and this contract: `settings.py` (`agent_max_steps`,
  `translation_configured`), `source.py` (`DEMO_CLINIC_ID`), `db.py` (`utcnow`), `simulation.py`
  (simulator gate, `displayed_in_simulator`), `engine.py` (handoff, budgets, delivery labels),
  `channel.py`/`routes.py` (outbox lookup), `questions.py`/`contracts.py`/`policy.py` (task and
  handoff rules).
- **Re-verified by the orchestrator**: schema line citations after the commandcode-API edit, the
  structural self-consistency assertion, and the projection's determinism tests.
- **Not independently re-verified**: the remaining map citation set listed in `M1_PRD.md`'s appendix;
  live runtime behaviour of the escalation and translation paths.
