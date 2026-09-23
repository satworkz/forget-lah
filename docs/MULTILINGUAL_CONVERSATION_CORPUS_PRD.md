<!--
Provenance: bounded read-only PRD run of codex `gpt-6-astra` (reasoning effort high),
job `astra-corpus-prd-v2`, 2026-09-23. Final-message sha256
2be41feb78e8adad90db7916cc0e3b1b65784583cfdabf94468dac39ce4aa8fa.
This supersedes an earlier decider-targeted draft; the System One decider was ruled out by
code review because it bypasses every reply-interpretation phase. Status: proposed only.
No corpus, code or deployment exists yet.

Revision 2 (2026-09-23, operator review): corpus size reduced 1,040 -> 520; reviewers,
adjudicator, custodian and test-phone owners agreed; pipeline tuning separated from review;
AI-assistance rules added; a custodian-only acceptance holdout added; wrong-number/third-party
and expected-terminal-outcome policies approved. All decisions resolved. The authoritative
decision record is held with the operator.
-->

# PRD: Synthetic Multilingual Conversation Corpus for forget-lah

**Status:** Proposed (revision 2, 2026-09-23)  
**Target:** Main-model interpreter and conversation pipeline  
**Languages:** English (`en`), Mandarin (`zh`), Malay (`ms`), Tamil (`ta`)

## Goal

Build a reproducible corpus of synthetic, multi-turn patient conversations that measures whether Mandarin, Malay and Tamil produce the same correct conversation state and eventual outcome as semantically equivalent English.

Evaluate through `patient_simulator`. Treat conversation state and the completed run’s outcome—not a decider candidate identifier—as the scoring unit.

## Non-goals

- Reassess the System One decider or its multilingual checkpoint requirements.
- Build appointment management, invent slot availability, provide clinical advice or perform real appointment writes.
- Contact real patients, use real patient records or deploy publicly.
- Add inbound translation. Patient replies remain stored in their original language.
- Treat model output as proof of identity, consent, booking success or authority.

## Assumptions

- The main model interprets replies; the decider bypasses reply-interpretation phases.
- Supported outbound kinds are `reminder`, `options`, `acknowledgement` and `doctor_instruction_check`.
- Language memory contains `preferred_language`, including `und`, and `excluded_languages`. Contact permission is also graded.
- The delivery gate returns `LANGUAGE_SUPPORT_REQUIRED` for unsupported or excluded languages.
- Translation applies only to clinic-to-patient messages.
- Coordinator delegates to Engagement and Preparation. Only Coordinator delegates.
- Existing Tamil live validation demonstrates feasibility, not corpus-level multilingual equivalence.
- Source APIs own appointments; named staff acceptance is required before a handoff is owned.

## Requirements

### 1. Thread and fixture contract

A corpus item is a **thread**, containing at least one clinic turn and one patient turn, with prior history and a fixed reference datetime carrying an explicit SGT offset (`+08:00`). A required subset must contain multiple patient replies separated by clinic turns.

Each aligned family contains four variants sharing one clinic scenario, one canonical history, the same intended meaning at every patient turn and identical external conditions. Only patient wording and language vary. Historical patient turns may be localized; their meaning, order and timing remain fixed.

| Component | Required fields |
|---|---|
| Identity | Corpus version, family ID, variant ID, scenario ID, language, primary stratum, secondary coverage tags |
| Clock and environment | Reference datetime; per-turn time or offset; frozen clock behavior; clinic boundary; synthetic source-API fixtures; deterministic tool results; named staff acceptance fixture where relevant |
| Initial state | Appointment context, conversation phase, existing questions/tasks, language memory, contact permission and relevant prior run state |
| Conversation | Ordered history and replay turns; speaker; clinic-turn kind; raw body; language tags, including mixed or romanised content; turn IDs |
| Meaning contract | Language-neutral intended meaning for every patient turn; unresolved ambiguity; facts the system must not infer |
| Checkpoint oracle | Expected `appointment_intent` (`CONFIRM`, `CANCEL`, `CHANGE`, `UNSPECIFIED`), `patient_questions`, `patient_task_types`, memory updates, translation behavior and delivery gate |
| Terminal oracle | Expected eventual step/outcome, permitted terminal alternatives where genuinely equivalent, forbidden actions and fixture-specific completion bound |
| Governance | Synthetic provenance, authorship/licence, reviewer records, independent back-translation, adjudication status, split and version |
| Integrity | Content hashes for family, variant, oracle, fixture and manifest; generation and replay seeds |

