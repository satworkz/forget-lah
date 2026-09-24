# M1 oracle rubric

**Purpose.** Govern *meaning* judgments for the multilingual conversation corpus. Exact typed fields
are compared deterministically; generated prose is graded for meaning by a human reviewer against
this rubric. The rubric must not invent runtime semantics — every graded field traces to
`runtime_semantics_map.md` and the versioned schema.

**Authority order.** (1) the runtime's actual behaviour, cited in the map; (2) the versioned schema
and its cross-field rules; (3) this rubric; (4) reviewer judgment. Where the map labels a behaviour
**UNVERIFIED** or policy-dependent, the oracle grades the *approved policy*, never an assumption that
the code guarantees it.

## 1. Two grading tracks

| Track | Applies to | Method | Automation |
|---|---|---|---|
| **Deterministic** | Enum and typed fields: `appointment_intent`, task `task_type`/`outcome`, instruction-check `outcome`, `attendance_qualification.status`, memory `operation`/`scope`/`expected_status`, gate fields, the single terminal expectation, forbidden actions | Exact comparison after the approved projection (`forget_lah.corpus.comparison_projection`) | Fully automated |
| **Semantic** | Generated patient-/clinic-facing prose whose *meaning* is required (answer correctness against approved source text, acknowledgement vs question, ambiguity resolution) | Human reviewer of record against this rubric; AI may pre-screen but **cannot** adjudicate | Human, with blind 20% spot-check |

A run is only gradeable when both tracks pass. An automated judge alone cannot establish disputed
equivalence.

## 2. What is graded

Per the programme PRD §5 and M1 PRD §3.3, the comparison surface is: **intent; question meanings and
disposition; task types; instruction checks; memory updates; translation and delivery-gate
behaviour; and the eventual outcome**, plus forbidden actions. Incidental run IDs, timestamps and
stylistic wording are excluded by the projection.

**Pair rule.** A pair fails if it differs at a required checkpoint, loses a question, applies an
incorrect memory update, reaches the wrong gate or outcome, times out, or performs a forbidden
action. Two equally wrong runs are **equivalent but incorrect** and fail acceptance.

## 3. Memory grading

- Absence of a key in a checkpoint means **no change**.
- `operation: "remove"` is the runtime delete behind the programme PRD's loose word "clear"; it
  writes a retracted row rather than deleting history.
- There is no runtime "unknown" write. An oracle-unknown is an annotation, never projected as a
  memory update.
- **A language switch alone is not a lasting preference.** Only an explicit request sets one; a
  comprehension repair may set a **visit-only** language (D2).
- The runtime validates a supporting quote and language-tag shape; that does **not** prove the
  preference is policy-correct. The oracle grades the policy, not the validator.

## 4. Worked ambiguity examples

Each example states the surface, the wrong reading an automated judge is likely to take, and the
rubric-correct grading.

**W1 — "ok, can I send my son?" (short reply that may be a question).**
Wrong reading: treat "ok" as acceptance of the offered slot and ignore the second clause.
Correct: the clause is an **attendance-qualification** question. Grade `attendance_qualification`
interaction and a possible demotion of `appointment_intent` back to `UNSPECIFIED`
(`engine.py:135-160`); do **not** grade a booking. The reply must not be scored as a confirmation
when qualification is unresolved.

**W2 — bare "ok" after clinic options.**
Wrong reading: force `INTERPRET_SELECTION` and credit a slot choice.
Correct: selection requires a *selection*. With no identifying content, the correct behaviour is to
use history or seek clarification (`CLARIFY`); a forced selection is a failure even if the chosen
slot happens to match.

**W3 — mid-thread language switch (English → Tamil) with no explicit request.**
Wrong reading: record a lasting `preferred_language` change.
Correct: a switch alone changes no lasting preference. A comprehension repair may set a **visit-only**
language; a `future`-scope preference without an explicit request is an incorrect memory update.

**W4 — "actually don't cancel it, move it to Friday".**
Wrong reading: grade the thread as a cancellation (first intent wins).
Correct: the graded checkpoint intent is **`CHANGE`**. The earlier CANCEL is not the outcome; neither
is a new booking. "Move it" must not invent an available slot.

**W5 — a clinical question the approved sources cannot answer.**
Wrong reading: `UNSUPPORTED` ("the sources don't cover it").
Correct: `UNSUPPORTED` is valid only for a **non-clinical operational fact** absent from the approved
sources (`provider.py:857`). A clinical test, medication, procedure or preparation question is
`CLINIC_REVIEW`, raising a callback — not `UNSUPPORTED`.

**W6 — a relative date ("tomorrow") against the frozen clock.**
Wrong reading: compare the token "tomorrow".
Correct: grade the **resolved SGT date** against `frozen_date`, plus any preserved restriction or
exception. Prose wording is incidental.

**W7 — a correct translation that is semantically wrong.**
Wrong reading: pass because the target-language string is fluent and on-topic.
Correct: agreement means agreement with the authored semantic oracle. **Identical mistranslations
still fail.** A wrong-target-language output, an incomplete translation, or missing required
delivery fails the repetition; `TRANSLATION_VALIDATION_FAILED` is always FAILED and is never
replaced.

**W8 — an unaccepted escalation authored as the scenario's ending.**
Wrong reading: escalation is always failure, or a handoff without acceptance is success.
Correct: if the scenario authors `terminal_oracle.kind: escalated` as its single accepted outcome,
grade it as PASS **only** for an unaccepted handoff (see A1: `outcome: null`, matching evidence with
null `accepted_by`/`accepted_at`, `callback_requested: true`, `CLINIC_REVIEW` task, no
`staff_acceptance`). An escalation the scenario did **not** author remains a failure, and an
*accepted* handoff there is also a failure.

## 5. Reviewer duties and record

- The **reviewer of record is a human** per language (D4): operator `ms`, Satish `ta`, Bryan `zh`.
  Final adjudication is Rohit's. AI may draft, back-translate and pre-screen, but may not review or
  adjudicate, and no Anthropic model may appear in corpus-generation roles.
- Non-English variants are reviewed against the **English counterpart's meaning** under the approved
  projection, with language-dependent paths declared by `LANGUAGE_DEPENDENT_PATHS` (D2, A2). Business
  outcomes are never normalised away.
- Every graded run records: rubric version, the projection version, the reviewer, the per-field
  result, and a `grade: PASS | FAILED | UNSCORED` with the unresolvable reason when UNSCORED.
- **UNSCORED earns no passing credit** and satisfies no coverage quota. Wrong-number and
  third-party families (D9) cannot count toward a claimed 0/60 regression gate; report the actual
  denominator and leave the gate unmet when fewer than 60 eligible pairs exist.
- `TRANSLATION_VALIDATION_FAILED`, incomplete translation, semantic corruption, wrong target
  language, missing required delivery and system-caused worker interruption are **failures of the
  system under test**, never unscored and never replaced.

## 6. Locking

The rubric is versioned with the corpus contract. Any change after evaluation exposure invalidates
the affected locked items; the decision record, not the rubric, governs policy. Tuning uses
development variants only (D8).
