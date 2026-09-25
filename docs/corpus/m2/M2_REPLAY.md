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

Two real archives exist for the ambiguous family, both graded from captured observations and both
re-recorded with the authored source (`variant_tools`) **and the clarification fix**:

| variant | model | decisions | observed | verdict |
|---|---|---|---|---|
| `fam-ambiguous-01-en` | `claude-sonnet-4-5-20250929` | 2 | `waiting` | **PASS (0 paths)** |
| `fam-ambiguous-01-zh` | `claude-sonnet-4-5-20250929` | 2 | `waiting` | **PASS (0 paths)** |

**The failure was a real runtime defect, and it is fixed.** Recorded symptom: both languages returned
`appointment_intent: CONFIRM` and escalated instead of clarifying. `@oracle` traced it to the
simulation review phase (`provider.py:367`), which allowlisted only `REVIEW_NEEDS` and `REPORT_SYMPTOMS`,
so **`CLARIFY` was unreachable**; with no clarify option the coordinator forced an intent and later
chose `EscalateDecision`. Applied changes:

- `provider.py:367` now allowlists `CLARIFY` in the phase;
- the prompt defines `CONFIRM` as requiring a preceding clinic turn that *asked* for confirmation, and
  states that a one-way reminder asks nothing (so a bare acknowledgement stays `UNSPECIFIED`);
- the observation mapping now turns an unset `appointment_intent` into `UNSPECIFIED`, mirroring the
  runtime's own default (`engine.py:399`).

Both variants went from FAILED (7 paths) to **PASS (0 paths)** and remain cross-language
**equivalent**. Guarded by `tests/test_clarification_phase.py` and
`tests/test_archive_grading.py::test_archived_ambiguous_family_is_cross_language_equivalent`.

**Normalisation retained.** `replay` still normalises two non-deciding differences: a visit-scoped
`preferred_language` whose value equals the variant's own language (D2 comprehension repair), and an
unrecorded `callback_requested` treated as `false`.

**Historical note.** An earlier recording of this pair diverged on one token — en returned
`CAPABILITY_UNAVAILABLE` and zh `AMBIGUOUS_REPLY`, and `engine.py:1797-1820` maps the latter to a
clarification wait while any other reason becomes a handoff. That single-token sampling difference is
exactly what A2's 60/60 rule exists to catch, and it no longer appears once the authored source is
used.

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

## Item→runtime mapping (implemented)

`POST /api/cases/{id}/agent/events` now accepts **`scripted_clinic_turn`**: it records the authored
clinic turn as a `SimulatedMessage` and bumps the case version **without advancing the run**, so
`observation_for` surfaces it to the model as `recent_messages`. The recorder replays each
`origin: history` clinic turn before the patient reply. Covered by
`tests/test_scripted_clinic_turn.py` (recorded as controlled input; no run advance; content required).

Both variants were re-recorded against the authored scenario:

> The ambiguous pair below was recorded **before** `runtime_fixtures.variant_tools`; its observations
> cite the harness-default clinic note rather than an authored instruction. Re-recording it is a
> follow-up, not a correctness blocker for that family (it authors no task expectation).

| variant | decisions | observed | verdict |
|---|---|---|---|
| `fam-ambiguous-01-en` | 4 | `escalated` | FAILED — the escalation (6 paths) |
| `fam-ambiguous-01-zh` | 6 | `waiting` | FAILED — `appointment_intent` expected `UNSPECIFIED`, observed **`CONFIRM`** |

**Finding — a language-independent over-interpretation.** The family's clinic turn was changed from
*"Shall I confirm this?"* to a neutral reminder (the old turn led the patient), then both variants were
re-recorded. Both languages still return `appointment_intent: CONFIRM` for a bare `"ok"`:

| variant | decisions | observed | verdict |
|---|---|---|---|
| `fam-ambiguous-01-en` | 6 | `escalated` | FAILED — `CONFIRM` + the escalation (7 paths) |
| `fam-ambiguous-01-zh` | 6 | `waiting` | FAILED — `CONFIRM` only (1 path) |

So the mismatch is **not** language-dependent and **not** caused by the leading turn: with a neutral
reminder, a bare acknowledgement is interpreted as an attendance confirmation. The oracle expects
`UNSPECIFIED` + `CLARIFY`, per the `ambiguous_short_reply` rule *"do not force an unsupported
interpretation"*. This is now a **ruling**, recorded in `oracle_rubric.md` §4 W2b: a reminder asks nothing, so `"ok"`
acknowledges receipt, and confirming attendance requires a clinic turn that asked for it. The corpus
is right and the **runtime over-interprets an acknowledgement** — a shared, language-independent
behaviour, which the programme PRD classifies as a general pipeline defect rather than a language
defect. It is a runtime item to escalate, not a corpus fix. A2's 60 repetitions are required before
calling the over-read systematic.

**Divergence root cause — not language-dependent (recorded 2026-09-25).** The two recorded streams are
identical in shape: `DELEGATE → REVIEW_NEEDS(CONFIRM) → DELEGATE(preparation) → RETURN → DELEGATE →
ESCALATE`, six decisions each. They differ in exactly one field: the model returned
`CAPABILITY_UNAVAILABLE` for en and **`AMBIGUOUS_REPLY`** for zh. `engine.py:1797-1820` then decides
the terminal:

```python
elif isinstance(decision, ClarifyDecision) or (
    isinstance(decision, EscalateDecision)
    and decision.reason_code == "AMBIGUOUS_REPLY" and clarification_allowed(db, run)
):
    ... patient_message(kind="clarification") ... ; release(run, "waiting")
elif isinstance(decision, EscalateDecision):
    request_handoff(...)          # -> escalated
```

So the runtime is behaving as designed; the en/zh difference is a **single-token sampling difference in
the reason code**, which is precisely what A2's 60/60 rule exists to catch — a variant that returns
either reason would fail the 60-repetition gate. It is **not** a language defect.

Two consequences: the clarification path **does** deliver a message (`kind="clarification"`), so
per-message delivery is observable once the contract can address runtime-generated messages; and the
`CONFIRM` over-interpretation is common to both languages before that step.

**Language-switch family (`switch-01`) — added, then fixed and passing (2026-09-25).** Two patient turns
(English → the variant's language) with an English control, replayed through the scripted-clinic-turn
seam. A first recording diverged on the task outcome (en `UNSUPPORTED` vs zh `ANSWERED`), which traced
to the **citable source**: the runtime was answering from the harness-default clinic note, not the
item's authored instructions.

`runtime_fixtures.variant_tools` now overrides the `followup-context` payload's `instructions` with the
item's `approved_instructions`, and the family's oracle gained the task expectation it lacked. Result:

| variant | observed | cited source | verdict |
|---|---|---|---|
| `fam-switch-01-en` | `waiting` | `instr-fast` | **PASS (0 differences)** |
| `fam-switch-01-zh` | `waiting` | `instr-fast` | **PASS (0 differences)** |

`cross_language_equivalence` reports the pair **equivalent**. This is the strongest replay evidence in
the milestone: a passing, multi-turn, language-switch replay against the authored scenario with an
authored citation. Asserted in
`tests/test_archive_grading.py::test_archived_switch_family_is_cross_language_equivalent`.

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
