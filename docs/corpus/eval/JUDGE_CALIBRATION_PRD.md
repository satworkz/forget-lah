# PRD — Judge Calibration Harness for A2's Translation Gate

**Status:** Proposed (not approved) · **Owner:** Evaluation custodian (operator); reviewer-of-record
sign-off per language · **Date:** 2026-09-25 · **Target:** translation-path automated judge admission ·
**Environment:** offline, `forget-lah` repo, no network required for scoring.

**Provenance.** Bounded `@oracle` run, session `ses_f29baa3f4ffeQSlw6q40V65tV7`, 2026-09-25. Every
load-bearing citation below was re-verified first-hand by the orchestrator after delivery
(`decision_log.md:24,40,44,57`; `oracle_rubric.md:18,124-130`; `comparison_projection.py:127`;
`M2_REPLAY.md:48-58`), and both derived figures were independently recomputed
(`e ≤ 1−0.95^(1/60) ≈ 0.0855%`; zero-error bound `n ≥ ln 0.05 / ln(1−0.000855) ≈ 3,523` pairs).

**Placement note.** The proposing run suggested `docs/corpus/m1/`. This file lives under
`docs/corpus/eval/` instead: the harness is evaluation machinery, and the M1 deliverable set is
enumerated in `M1_PRD.md` — adding a non-M1 document there would blur the M1 exit set.

## Background

A2 ("translation path scored as system under test", `decision_log.md:40`) needs 60 predeclared
repetitions and 60/60 semantic passes per scored variant; 0/60 bounds failure at ≈4.87%
(`decision_log.md:44`). Today the semantic track is human only (`oracle_rubric.md:18`), and no judge
has a measured error rate on this task. The Lane C legs are option-picking deciders on
`LocalLLaMA/typed-decisions` (600 `choice` / 600 `noul` / 800 `score`) and are **not** semantic
judges; `openjev-kev4b` is Kev-4B, not `openjev/openjev`; `/workspace/openjev` contains no semantic
judge.

## Objective

Sample a predeclared set of source→translation pairs from the real corpus, obtain blind human
adjudication of semantic preservation from the reviewer of record, score a candidate judge against
that adjudication, and report a confusion matrix, false-pass/false-negative rates, the derived
`(1−e)^60`, a confidence statement, and a use/exclude decision.

## Scope and Non-Goals

**In scope:** sampling; blinding; adjudication procedure; judge scoring; metrics/reporting; UNSCORED
handling; licence/role preconditions.

**Non-goals:** the harness does **not** run the 60 repetitions; grade or modify corpus items; tune or
train the judge; or decide any pass/fail. It does not replace `comparison_projection.project`
(`comparison_projection.py:127`) or the replay verdict path (`M2_REPLAY.md:48-58`).

## Assumptions

- **Verified fact:** A2 is translation-scoped and uses 0/60 (`decision_log.md:44`); reviewers of record
  are human (`decision_log.md:24`); AI may pre-screen only (`oracle_rubric.md:18`); no Anthropic model
  may judge and the judge family must differ from the producer's (PRD §3); AI contributions are
  declared in `ai_declarations`. `openjev/openjev` is CC BY-NC 4.0; Laya's licence is unestablished.
- **Assumption:** at least 60 source→translation pairs suitable for adjudication exist in the real
  corpus at harness time; the reviewer of record is available and blind.
- **Target (derived, not measured):** ≥95% chance of a clean 60/60 requires
  `e ≤ 1 − 0.95^(1/60) ≈ 0.085%`.

## Requirements

1. **FR-1 Sampling.** A predeclared, seeded sample of source→translation pairs is fixed before any
   judge is run; no post-hoc selection or best-run choice.
2. **FR-2 Blinding.** The judge is run blind to adjudication; adjudicators are blind to judge output
   and do not see intended meaning before judging.
3. **FR-3 Adjudication.** The reviewer of record labels each pair `preserves` / `does not preserve`;
   two independent labels agree, a third adjudicator breaks disagreement (D4 roles).
4. **FR-4 Scoring.** Confusion matrix at the judge's operating threshold: false-pass = judge says
   preserve, human says not (the dangerous cell); false-negative = judge says not, human says
   preserve. Report per language.
5. **FR-5 Derived gate.** Report `(1−e)^60` for the point estimate and a confidence bound on `e`
   (exact binomial); label as derived.
6. **FR-6 Reporting.** Machine-readable JSON + prose summary; every run records judge identity,
   licence, family, prompt/hash, seed, sample ids, adjudication labels.
7. **FR-7 UNSCORED.** An unadjudicated pair is UNSCORED, earns no credit, and satisfies no quota
   (`oracle_rubric.md:124-130`).
8. **FR-8 Preconditions.** Refuse to run if the judge is Anthropic-backed, same-family as the
   producer, or unlicensed; record `ai_declarations` for the judge's role.
9. **NFR-1** Deterministic replay from recorded judge outputs; **NFR-2** no corpus mutation;
   **NFR-3** no credentials in outputs.

## Milestones

- **M1 (smallest increment).** One language, a predeclared sample, one candidate judge, human labels,
  confusion matrix + `(1−e)^60`. Exit: report issued, no corpus edits.
- **M2.** Add per-language coverage and the confidence-bound machinery; predeclare sample sizes.
- **M3.** Repeat for each candidate judge; emit the licence/role precondition record.

## Acceptance Criteria

The harness produces, for a predeclared sample, a confusion matrix, false-pass and false-negative
rates, a confidence bound on `e`, the derived `(1−e)^60`, and an explicit use/exclude decision; all
runs replay deterministically; zero corpus items modified; every judging AI declared.

## Rollout or Exit Decision

- **Licenses pre-screen-only use** iff the sample shows zero false-passes, `e`'s upper confidence
  bound ≤ 0.085%, and role/licence preconditions pass. Pre-screen output stays advisory; the reviewer
  of record decides every pass.
- **Exclude** on any false-pass, on an upper bound exceeding target, or on failing preconditions.
- **Single decisive falsifier:** if the judging sample contains even one false-pass, the judge cannot
  be the gate, because bounding `e` at 0.085% by zero-error sampling needs roughly n ≥ 3,500
  adjudicated pairs (derived), infeasible at corpus scale.

## Open Questions

- Is Laya's licence clearable? (unestablished; rights decision open, `decision_log.md:57`.)
- Feasible sample size versus the ~3,500 needed to *bound* `e` at 0.085%?
- May a judge be used as a non-decisive second check if it fails the bound?