Oracle values must use the runtime’s existing types and semantics. Exact enum mappings, contact-permission semantics and policy-dependent expectations must be approved before fixture lock; they must not be invented during scoring.

Checkpoint expectations must distinguish **no change**, **set**, **clear** and **unknown** where the runtime supports those operations. Expected questions and tasks must encode meaning and disposition rather than require identical generated wording.

Fixture replay must freeze external results, preserve clinic boundaries and prohibit real writes. Uploaded records cannot establish availability. Rules, mocks and live-model events must carry distinct labels.

Scripted clinic turns provide controlled inputs. Any clinic message generated by the evaluated pipeline is an output to score; replay must not silently replace an incorrect generated message with the expected one.

### 2. Scenario coverage

Cover these primary strata in every language:

| Stratum | Required thread behavior |
|---|---|
| Confirmation | Interpret acceptance in context; distinguish intent from a successful booking or write |
| Cancellation | Interpret cancellation, including a later correction or qualification |
| Rescheduling | Interpret change requests without inventing available slots |
| Timing constraints | Resolve relative dates against the fixed SGT clock; preserve restrictions and exceptions |
| Preparation acknowledgement | Distinguish acknowledgement from a question or unresolved instruction check |
| Questions | Preserve patient questions alongside appointment intent and across follow-up turns |
| Wrong number | Exercise the approved memory, contact and routing policy |
| Third-party reply | Preserve uncertainty about identity and authority |
| Refusal/contact-stop | Distinguish refusal of a proposed action from a request to stop contact |
| Ambiguous/very short reply | Use history or seek clarification; do not force an unsupported interpretation |

The **Wrong number** and **Third-party reply** strata are authored but excluded from scoring until the approved routing policy exists in the runtime; they are reported as unscored coverage and must never be reported as passing.

Across these strata:

- Exercise all four clinic-turn kinds and the reply phases `REVIEW_NEEDS`, `CLARIFY`, `ASSESS_BARRIERS`, `REPORT_SYMPTOMS`, `INTERPRET_ATTENDANCE` and `INTERPRET_INSTRUCTION_CHECK` where applicable. Symptom content tests routing, not clinical advice.
- Include corrections, negation, multiple intents, unanswered questions and short replies whose interpretation changes with history.
- Include mid-conversation switches from English to each non-English language, with semantically matching English controls. Mere use of a language must not be assumed to authorize a preference update unless approved policy says so.
- Include explicit language preferences, excluded-language conflicts, unsupported-language requests and contact-permission changes.
- Include untrusted instructions embedded in patient text. They must not override policy, clinic boundaries or tool authorization.

### 3. Sourcing and validation

Carry forward these corpus controls:

- **Synthetic-only provenance:** Record synthetic origin for every scenario, message and fixture.
- **PII prohibition:** Exclude real patient information and real contact identifiers.
- **Authorship/licence records:** Record author or generator, source and approved usage rights.
- **Storage path and Git policy:** Commit development variants and the content-hash manifest to the repository. Keep evaluation variants, expected answers, the acceptance holdout and run traces in restricted storage readable only by the evaluation custodian. Default archive retention is 90 days unless project rules require otherwise.
- **Seeded reproducibility:** Record seeds, generator/model versions, prompts and immutable generated artifacts; seeds alone do not guarantee identical model output.
- **Native review and back-translation:** Require native-speaker review plus independent back-translation and adjudicate discrepancies.
- **Seeds and challenges:** Combine English-seeded aligned families with natively authored challenge threads.
- **Aligned versus independent:** Label aligned families separately from independent items; independent items do not count as paired evidence.
- **Locked split:** Maintain separate development and locked evaluation sets; tuning uses development data only.
- **Singapore register:** Include romanised Tamil, Mandarin/Malay code-switching, Singlish/Manglish particles, emoji, typos and fragments.
- **Adversarial subset:** Label patient-authored instructions as untrusted and test their containment.

Reviewers must confirm semantic alignment, naturalness, contextual ambiguity, cultural/register suitability and oracle correctness. Unresolved disagreements block inclusion in locked evaluation.

#### Roles and separation of duty

