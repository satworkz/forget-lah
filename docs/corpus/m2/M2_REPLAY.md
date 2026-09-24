# M2 replay contract

M2 acceptance requires that **replay demonstrates checkpoint grading, ambiguity and language
switching**. The schema defines the origin precisely: `execution_origin: replay` *reproduces one
observed execution from archived request/response evidence and does not estimate variability* (A2).

This document specifies the archive record and the verdict the grader
(`src/forget_lah/corpus/replay.py`) produces from it.

## Archive record

```jsonc
{
  "replay_version": "1",
  "variant_id": "fam-questions-01-en",
  "execution_origin": "replay",
  "source_run": {                      // provenance of the live run that produced this archive
    "runtime_commit": "85e9b89",
    "model_id": "deepseek/deepseek-v4.1-flash",
    "prompt_version": "1",
    "started_at": "2026-09-24T09:00:00+08:00",
    "request_id": "req-…"
  },
  "translation_status": "ok",          // or a hard-failure status (see below)
  "observed": {                        // the graded fields, same shape as a corpus item
    "identity": { "variant_id": "fam-questions-01-en", "language": "en", … },
    "environment": { "translation_configured": true, "delivery_evidence_source": "displayed_in_simulator" },
    "checkpoint_oracle": [ … ],        // observed checkpoints, not the expectation
    "terminal_oracle": { … },          // observed terminal
    "scoring": { "scored": true }
  },
  "evidence": {
    "requests":  [ { "turn_id": "t2", "sha256": "…" } ],
    "responses": [ { "turn_id": "t2", "sha256": "…" } ],
    "delivery":  [ { "turn_id": "t2", "delivery_status": "displayed_in_simulator" } ]
  }
}
```

- Archives carry **hashes and references**, never raw credentials or real patient data.
- `observed` uses the runtime's own vocabulary; the grader projects both sides through
  `comparison_projection`, so incidental ids, timestamps and prose never affect the verdict.

## Verdict

| Condition | Grade |
|---|---|
| no field difference and no hard failure | **PASS** |
| any projected field differs, or `wrong_target_language` / a hard translation failure | **FAILED** |
| the authored item is quarantined (`scoring.scored: false`) | **UNSCORED** — no passing credit, satisfies no coverage quota |

Hard-failure statuses (`translation_status`): `TRANSLATION_VALIDATION_FAILED`,
`TRANSLATION_INCOMPLETE`, `semantic_corruption`, `wrong_target_language`,
`missing_required_delivery`, `worker_interruption`. These are failures of the system under test and
are **never** replaced by a diagnostic rerun (rubric §5).

The verdict always reports `differences` (path, expected, observed) so a failure is actionable, and
never selects a best or majority run.

## Cross-language equivalence

`cross_language_equivalence(a, b)` projects two aligned variants and compares them **after** dropping
the declared language-dependent paths (`LANGUAGE_DEPENDENT_PATHS`) plus `identity.variant_id`. That is
the property the programme PRD calls "the same state trajectory and eventual outcome after the
approved normalization", and it deliberately does **not** normalize business outcomes away.

## Producer wiring (recon 2026-09-24)

The archive producer reuses the runtime test apparatus rather than reimplementing it:

| Need | Seam |
|---|---|
| store + signed client | the `runtime` fixture in `tests/test_runtime.py` (alembic sqlite + seeded mock clinic) |
| case + run | `start(runtime)` |
| patient turn | `event(client, case_id, "demo_reply", <variant patient text>)` |
| engine drive | `drain(runtime, model=…, tools=…)` → `claim_run`/`process_run` |
| capture | `view(client, case_id)` (run status, steps, checkpoint) |
| frozen clock | monkeypatch `forget_lah.db.utcnow` to `clock.reference_datetime` |
| simulator path | `Settings(patient_simulator_enabled=True, agent_min_interval_seconds=0)` and a `DEMO_CLINIC_ID` run so `simulation_enabled(run)` holds |
| sources | `ClinicTools(..., transport_for(source), FOLLOWUP_KEY)` — item `source_api` results must be supplied through that transport, not a standalone dict |
| model | `MockModel` is deterministic and must be labelled **mock**, never Claude; a recorded model is required for a true observation |

