# M1 PRD — multilingual conversation corpus contract

**Status:** Approved for implementation (2026-09-23)
**Milestone:** M1 of the programme PRD, "Contract and policy mapping"
**Programme PRD:** `docs/MULTILINGUAL_CONVERSATION_CORPUS_PRD.md` — currently on branch
`docs/multilingual-conversation-corpus-prd` at `9103197`, not yet merged to `main`.
**Decision ledger:** all nine operator decisions accepted 2026-09-23.

> **Note on the programme-PRD reference.** This branch is based on `origin/main` (`880da93`), which
> does not yet contain the programme PRD. The path above resolves once
> `docs/multilingual-conversation-corpus-prd` merges. Until then, read it from that branch.

Provenance: bounded read-only @oracle run, session `ses_f3369866effeRq0kWCqfKKAwsE`, 2026-09-23,
requested as "@oracle give bounded PRD for M1". Oracle's line-number citations were re-verified by
the orchestrator after delivery; see the appendix, which **supersedes the body for all line numbers**.

---

## 1. Goal and Non-goals

M1 establishes an implementable contract for the programme PRD before corpus production. It must
map each graded checkpoint and terminal expectation to observable runtime evidence, with policy
expectations clearly distinguished from behaviour the code currently enforces.

**Non-goals:** corpus generation beyond a small schematic pilot fixture set; an evaluation run;
model selection; production writes; tuning or release claims.

## 2. Deliverables

| Artifact path | Purpose | Definition of done |
|---|---|---|
| `docs/corpus/m1/runtime_semantics_map.md` | Trace graded fields to runtime evidence. | Each field names its source, extraction point, meaning, and any unsupported or uncertain behaviour. |
| `corpus/schema/corpus.schema.json` | Versioned thread, oracle, split and provenance contract. | Valid pilot items pass; malformed or contradictory items fail schema or stated cross-field checks. |
| `src/forget_lah/corpus/comparison_projection.py` | Deterministic, language-neutral comparison view. | Pure projection preserves required semantic differences and excludes incidental IDs and timestamps. |
| `docs/corpus/m1/oracle_rubric.md` | Govern meaning judgments. | Rubric has worked ambiguity examples. |
| `docs/corpus/m1/decision_log.md` | Record the nine accepted decisions and owners. | Records decisions without reopening them. |
| `docs/corpus/m1/fixture_contract.md` | Specify isolated simulator inputs and evidence capture. | Clock, clinic, source results, staff events, delivery evidence and write boundaries are explicit. |
| `tests/fixtures/corpus_m1/*.json`, `tests/test_corpus_contract.py` | Exercise the contract with synthetic examples. | Positive and negative cases cover schema and projection invariants; these are not benchmark items. |
| `docs/corpus/m1/validation.md` | Record M1 checks and remaining unknowns. | Contains commands, results, source revision and labelled unresolved items. |

Evaluation items and their expected answers must never appear on this branch.

## 3. Requirements

### 3.1 Semantics map

Separate patient-turn interpretation from accumulated checkpoint state. `REVIEW_NEEDS` admits
`UNSPECIFIED`, `CHANGE`, `CONFIRM` and `CANCEL`; questions and neutral plans are distinct inputs,
capped at three combined, then stored as aligned `patient_questions` and `patient_task_types`
arrays.

`ANSWERED`, `GUIDANCE`, `NOT_REQUIRED`, `CLINIC_REVIEW` and `UNSUPPORTED` are **per-question
outcomes**, not whole-thread terminal outcomes. `PLAN` accepts only `GUIDANCE` or `NOT_REQUIRED`,
and answered or guided tasks require approved-source evidence. Instruction checks use `MET`,
`NOT_MET` or `UNCLEAR` with a bound reply and quote.

### 3.2 Schema

Require one authored terminal expectation per scenario, expressed separately from question
dispositions. The programme PRD's phrase "permitted terminal alternatives" must be removed: the
accepted policy allows exactly one.

Encode expected run status, outcome or wait/failure reason, handoff evidence, forbidden actions and
checkpoints. Runtime run status is `queued`, `running`, `waiting`, `paused`, `escalated` or
`completed`. Completion outcomes include owned staff handoff and simulated confirmation.

A handoff needs named acceptance; pending callback or clinical review may also require resolution
before completion. Wrong-number and third-party fixtures must be explicitly `UNSCORED`, never marked
passing.

### 3.3 Projection

Compare checkpoint intent, question meaning and disposition, task types, instruction checks, memory
effects, translation and gate behaviour, then the single terminal expectation. Keep locale-specific
expected language values; discard only incidental run IDs, timestamps and prose style.

Represent memory expectations as no change, `set`, `remove` or oracle-unknown: `remove` is the
runtime operation behind the programme PRD's loose word "clear"; unknown is an oracle annotation,
not a runtime write. A mere language switch must not become a lasting preference. The model prompt
instructs visit-only comprehension repair, while runtime validation checks a supporting quote and
language-tag shape; the oracle must grade the policy rather than assume code guarantees it.