| Role | Holder | Constraint |
|---|---|---|
| Reviewer of record `ms` | operator | Human sign-off required |
| Reviewer of record `ta` | Satish | Human sign-off required |
| Reviewer of record `zh` | Bryan | Human sign-off required |
| Final adjudicator | Rohit | Independent of every reviewer; no reviewer adjudicates their own item |
| Evaluation custodian | operator | Sole holder of the locked evaluation set and the acceptance holdout |
| Test-phone owner | operator, Satish, Rohit | Registered test numbers |
| Pipeline tuner | Engineering agents | Development variants only; never receives evaluation or holdout variants |

Reviewers and the adjudicator necessarily see evaluation variants and their expected meanings, so neither may double as the tuner.

#### AI assistance

AI may assist, but it cannot hold a role of record:

- No Anthropic model may participate in generation, back-translation, review or adjudication, because the pipeline under test is Anthropic-backed.
- Any AI that judges a variant must be a different model family from the model that produced it. The back-translator must differ in family from the variant drafter; a same-family round trip is vacuous.
- An AI may pre-screen variants and propose edits to reduce review volume, but may not be the reviewer of record.
- The independent spot-check, performed per language by the reviewer of record, must be blind: the checker must not see the intended meaning before judging the back-translation.
- Every AI contribution is declared per variant in the provenance manifest, naming the model and the step.

#### Custodian-only acceptance holdout

Approximately 20 evaluation variants per language form a custodian-only acceptance holdout drawn from the locked evaluation set:

- Held by the custodian alone; no tuning process and no non-custodian role receives them after lock.
- Reviewed during authoring like other evaluation variants, by reviewers who are not the tuner.
- Reported separately from the wider screened result, so the project retains one acceptance number that cannot have been absorbed into tuning.
- If the wider evaluation set is ever exposed to tuning, only the holdout can still support an acceptance claim.

### 4. Size, stratification and split

The approved initial release contains **520 thread variants**:

| Population | Development | Locked evaluation | Total |
|---|---:|---:|---:|
| Aligned families | 40 families × 4 languages = 160 | 60 families × 4 languages = 240 | 400 |
| Independent native challenges | 10 per language = 40 | 20 per language = 80 | 120 |
| **Total variants** | **200** | **320** | **520** |

This yields **60 locked paired comparisons per non-English language**: English–Mandarin, English–Malay and English–Tamil. Development provides another 40 pairs per language, excluded from release claims. Approximately 80 of the locked evaluation variants form the custodian-only acceptance holdout.

The size was reduced from 1,040 to keep the human review load proportionate. Consequence: the 5% language-regression bound becomes effectively a zero-discordance gate at this size (see Acceptance criteria).

Stratification requirements:

- Each primary stratum receives four development and six evaluation aligned families.
- Independent challenges receive one development and two evaluation threads per stratum, per language.
- At least 30 evaluation families contain two or more patient turns separated by clinic turns.
- Each clinic-turn kind appears in at least 10 evaluation families.
- At least six evaluation families exercise a mid-conversation language switch in each non-English variant.
- At least six evaluation families and two independent evaluation threads per language belong to the adversarial subset.

Secondary tags may overlap. Related templates, paraphrases, challenge derivatives and all family members must remain in the same split. Repeated executions increase reliability evidence, not the number of independent paired comparisons.

### 5. Evaluation and archived evidence

Run every variant through `patient_simulator` from a clean fixture state. Verify delivery events use `displayed_in_simulator`. Fix the model configuration, prompt versions, policy version, fixtures and scoring rules for a benchmark run.

Evaluate two separate properties:

1. **Oracle correctness:** Does each variant reach the approved state at each checkpoint and the approved eventual outcome, without forbidden actions?
2. **Cross-language equivalence:** Does each non-English variant match its English counterpart’s state trajectory and eventual outcome after the approved normalization?

The comparison projection must include intent, question meanings and disposition, task types, memory updates, translation behavior, delivery gates and eventual outcome. Ignore run IDs, incidental timestamps and stylistic response differences.

Locale-specific surface text may differ. Language-memory values and translation targets must be checked against explicit variant expectations, not discarded by normalization. Any permitted language-dependent difference must be declared before evaluation; business outcomes cannot be normalized away.

Grade generated prose for meaning using a locked rubric. Exact typed fields use deterministic comparison. Human adjudication resolves semantic uncertainty; an automated judge alone cannot establish disputed equivalence.

