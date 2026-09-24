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

**Gaps to close before an archive is real:**

1. map the runtime checkpoint into the item's projection shape — `tasks` must be built from
   `patient_questions` + `patient_task_types`, not read as a `tasks` array;
2. map the item's `environment.fixtures.source_api` results onto the mock source transport;
3. emit `source_run` provenance naming the actual model id (never a mock presented as live).

## Outstanding

The grader is complete and exercised by `tests/test_corpus_replay.py`. The **archive producer** is
the remaining build: the wiring above is identified, but gaps 1–3 are a real integration task that
must be iterated against the runtime test apparatus. Until it lands, **no pilot variant carries an
execution archive and no replay claim is made.**