**Observed checkpoint keys** the capture step reads: `appointment_intent`, `patient_questions`,
`patient_task_types`, `callback`, `wait_reason`, `outcome`.

**Gaps before an archive is real:**

1. ~~map the runtime checkpoint into the item's projection shape~~ — **done**:
   `src/forget_lah/corpus/runtime_mapping.py` joins `patient_questions`/`patient_task_types` with
   `question_answers` (`contracts.py:86`) and packages checkpoint/terminal/delivery evidence into the
   observation shape; unit-tested in `tests/test_runtime_mapping.py`, including a mapped run that
   grades **PASS** against its pilot variant;
2. ~~map the item's `environment.fixtures.source_api` results onto the mock source transport~~ —
   **done**: `runtime_fixtures.source_transport` serves the item's frozen results by call name and
   delegates everything else to the harness default (an empty `source_api` means "use the default",
   which is what the pilot items declare);
3. ~~emit `source_run` provenance~~ — **done**: `archive_record` records the actual `model_id`,
   `runtime_commit`, `prompt_version`, clock start and request id.

## Recorded findings (2026-09-25)

Two real archives exist for the ambiguous family, both graded from captured observations:

| variant | model | decisions | observed | verdict |
|---|---|---|---|---|
| `fam-ambiguous-01-en` | `claude-sonnet-4-5-20250929` | 5 | `escalated` | FAILED (6 paths — the escalation) |
| `fam-ambiguous-01-zh` | `claude-sonnet-4-5-20250929` | 2 | `waiting` | **PASS (0 paths)** |

**Cross-language divergence (investigated).** `cross_language_equivalence` reports the two variants as
**not equivalent**. Reading the recorded decisions gives a different verdict for each difference:

1. **zh memory — resolved: permitted and no longer graded.** `replay` now normalises two
   non-deciding differences before comparing: a **visit-scoped `preferred_language` whose value equals
   the variant's own language** (D2 comprehension repair — permitted, not required), and an
   **unrecorded `callback_requested` treated as `false`** (the runtime stores no negative callback).
   zh fell from 3 differing paths to **1**; en from 8 to **7**.
2. **en escalation — inconclusive: the run did not use the authored scenario.** The recorded decisions
   are `DELEGATE → REVIEW_NEEDS(UNSPECIFIED, updates: []) → TOOL READ_SOURCE → DELEGATE → ESCALATE`
   with reason **`CAPABILITY_UNAVAILABLE`**. But the harness injects only the **patient reply text**:
   the clinic history and source data come from the runtime's *default detected case* (`start()`
   selects by specialty), the item's `conversation` is never injected, and its `source_api` is empty.
   The model therefore never saw the authored ambiguous scenario, so the escalation cannot be
   attributed to the runtime, the model or the oracle. **Ruling: inconclusive — implement the
   item→case/conversation/source mapping, then repeat (A2: 60 runs) before any behavioural claim.**
3. **Trajectory length differs by language for the same scenario** — 5 decisions (en) vs 2 (zh).
   Sampling variance of this kind is exactly why A2 requires 60 predeclared repetitions and 60/60
   passes rather than one run per variant.

**Delivery expectation — adjudicated as an oracle error (fixed).** Both archives had flagged
`checkpoints[0].delivery.expected_message_delivery`. The schema documents that field as delivery
evidence *per message the run emits*, but the generator asserted it against `t2` — the **patient**
turn. A patient turn is never delivered; a runtime-*generated* clinic message is, and it has no
authored turn id. The expectation was a category error, so the pilot no longer asserts it. With the
visit-only language, absent-callback and delivery normalisations in place, **`fam-ambiguous-01-zh`
grades PASS with zero differences**; `fam-ambiguous-01-en` still fails on its genuine escalation.

**Open contract gap.** The pilot consequently asserts **no** per-message delivery coverage. Expressing
"the reply generated after turn X is delivered" needs the contract to address runtime-generated
messages, which it does not today.