A pair fails if it differs at a required checkpoint, loses a question, applies an incorrect memory update, reaches the wrong gate/outcome, times out or performs a forbidden action. Two equally wrong runs are **equivalent but incorrect** and fail acceptance.

Report by language, stratum, clinic-turn kind, phase and register:

- Complete-thread oracle pass rate and field-level error rates.
- Pair concordance and English-pass/non-English-fail discordance.
- Safety/policy violations, timeouts and reviewer disagreements.
- Failures shared with English, including independent English challenges.

For every scored run, archive:

- Locked corpus manifest, hashes, split and oracle version.
- Raw original patient bodies and observed clinic messages.
- Model, prompt, policy, application and fixture versions; seeds and clock.
- Interpreter outputs, validated proposals, checkpoint snapshots, translation and gate events, delegation/tool events and terminal outcome.
- Rule/mock/live-model labels, scoring output, adjudication and failure classification.

Archives must exclude credentials and real patient data.

### 6. Acceptance criteria

The proposed release gates are:

- **Corpus integrity:** All locked items validate, have complete governance records, pass review and meet coverage requirements; no unresolved split leakage.
- **Policy invariants:** Zero forbidden actions or violations of clinic isolation, identity/authority, contact, availability, handoff ownership or untrusted-instruction policy.
- **Absolute correctness:** At least 95% complete-thread oracle accuracy for each language’s 60 aligned evaluation threads, and separately for each language’s 20 independent evaluation threads.
- **Paired equivalence:** At least 95% full-thread concordance for each non-English language.
- **Language regression bound:** For each language, the one-sided 95% exact binomial upper confidence bound on English-pass/non-English-fail discordance, using all 60 evaluation pairs, must be at most 5%. At this size the bound admits **zero** discordant pairs: 0/60 gives an upper bound of about 4.9%, while a single discordant pair gives about 7.7%. The 95% correctness and equivalence targets are therefore reported as **screening** targets — they indicate whether the pipeline is worth deeper investigation, not a confirmed equivalence claim.
- **Evidence completeness:** Every scored failure has a reproducible trace and an adjudicated or explicitly unresolved attribution.

Aggregate success cannot waive a policy violation. Passing establishes evidence for the covered distribution, not universal language support or equivalence in every individual stratum.

## Alternatives

| Alternative | Decision |
|---|---|
| Isolated translated replies | Reject: omit history, corrections, state accumulation and eventual outcomes |
| Decider candidate scoring | Out of scope: this corpus targets interpretation and pipeline behavior |
| Translation-only aligned corpus | Insufficient: retain native challenges to expose unnatural phrasing and register gaps |
| Independent native threads only | Insufficient: retain aligned families for controlled language comparisons |
| WhatsApp-first evaluation | Reject: simulator provides controlled replay; use WhatsApp only for final delivery verification |
| Inbound translation before interpretation | Defer: changes the system under evaluation and does not match the current raw-inbound design |

## Milestones + Acceptance

| Milestone | Deliverable | Acceptance |
|---|---|---|
| M1: Contract and policy mapping | Schema, comparison projection, oracle rubric, fixture contract and approved decisions | Every graded field maps to actual runtime semantics; unsupported policy assumptions are resolved |
| M2: Development pilot | Twenty aligned development families, two per stratum | All variants reviewed; replay demonstrates checkpoint grading, ambiguity and language switching |
| M3: Corpus completion and lock | Full 520-variant release, review records and split manifest | Counts, coverage, hashes and leakage checks pass; evaluation access is controlled |
| M4: Simulator benchmark | Locked evaluation report and complete evidence archive | All release gates assessed; failures separated into language-specific, shared and unresolved causes |
| M5: Delivery verification | Small signed `whatsapp_test` round trip using operator-approved test phones | Outbound language rendering and raw inbound preservation verified; channel failures reported separately |

For changes to the project, require `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` and `pnpm --dir apps/web build`. PostgreSQL concurrency coverage remains skipped without `TEST_DATABASE_URL`; SQLite results do not establish PostgreSQL locking behavior. Schema changes require new migrations.

## Rollout-Exit

Develop and tune against development threads, then freeze the implementation and run locked evaluation. Evaluation exposure must be recorded; a set used for tuning cannot remain an untouched acceptance holdout.

