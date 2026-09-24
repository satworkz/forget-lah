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

## Outstanding

The grader is complete and exercised by `tests/test_corpus_replay.py`. The **archive producer** —
executing a pilot variant through the runtime's `patient_simulator` path from frozen fixtures and
writing the record above — is the remaining build. It needs the runtime apparatus (alembic store,
mock clinic source, a recorded/Mock model, frozen SGT clock via `forget_lah.db.utcnow`, and no real
writes) and is the last item between the authored pilot and a replay demonstration. Until it exists,
no pilot variant carries an execution archive and **no replay claim is made**.
