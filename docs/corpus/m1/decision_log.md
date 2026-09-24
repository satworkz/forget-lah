# M1 decision log

**Status:** record, not a debate. Each entry states the accepted decision, its owner, and its source.
Later rulings that amend an earlier decision are recorded as amendments in place; the earlier text is
never silently rewritten.

- **Programme PRD decisions accepted 2026-09-23** — `docs/MULTILINGUAL_CONVERSATION_CORPUS_PRD.md`
  (branch `docs/multilingual-conversation-corpus-prd` @ `9103197`), "Decisions" and the two approved
  policy sections. The authoritative signed record is held with the operator.
- **M1 governing ruling 2026-09-24** — `astra-m1-forks-v2` (Fork A / Fork B), applied to
  `corpus/schema/corpus.schema.json` and reconciled in `runtime_semantics_map.md` §12.

The M1 PRD refers to the 2026-09-23 set as "the nine accepted operator decisions"; the programme PRD
records them as an eight-topic decisions table plus two approved policy sections. They are
reproduced here as D1–D10 without renumbering the source.

## Decisions

| # | Decision | Owner | Source | Status |
|---|---|---|---|---|
| D1 | **Runtime vocabulary.** Use the runtime's actual types, never invented labels: patient tasks `QUESTION`/`PLAN`; question outcomes `ANSWERED`/`GUIDANCE`/`NOT_REQUIRED`/`CLINIC_REVIEW`/`UNSUPPORTED`; appointment intent `CONFIRM`/`CANCEL`/`CHANGE`/`UNSPECIFIED`; instruction checks `MET`/`NOT_MET`/`UNCLEAR`. | operator | PRD Decisions | accepted |
| D2 | **Language-preference semantics.** A language switch alone changes no lasting preference. Only an explicit request sets one; a clear comprehension repair may set a **visit-only** language. | operator | PRD Decisions; map §9 | accepted |
| D3 | **Corpus size and gates.** 520 variants: 200 development, 320 locked evaluation; ~20 evaluation variants per language held as the custodian-only acceptance holdout. The 5% regression bound is a **screening target**, not a guarantee. | operator | PRD Decisions; PRD §4 | accepted |
| D4 | **Reviewers and rights.** Original synthetic text only. Reviewer of record per language: operator (`ms`), Satish (`ta`), Bryan (`zh`); final adjudicator Rohit. Independent AI back-translation with a blind 20% human spot-check. Unresolved items are excluded from locked evaluation. | operator / Satish / Bryan / Rohit | PRD Decisions | accepted |
| D5 | **Storage, retention and access.** Development variants and the hash manifest live in the repository; evaluation variants, expected answers, the holdout and run traces live in restricted custodian-held storage. 90-day retention unless project rules require otherwise. | operator | PRD Decisions | accepted |
| D6 | **Model and replay pinning.** Pin model IDs, prompt and code revision, the reference clock and fixture results. | operator | PRD Decisions | **amended 2026-09-24** (see A2) |
| D7 | **Fixtures and test phones.** Engineering owns the source-API and staff-acceptance fixtures; test-phone owners are operator, Satish and Rohit. The signed `whatsapp_test` round trip verifies delivery **only**. | engineering / operator / Satish / Rohit | PRD Decisions | accepted |
| D8 | **Tuning separation.** Engineering agents tune on development variants only and never receive evaluation or holdout variants. Reviewers and the adjudicator see expected meanings, so neither may double as the tuner. | operator | PRD Decisions | accepted |
| D9 | **Wrong-number and third-party policy.** A reply from an unverified third-party sender is not treated as the patient: the runtime must quarantine the send, disclose nothing, change no memory and no appointment, and flag the thread for staff verification. No dedicated runtime path exists today, so the **Wrong number** and **Third-party reply** strata are authored but excluded from scoring and reported as **unscored coverage** — never as passing. | operator | PRD approved policy §1; schema `scoring.unscored_reason` | accepted |
| D10 | **Expected terminal outcome and step bounds.** Every scenario declares exactly one correct terminal outcome at authoring time. `waiting` is correct only where authored. A handoff counts as success only after named staff acceptance. Step exhaustion is always a failure (`agent_max_steps` default 40, `settings.py:39`; simulator role limits 8 Coordinator / 6 specialist, `engine.py:784`). `CLINIC_REVIEW` and `UNSUPPORTED` are correct only where expected. Code bounds are recorded, not raised per scenario. | operator | PRD approved policy §2; map §10 | **amended 2026-09-24** (see A1) |