### 3.4 Fixture contract

Specify a demo-clinic run with the simulator enabled; that path requires both the demo clinic
identity and the checkpoint flag. The role-limit wording must be stated as **simulator: Coordinator
8, specialists 6; otherwise: Coordinator 4, specialists 6**.

Record the configured per-turn step bound, whose default and maximum are 40, and classify step or
role exhaustion and stale checkpoints as failures. Freeze the SGT clock, because observations
currently derive "today" from wall-clock time. Pin source and approved-instruction results.

Name one authoritative delivery-evidence source: simulator messages label themselves
`displayed_in_simulator`, while the case-view route replaces that field with an outbox-status
lookup. The language gate depends on translation configuration, and stopped contact is checked there
for proactive delivery.

### 3.5 Rubric, decisions and tests

Grade meaning rather than wording; two matching but incorrect runs fail. Preserve the locked human
roles, blind 20% spot-check, model-family separation, Anthropic exclusion and per-variant AI
declarations. Contract tests must reject multiple terminal expectations, illegal task/outcome
combinations, missing source evidence, and scored quarantined strata.

## 4. Acceptance criteria

- Schema validation and contract tests pass for the pilot fixtures, including deliberately invalid
  cases. The projection is deterministic and retains variant-specific language expectations.
- Every graded field has a cited runtime source or is marked **UNVERIFIED**. The map distinguishes
  policy requirements, model instructions and enforced validation.
- The fixture contract names a clock-freezing method and one authoritative delivery observation.
  Until verified, each remains **UNVERIFIED**, never silently inferred.
- The operator checks the policy map against the decision ledger; reviewer-of-record and adjudicator
  responsibilities are represented without assigning either a tuning role.
- Record results for `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` and
  `pnpm --dir apps/web build`. No benchmark score is reported.

## 5. Dependencies, risks and open questions

- **Agent-resolvable:** verify a deterministic clock mechanism and the authoritative delivery-status
  observation. A plausible fixture can otherwise score the wrong date or delivery event.
- **Agent-resolvable:** confirm extraction of terminal outcomes across normal completion and staff
  resolution paths before fixing the projection contract.
- **Needs human decision before corpus production:** approve permitted authorship and licence
  sources. M1 may record `pending`; it must not treat pending rights as approved.
- **Deferred dependency:** the wrong-number and third-party runtime path. Its absence is handled by
  the approved `UNSCORED` rule, not by an invented oracle result.

## 6. Exit condition

M1 is complete when the versioned schema, projection, rubric, decision record, fixture contract and
contract tests agree on every graded runtime meaning, pass the recorded checks, and label every
remaining uncertainty explicitly.

---

## Appendix — citation verification (2026-09-23)

Oracle's substance held; its line numbers drifted by 2–20 lines. Verified corrections:

| Claim | Verified reality |
|---|---|
| `models.py:39` run status | `models.py:41-42` CheckConstraint: `queued`, `running`, `waiting`, `paused`, `escalated`, `completed` — oracle omitted `queued` and `running` |
| `contracts.py:275` MemoryChange | class at 275; `operation: Literal["set","remove"]` at `contracts.py:287`; `scope: Literal["visit","future"]` at `contracts.py:286` |
| `engine.py:1852` completion outcomes | exact: `OWNED_STAFF_HANDOFF` (`CompleteDecision`), `SIMULATED_ATTENDANCE_CONFIRMED` (`CompleteSimulationDecision`) |
| `engine.py:394` "today" | exact: `"today_sgt": utcnow().astimezone(timezone(timedelta(hours=8)))...` |
| `settings.py:39` step bound | exact: `agent_max_steps: int = Field(default=40, ge=4, le=40)` |
| `simulation.py:18` simulator gate | exact: demo clinic id **and** `checkpoint["patient_simulator_enabled"] is True` |
| `engine.py:777` simulator branch | exact: `if simulation_enabled(run):` |
| Failure pauses | `STALE_CHECKPOINT` `engine.py:749-750` and `1993-1994`; `STEP_BUDGET_EXHAUSTED` `engine.py:757`; `ROLE_BUDGET_EXHAUSTED` `engine.py:788` |
| `displayed_in_simulator` | `simulation.py:995`, plus `engine.py:2093` and `engine.py:2123` |
| Route delivery override | `routes.py:264` (`"delivery_status": db.scalar(...)`) |
| Per-question outcome rules | `contracts.py:88` (outcome literal), `contracts.py:136-140` (ANSWERED/GUIDANCE evidence), `contracts.py:238` (InstructionCheckDecision), `questions.py:45-47` (PLAN constraints) |

Not independently re-verified; verify during M1 step 1: `contracts.py:349`, `contracts.py:364`,
`questions.py:13`, `engine.py:981`, `policy.py:389`, `engine.py:682`, `routes.py:387`,
`memory.py:65`, `memory.py:115`, `provider.py:838`, `policy.py:119`, `contracts.py:310`.
