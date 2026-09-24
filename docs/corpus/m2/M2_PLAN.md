# M2 plan — development pilot

**Milestone.** Programme PRD M2: *twenty aligned development families, two per stratum*. Acceptance:
all variants reviewed; replay demonstrates checkpoint grading, ambiguity and language switching.

## Matrix

Ten strata × two families = **20 families**. An aligned family has **four variants** (en, zh, ms, ta),
so the pilot is **80 variants**. All are `split: development`; evaluation and holdout are out of scope
here.

| Stratum | Family A | Family B |
|---|---|---|
| confirmation | confirm offered slot + preparation question | confirm with a later qualification |
| cancellation | cancel the appointment | cancel then correct/qualify |
| rescheduling | move to a named later date | move request with no available slot in source |
| timing_constraints | relative date resolved against the frozen SGT clock | excluded weekday/time restriction preserved |
| preparation_acknowledgement | acknowledge preparation instruction | acknowledgement containing a new question |
| questions | answerable question from approved sources | unresolved question → authored escalation |
| wrong_number | reply from a non-patient sender | second sender after a wrong-number flag |
| third_party_reply | third party replying for the patient | third party asserting authority |
| refusal_contact_stop | refuse a proposed action (not a stop) | explicit request to stop contact |
| ambiguous_short_reply | bare acknowledgement after options | short reply whose meaning needs history |

At least one family per language pair exercises a mid-conversation **language switch** with a
semantically matching English control (register markers may include `code_switching`, `manglish`,
`romanised_tamil`).

## Authoring rules

- Each variant is a single item conforming to `corpus/schema/corpus.schema.json` (revision 3) and must
  pass `tests/test_corpus_contract.py` before it enters the pilot.
- Aligned members share `family_id`, scenario, clinic turns, intended meaning, fixtures and oracle;
  only `language`, `variant_id`, patient wording, language tags and language-dependent expectations
  differ (rule R37).
- Development variants and the hash manifest live in the repository (decision D5). Evaluation
  variants, expected answers and run traces stay in custodian-held storage.
- Rights: sources are original synthetic text; the licence field records `original_synthetic` for the
  pilot until the operator's authorship approval lands. Pending is never treated as approved.
- AI drafting is declared per variant (`governance.ai_declarations`, non-Anthropic family); the
  reviewer of record is human and per language.

## Not claimable by authoring alone

| Gate | Why it blocks |
|---|---|
| Human review per language | Reviewer of record: operator `ms`, Satish `ta`, Bryan `zh` (D4). The pilot is **not accepted** until each variant is reviewed. |
| Replay demonstration | Requires an execution harness that replays a variant from a frozen fixture state and emits checkpoint evidence. It does not exist yet. |
| Contract enforcement | Every item is machine-checked here; R10/R27/R34 remain oracle/harness obligations. |

## Artifacts

| Path | Contents |
|---|---|
| `corpus/development/pilot/*.json` | the emitted variants |
| `corpus/development/pilot/manifest.json` | family → variants, per-item sha256, counts |
| `corpus/development/build_pilot.py` | the authoring generator (single source for the pilot) |
| `tests/test_corpus_contract.py` | validates every emitted item against schema + R1–R37 |

## Delivery status (tranche 1)

Tranche 1 emits the **family A** row of every stratum: **10 families / 40 variants**, produced by
`corpus/development/build_pilot.py` and validated by the contract suite. Tranche 2 adds the
**family B** row (10 more families / 40 variants) on the same generator.

Still not claimable by authoring alone: human review per language, and the replay demonstration
(no execution harness exists yet).
