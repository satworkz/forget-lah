# M1 fixture contract

**Purpose.** Specify the isolated simulator inputs a corpus item runs against, and the evidence
captured from that run, so a replay is deterministic, clinic-scoped and write-free. Field names
match `corpus/schema/corpus.schema.json`; semantics trace to `runtime_semantics_map.md`.

## 1. Clinic identity and the simulator gate

Both are required; either alone is insufficient (`simulation.py:18-20`):

- `environment.clinic_id` = the runtime **DEMO_CLINIC_ID** `10000000-0000-4000-8000-000000000001`
  (`source.py:8`), and
- `environment.patient_simulator_enabled` = `true`, set on `checkpoint["patient_simulator_enabled"]`.

When the gate is false the simulator path and the 8/6 role limits do not apply and the runtime yields
4/6 (`engine.py:786`). `environment.is_demo_clinic` must therefore be `true` wherever the recorded
`runtime_bounds` are the simulator values.

## 2. Clock

The runtime derives "today" from the wall clock (`engine.py:394`, `today_sgt`), and `utcnow` is a
free function with **no override seam** (`db.py:20`). Freezing therefore requires one of:

1. monkeypatch `forget_lah.db.utcnow` in-process for the run (preferred for isolated replay), or
2. add an explicit injectable seam (a code change, tracked separately).

The fixture records:

- `clock.reference_datetime` — fixed instant with an explicit `+08:00` offset;
- `clock.frozen_date` — the SGT calendar date the fixture injects in place of `utcnow()`, which must
  equal `reference_datetime`'s SGT date;
- `clock.per_turn_offset_minutes` — optional per-turn offsets, in turn order.

A run that reads the host clock is **not** reproducible and must not be scored.

## 3. Source and instruction fixtures

- `environment.fixtures.source_api` — frozen, deterministic tool results. **Uploaded records must
  never establish availability.** The runtime owns appointment truth through authorized APIs; a
  bridge clinic owns approved follow-up episode state in Forget-lah Bridge tables under the same
  logical source interface, and Bridge must never read or modify mock-clinic tables.
- `environment.fixtures.approved_instructions` — approved instruction text. `ANSWERED`/`GUIDANCE`
  quotes must be substrings of the referenced `approved_text` (`questions.py:49-54`), so this text is
  part of the oracle surface, not decoration.
- Fixture content is identical across the variants of one aligned family; only language and patient
  wording vary.

## 4. Staff events

- `environment.fixtures.staff_acceptance` — named acceptance records (`handoff_id`, `accepted_by`,
  `accepted_at`). A `CompleteDecision` handoff requires **both** `accepted_by` and `accepted_at`
  (`policy.py:400`).
- An **unaccepted** handoff (the authored `escalated` outcome, A1) requires `accepted_by: null` and
  `accepted_at: null`, and the matching `handoff_evidence` must carry clinic/case/run identity.
- A handoff is owned **only** after named staff acceptance; an unowned escalation is not success.

## 5. Delivery evidence (one authoritative source)

On a simulator run there is exactly one non-null delivery observation:

- `ChannelOutbox` is constructed only for a bound WhatsApp channel (`channel.py:523`), so the
  case-view route's outbox lookup returns `None` for every simulated message (`routes.py:264`);
- the simulator label `"delivery_status": "displayed_in_simulator"` (`simulation.py:995`,
  `engine.py:2093`, `engine.py:2123`) is therefore authoritative.

`environment.delivery_evidence_source` is `displayed_in_simulator`, and each checkpoint records the
expected per-message value in `delivery.expected_message_delivery`. Stopped-contact and language
gates are checked on this same path, so a stopped/hold result is captured as a gate outcome, not
silently dropped.

## 6. Translation gate

`translation_configured` is the derived gate (`settings.py:20-25`):

```python
multilingual_enabled and agent_model_mode == "anthropic" and model_configured
```

The fixture pins the component settings and the derived value; a change in any component changes the
graded outcome. The runtime-under-test role for an Anthropic-backed translator is recorded in
`environment.translation_profile` (A2). Anthropic remains forbidden for **corpus** drafting,
back-translation, pre-screening, review or adjudication.

## 7. Bounds

Recorded, not authored:

- per-turn step bound `runtime_bounds.agent_max_steps`, default **40**, `ge=4 le=40`
  (`settings.py:39`), measured from `checkpoint["turn_start_step"]` (`engine.py:753-757`);
- role limits: **simulator 8 Coordinator / 6 specialist** (`engine.py:784`); non-simulator
  **4 / 6** (`engine.py:786`).

Step exhaustion, role exhaustion and stale checkpoints are always failures, never authored outcomes.

## 8. Write boundaries and isolation

- Replay runs the **simulator path only**. No real WhatsApp/outbound send; no approved-template
  delivery; no public deployment; no real-patient contact.
- No source writes and no mock-clinic-table writes from a Bridge clinic. Uploaded records cannot
  invent availability.
- Clinic boundaries are enforced in database relationships and request queries.
- Credentials and real patient data never enter the repository, fixtures or logs.
- Each variant runs from a **clean fixture state**; the model, prompt, policy and fixture versions
  are fixed for the experiment.

## 9. Labels

Every event the oracle grades carries its origin: **rule**, **mock**, or **live-model**. No simulated
integration is labelled live. Scripted clinic turns are controlled inputs; a clinic message generated
by the evaluated pipeline is an output to score and is never silently replaced by the expected one.

## 10. Evidence archive

For every scored run, capture (programme PRD §5):

- locked corpus manifest, hashes, split and oracle version;
- raw original patient bodies and observed clinic messages;
- model, prompt, policy, application and fixture versions; seeds and clock;
- interpreter outputs, validated proposals, checkpoint snapshots, translation and gate events,
  delegation/tool events, and the terminal outcome;
- rule/mock/live labels, scoring output, adjudication record and failure classification.

Archives exclude credentials and real patient data. Retention and access follow D5.