Asserted in `tests/test_archive_grading.py::test_archived_en_and_zh_diverge` so a fix flips it
deliberately.

**Language-switch coverage is still thin.** The pilot's non-English variants reply in the target
language to an English clinic turn; there is **no dedicated mid-conversation switch family**. The M2
plan claims one per language pair — that authoring gap is open.

## Producer status

The producer is built and exercised end-to-end by `tests/test_archive_producer.py`: it freezes the
clock, starts a simulated run, injects the variant's patient turn, drains the engine, maps the
captured checkpoint, writes the archive and grades it.

**First produced observation — harness self-test, not a benchmark result.** For
`fam-ambiguous-01-en` with the harness-default clinic fixtures and the deterministic `MockModel`, the
run ended `escalated` where the authored oracle expects `waiting`, and the captured checkpoint held
only early keys (`delegation_start`, `latest_event`, `patient_simulator_enabled`,
`returned_specialists`, `turn_start_step`). Grading reported the exact differing paths
(`terminal.kind/run_status`, `checkpoints[0].appointment_intent`, `wait_reason`,
`delivery.expected_message_delivery`). Two caveats keep this from being a corpus result: the pilot
items declare an empty `source_api` (so harness defaults are used, not variant fixtures) and the
model is a deterministic double. **Source-fixture convention.** A `source_api` entry's `call` is matched against the request path as a
suffix or as its final segment, so it can address the runtime's real episode paths —
`followup-context/DEMO-DENTAL-RECALL-01`, `followup/<episode>/confirm` — as well as bare names such as
`availability`. Note the runtime selects the case/episode from the detected candidates, so pinning
source results alone does not pin the scenario; a true replay also needs the variant's case mapping.

**Recording — unblocked, partial.** An Anthropic credential is now present (untracked `.env`), and
`recording.RecordingModel` / `RecordedModel` capture and replay real decisions. A first genuine
recording exists at `corpus/development/recordings/fam-ambiguous-01-en.json`
(`model_id: claude-sonnet-4-5-20250929`, 2 recorded decisions), produced by
`tests/test_live_recording.py` (opt-in via `RUN_LIVE_RECORDING=1`; the test loads `.env` itself).

Two cautions and one follow-up:

- **Never shell-export `.env` while running the suite.** `SettingsConfigDict(env_file=None)` means
  provider settings come from the *ambient* environment, so conftest's `Settings()` would flip every
  test to `anthropic` and issue live calls. The live test loads `.env` into its own environment with
  `monkeypatch` instead.
- **The earlier "parks in `queued`" reading was a harness artefact, not a runtime defect.** The parked
  run held a `pending` step with `MODEL_CONNECTION_FAILED` (`attempts=1`), and `record_failure` had
  released it `queued` with `delay=exc.retry_after` (30 s): `available_at` was a concrete future
  timestamp and `lease_until` was `null`. The 60 s drain simply sampled it mid-backoff. A backoff-aware
  drain (sleeping to `available_at`, bounded to 180 s) drives it to a terminal.
- The live run now reaches **`escalated`** with **7 recorded decisions** across 12 completed steps. The
  variant's authored oracle expects `waiting`, so the graded verdict is **FAILED** — a real observation,
  unlike the `MockModel` self-test.
- **Clock freeze is not the fix — it is a tension.** Freezing `utcnow` for the record pass breaks
  retries: `release(..., delay=30)` sets `available_at = frozen_now + 30 s`, which is never
  `<= frozen_now`, so a retry can never be claimed. Not freezing breaks replay fidelity: recorded
  replies embed `expected_case_version`, so an offline re-execution whose context is not byte-identical
  rejects them and diverges (`409: Wait until the agent requests a demo reply`).
- Resolving it needs one of: a **ticking** deterministic clock whose per-decision tick is recorded and
  replayed; or grading the **archived observation** captured during the record pass (the archive's
  `observed` block is captured evidence, not re-derived), reserving `RecordedModel` re-execution for
  in-process replay.
- No graded archive exists yet, and **no M2 replay evidence is claimed**.