Issue one of these conclusions per non-English language, with a separate shared-defect finding when applicable:

| Conclusion | Required evidence and action |
|---|---|
| **Pipeline handles zh/ms/ta equivalently** | The named language passes correctness, equivalence and policy gates. Claim all three only if all three pass. Complete the final test-phone delivery check before closing validation. |
| **Interpreter needs work per language** | English succeeds and adjudicated traces locate a language-dependent error in interpretation. Identify affected languages and fields; fix using development cases and re-evaluate on an untouched holdout. |
| **General pipeline defect unrelated to language** | English and non-English runs fail, and traces establish a shared policy, state-transition, fixture or tool-path defect. Correct the shared defect before making an equivalence claim. |

Shared failures alone do not prove a language-independent cause. A translation or delivery defect following correct interpretation is a language-specific pipeline defect, not an interpreter defect. Unresolved attribution yields **inconclusive**, blocks acceptance and requires investigation.

Simulator scores determine conversation correctness. `whatsapp_test` verifies delivery only and cannot repair or substitute for failed benchmark results. Exit produces a versioned corpus, evidence archive and explicit acceptance decision; it does not authorize public deployment or real-patient contact.

## Decisions

Operator decisions agreed on 2026-09-23. The authoritative decision record is held with the operator.

| Topic | Decision |
|---|---|
| Runtime vocabulary | Use actual runtime types, not invented labels: patient tasks `QUESTION`/`PLAN`; question outcomes `ANSWERED`/`GUIDANCE`/`NOT_REQUIRED`/`CLINIC_REVIEW`/`UNSUPPORTED`; appointment intent `CONFIRM`/`CANCEL`/`CHANGE`/`UNSPECIFIED`; instruction checks `MET`/`NOT_MET`/`UNCLEAR`. |
| Language preference semantics | A language switch alone changes no lasting preference. Only an explicit request sets one; a clear comprehension repair may set a visit-only language. |
| Corpus size and gates | **520 variants** (200 development, 320 locked evaluation), with ~20 evaluation variants per language held as the custodian-only acceptance holdout. The 5% regression bound is reported as a screening target. |
| Reviewers and rights | Original synthetic text only. Reviewer of record per language (operator `ms`, Satish `ta`, Bryan `zh`); final adjudicator Rohit; independent AI back-translation with a blind 20% human spot-check; unresolved items are excluded from locked evaluation. |
| Storage, retention and access | Development variants and the hash manifest in the repository; evaluation variants, expected answers, the holdout and run traces in restricted custodian-held storage; 90-day retention unless project rules require otherwise. |
| Model and replay pinning | Pin model IDs, prompt and code revision, the reference clock and fixture results. One declared run per variant; reruns for diagnosis only. Fresh variants if tuning followed evaluation exposure. |
| Fixtures and test phones | Engineering owns the source-API and staff-acceptance fixtures; test-phone owners are operator, Satish and Rohit; the signed `whatsapp_test` round trip verifies delivery only. |
| Tuning separation | The engineering agents tune on development variants only and never receive evaluation or holdout variants. Reviewers and the adjudicator see expected meanings, so neither may double as the tuner. |

### Wrong-number and third-party policy (approved)

A reply from an unverified third-party sender is not treated as the patient. The runtime must quarantine the send and disclose nothing, change no memory and no appointment, and flag the thread for staff verification.

No dedicated runtime path exists today. Until it does, the **Wrong number** and **Third-party reply** strata are authored but excluded from scoring and reported as unscored coverage; they must never be reported as passing.

### Expected terminal outcome and step bounds (approved)

Every scenario declares exactly one correct terminal outcome at authoring time.

- `waiting` is correct only for scenarios authored as waiting scenarios; elsewhere it is a failure.
- A handoff counts as success only after named staff acceptance; an unowned escalation is a failure.
- Step-budget exhaustion is always a failure — `agent_max_steps` (default 40, `settings.py:39`) or the simulator role limit (8 for Coordinator, 6 otherwise, `engine.py:784`).
- `CLINIC_REVIEW` and `UNSUPPORTED` are correct only where the scenario expects them.
- The code's bounds are recorded in provenance and are not raised per scenario.

## Remaining approvals

- Permitted authorship and licences for each source, and any stricter per-stratum release gate the operator wants to add.
- Benchmark ownership and the replacement-holdout procedure.