## Amendments (M1 governing ruling, 2026-09-24)

The `astra-m1-forks-v2` ruling resolved the two policy questions `runtime_semantics_map.md` §12 had
carried as *needs-human-decision*. It amends D6 and D10; it does not reopen D1–D5 or D7–D9.

| # | Amend | Decision | Owner | Supersedes |
|---|---|---|---|---|
| A1 | D10 | An explicitly authored **`escalated`** ending may be the single accepted outcome, **only as an unaccepted handoff**: `run_status: escalated`, `outcome: null`, authored handoff reason, matching clinic/case/run `handoff_evidence` with `accepted_by`/`accepted_at` explicitly `null`, `callback_requested: true`, the same-item task `CLINIC_REVIEW`, and no `staff_acceptance` record for that handoff. An **unexpected** escalation remains a failure. This activates `terminal_oracle.kind: escalated` and satisfies the `questions` stratum. The authored budget-failure exception is removed: `STEP_BUDGET_EXHAUSTED` / `ROLE_BUDGET_EXHAUSTED` are always failures and must never be authored as an expected terminal. | operator (Astra Fork A) | D10's "unowned escalation is a failure" once an escalation is *authored* as the intended unaccepted handoff; the blanket schema prohibition |
| A2 | D6 | The **translation path is scored as part of the system under test** at its implemented **temperature 0**, with **60 predeclared fresh repetitions per scored variant** (English controls included) and **60/60 semantic-oracle passes** required for a variant to pass; no majority or best-run selection. `translation_configured` is *derived* (`multilingual_enabled AND agent_model_mode == "anthropic" AND model_configured`), and the exact provider/model/API/seed/plan/retry profile is pinned in `environment.translation_profile`. Only independently evidenced infrastructure faults may receive at most two replacement attempts, all retained; validation/semantic failures are never replaced. | operator (Astra Fork B) | D6's clause **"One declared run per variant; reruns for diagnosis only"** — for scored translation variants this is replaced by one declared **60-repetition experiment** |

**D6 reconciliation, stated plainly.** The clause "One declared run per variant; reruns for diagnosis
only" remains in force for non-translation grading, but it **cannot** also govern the translation
path: 60 repetitions are required to bound per-variant failure at a one-sided 95% upper bound of
≈4.87% (0/60). The two clauses are not contradictory once the scope is separated, and the schema
encodes the translation scope. Diagnostic reruns still cannot replace a failure.

**Quota preservation.** A1 keeps the `questions` quotas already in the programme PRD — four
development and six evaluation aligned families, plus one development and two evaluation independent
threads per language — and reserves at least one development and two evaluation aligned families
within them for unresolved-question escalation, retaining source-answerable question coverage.

## Still not decided (do not treat as approved)

| Item | Kind | Status |
|---|---|---|
| Permitted authorship and licences for each source; any stricter per-stratum release gate | rights | **open** — M1 may author `licence: pending`; pending rights are never treated as approved |
| Benchmark ownership and the replacement-holdout procedure | process | **open** |
| Whether the runtime's unaccepted-handoff `escalated` path produces the required evidence in practice | verification | **open** — the schema is authored from `engine.py:200-215`; live evidence is not yet captured |
| Contract-test enforcement of the 37 `x-cross-field-rules` | engineering | **resolved 2026-09-24** — unblocked and implemented in `tests/test_corpus_contract.py` (R1–R37, positive and negative fixtures); R10/R27/R34 remain oracle/harness review obligations |
