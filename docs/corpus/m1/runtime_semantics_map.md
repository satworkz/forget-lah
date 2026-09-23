# Runtime semantics map — graded fields for the conversation corpus

**Milestone:** M1 · **Status:** Draft for standup review · **Date:** 2026-09-23
**Revision 2** — corrected against the first independent review. See §13 for what changed and why.
**Purpose:** record what the runtime *actually does* for every field the corpus intends to grade,
so the schema, projection and oracle are built on verified semantics rather than on the programme
PRD's prose.

**Citation convention.** Every claim cites `file:line`. A claim marked **UNVERIFIED** was not
confirmed by reading and must not be relied on until it is. Anything not cited is a statement about
the corpus, not about the code.

**Source revision:** `origin/main` @ `880da93` (branch `feat/multilingual-corpus-contract`).

---

## 1. The single most important correction

The programme PRD blurs two different vocabularies. They must be separate fields in the schema:

| | What it grades | Runtime source |
|---|---|---|
| **Per-question outcome** | one patient question/plan task | `contracts.py:88` — `ANSWERED`, `GUIDANCE`, `NOT_REQUIRED`, `CLINIC_REVIEW`, `UNSUPPORTED` |
| **Run terminal state** | the whole conversation | `run.status` (`models.py:39-41`) **plus** `checkpoint["outcome"]` (written only at `engine.py:1853`, `1856`) **plus** `checkpoint["wait_reason"]` (`engine.py:1825`) for a waiting run |

`ANSWERED`/`GUIDANCE`/… answer *"what happened to the patient's question"*. They do not say the
conversation finished, and a run can hold several of them at once — one per task. Treating them as
thread outcomes (as the PRD's wording invites) would grade the wrong object.

---

## 2. Run terminal state

**Run status** — `models.py:39-41` (literal at `:40`), CHECK constraint:
`queued`, `running`, `waiting`, `paused`, `escalated`, `completed`

**Checkpoint outcome** — only **two** values are ever written to `checkpoint["outcome"]`:

| Value | Written at | Meaning |
|---|---|---|
| `OWNED_STAFF_HANDOFF` | `engine.py:1853` | completed via `CompleteDecision` |
| `SIMULATED_ATTENDANCE_CONFIRMED` | `engine.py:1856` | completed via `CompleteSimulationDecision` |

**A waiting run has no outcome.** `WAITING_FOR_CLARIFICATION` is **not** a checkpoint value: it is a
literal inside the clarification message's `evidence` dict (`engine.py:1817-1822`). The waiting path
writes `checkpoint["wait_reason"] = "AWAITING_PATIENT_REPLY"` and releases the run as `waiting`
(`engine.py:1825-1826`), so `checkpoint["outcome"]` stays `None` — which is exactly what the run
payload reports (`routes.py:163`). **`wait_reason` is the field that distinguishes a waiting run.**

`wait_reason` values observed in the runtime:

| Value | Site |
|---|---|
| `AWAITING_PATIENT_REPLY` | `engine.py:1111`, `:1152`, `:1247`, `:1359`, `:1399`, `:1522`, `:1825` |
| `CONTACT_STOPPED` | `engine.py:1023` |
| `AWAITING_LANGUAGE_PREFERENCE` | `engine.py:1031` |
| `ATTENDANCE_QUALIFICATION` | `engine.py:1076` |
| delivery block | `engine.py:554` |

**Escalation is a real terminal status, not an edge case.** `request_handoff` releases the run as
`escalated` (`engine.py:200-215`) and is reachable from an unresolved question (`engine.py:1728`),
no available slots (`:2159`), cancellation (`:1054`) and explicit escalation (`:1828`);
`routes.py:454` and `:485` also release to `escalated`. A scenario whose question cannot be answered
therefore ends `escalated`, **not** `waiting` and **not** `completed`. The schema must be able to
express this, and whether it counts as the scenario's single accepted outcome is a policy call —
see §12.

**Failure/pause codes** (`pause()` at `engine.py:115`):

| Code | Site | Approved policy #4 |
|---|---|---|
| `STALE_CHECKPOINT` | `engine.py:749-750`, `1993-1994` | failure |
| `STEP_BUDGET_EXHAUSTED` | `engine.py:757` | failure |
| `ROLE_BUDGET_EXHAUSTED` | `engine.py:788` | failure |

These are stored as `checkpoint["pause_reason"]` (`engine.py:116`) and surfaced at `routes.py:162`.
The schema's `failure_code` is a **projection name** for that field, not a runtime spelling.

**Completion gates** (`policy.py:381-403`) — a scenario may not treat completion as the expected
outcome unless its fixture satisfies these:

- Only the Coordinator may complete: `ONLY_COORDINATOR_CAN_COMPLETE` otherwise.
- `CompleteDecision` requires a `StaffHandoff` with **both** `accepted_by` and `accepted_at`
  (`policy.py:400`); otherwise `OWNED_HANDOFF_EVIDENCE_MISSING`. This is the runtime form of
  "a handoff succeeds only after named staff acceptance".
- `CompleteSimulationDecision` requires the coordinator and that the decision's evidence ids equal
  `simulation_evidence(...)["complete_evidence_ids"]` (`policy.py:385`), namely source receipt plus
  simulated delivery.

**Consequence for the schema:** the expected terminal outcome is not one enum. It is
`(run.status, checkpoint.outcome | wait_reason | pause_reason)` — plus, for handoff, a
fixture-supplied staff-acceptance record. The PRD's "permitted terminal alternatives" must be
deleted: the accepted policy is exactly **one** expected end state per scenario.

---

## 3. Checkpoint state and where it comes from

Written by `apply_control` on a `NeedsDecision` (`engine.py:981-990`):

| Checkpoint field | Source | Note |
|---|---|---|
| `patient_questions` | `decision.patient_questions + decision.preparation_plans` | one **combined** ordered list (`engine.py:986`) |
| `patient_task_types` | `["QUESTION"]*len(patient_questions) + ["PLAN"]*len(preparation_plans)` | index-aligned with the list above (`engine.py:987-988`) |
| `appointment_intent` | `decision.appointment_intent` | |
| `needs_reviewed` | `decision.reply_event_id` | |
| `callback` | set later at `questions.py:111-120` when any question is unresolved | `status: "requested"` |
| `wait_reason` | waiting paths | see §2 |
| `outcome` | completion paths only | see §2 |

**`QUESTION`/`PLAN` are positional, and the ordering is fixed.** `QUESTION` ≡ an entry in
`patient_questions`; `PLAN` ≡ an entry in `preparation_plans` (`contracts.py:350`, `:355`). Because
the runtime concatenates the two lists (`engine.py:986-988`), it can only ever emit **all QUESTIONs
followed by all PLANs** — a `PLAN, QUESTION` interleave is unrepresentable. The schema should say so
rather than let authors assign task types by hand.

---

## 4. Per-question outcomes

Literal at `contracts.py:88`; evidence rules at `contracts.py:136-140`; validation at
`questions.py:45-73`; the model-facing rules are stated at `provider.py:856-860`.

| Constraint | Site | Schema consequence |
|---|---|---|
| Every stored task must be answered, indices exactly `0..n-1` | `questions.py:16-17` | oracle must supply one answer per task; `QUESTION_COVERAGE_INCOMPLETE` otherwise |
| `PLAN` may only be `GUIDANCE` or `NOT_REQUIRED` | `questions.py:45-46` | reject other combinations at authoring |
| `GUIDANCE`/`NOT_REQUIRED` require `PLAN` | `questions.py:47-48` | symmetric rule |
| `ANSWERED`/`GUIDANCE` need `instruction_id` **and** a non-empty quote | `contracts.py:136-140` | |
| the quote must be a substring of the **approved instruction text** | `questions.py:49-54` | cannot be graded against free prose |
| `GUIDANCE` also needs a matching `INFORMATION` item in `scheduling_review` | `questions.py:55-60` | |
| **`GUIDANCE` requires `practical_issue` and `dependency`** | `provider.py:859` | both absent from the schema today |
| `CONFLICTS` must include `FOLLOW_CLINIC_INSTRUCTION` | `questions.py:63-64`, `provider.py:859` | |
| `POSSIBLE_SUBSTITUTION` needs `CONTACT_CLINIC` or `FOLLOW_CLINIC_INSTRUCTION` | `questions.py:65-68`, `provider.py:859` | |
| `OFFER_RESCHEDULE` requires `appointment_intent` in `{CONFIRM, CHANGE}` | `questions.py:69-73` | |
| actions are bounded to `FOLLOW_CLINIC_INSTRUCTION`, `ARRANGE_ASSISTANCE`, `CONTACT_CLINIC`, `OFFER_RESCHEDULE` | `provider.py:859` | |
| an unresolved question defaults to `CLINIC_REVIEW` and raises a callback | `questions.py:85`, `106-120` | `CLINIC_REVIEW` is the fallback, so it is a *plausible* end state, not necessarily a correct one |

`UNSUPPORTED` is the sanctioned answer **only** for a non-clinical operational fact the clinic sources
cannot answer (`provider.py:857`). Clinical tests, medication, procedures and preparation without an
approved answer still take `CLINIC_REVIEW` (`provider.py:857`).

---

## 5. Instruction checks

`contracts.py:238` (`InstructionCheckDecision`); protocol at `contracts.py:593-598`:
`MET` | `NOT_MET` | `UNCLEAR`, each with `answer_quote` bound to the doctor-instruction question
message. `NOT_MET` combined with a requirement whose `if_not_met == "CLINIC_REVIEW"` routes to
review (`engine.py:1363`).

---

## 6. Appointment intent

`contracts.py:364`: `Literal["UNSPECIFIED", "CHANGE", "CONFIRM", "CANCEL"]`, default `UNSPECIFIED`.

- Non-`UNSPECIFIED` **requires** a supporting quote (`contracts.py:384-385`) —
  `appointment_request_quote`.
- `attendance_qualification` is valid **only** with `CONFIRM` (`contracts.py:386-389`), and its own
  `status` resolves to `CONFLICT`, `COMPATIBLE` or `UNRESOLVED`, which can **demote**
  `appointment_intent` back to `UNSPECIFIED` (`engine.py:135-160`, `:1058-1076`). The schema
  currently leaves `attendance_qualification` an untyped object with no expected status.
- Plain attendance refusal is `CHANGE`; cancellation is `CANCEL`; neither is a patient question
  (`contracts.py:358`).

---

## 7. Memory semantics

`MemoryChange` — `contracts.py:275`; `scope` at `:286`; `operation` at `:287`.

| Aspect | Runtime behaviour | Site |
|---|---|---|
| keys | `excluded_weekdays`, `excluded_minutes`, `preferred_language`, `excluded_languages`, `contact_permission`, `arrival_support`, `other_concern` | `contracts.py:276-284` |
| `scope` | `visit` or `future` | `contracts.py:286` |
| `operation` | `set` or `remove` (default `set`) | `contracts.py:287` |
| `remove` + `contact_permission` | **rejected** — "Contact permission requires explicit simulator control to resume" | `contracts.py:292-294` |
| one change per key per decision | enforced | `contracts.py:382-383` |
| `set` supersedes older rows; `remove` retracts them | `row.status = "superseded" if set else "retracted"` | `memory.py:74` |
| new-row status | `retracted` for remove; else `pending` for `arrival_support`/`other_concern` or value `und`; else `active` | `memory.py:87-91` |
| `future` records are cross-case; `visit` records are case-bound | `records_for` filter: `scope == "future"` **or** `case_id == case.id` | `memory.py:17-18` |
| `effective_memory` merges `future` then `visit` (visit wins), excludes `other_concern`, keeps last 3 as `reported_concerns` | | `memory.py:42-56` |

**Corrections this forces on the programme PRD:**

1. The PRD's word **"clear"** is not a runtime operation. The operation is `remove`, and it works by
   writing a new row with status `retracted` — nothing is deleted. `memory.py:74`, `:87-88`.
2. The approved "**visit-only** language" rule maps onto the existing `scope: "visit"` field
   (`contracts.py:286`), and visit-scoped memory is naturally case-bound (`memory.py:17-18`). No
   new field is needed.
3. `contact_permission` cannot be unset by the model at all (`contracts.py:292-294`), so no scenario
   may expect the conversation to clear a contact stop.

---

## 8. Delivery gate and translation

`delivery_block` — `memory.py:115-123`:

- `proactive` + `contact_permission == "stopped"` → `CONTACT_STOPPED` (`memory.py:117-118`).
- language defaults to `en`; **supported set is `{en, zh, ms, ta}` only when
  `settings.translation_configured`**, otherwise `{en}` (`memory.py:119-120`).
- unsupported or excluded language → `LANGUAGE_SUPPORT_REQUIRED` (`memory.py:121-122`).

**`translation_configured` has its own gate** (`settings.py:20-25`), and it is narrow:

```python
multilingual_enabled and self.agent_model_mode == "anthropic" and self.model_configured
```

**Consequence 1 (fixtures).** The gate is configuration-dependent: the fixture must pin
`translation_configured`, or the same scenario yields different graded outcomes.

**Consequence 2 (this needs a decision).** The supported-language set opens for `zh`/`ms`/`ta`
**only when the runtime is in `agent_model_mode == "anthropic"`**. The corpus rules forbid Anthropic
models in *corpus generation and review*, which is a different thing from the *runtime under test* —
but it means the multilingual delivery path cannot be exercised in a non-anthropic runtime at all.
How the zh/ms/ta delivery path is to be exercised is therefore a **human decision**, not a code
discovery. See §12.

Acknowledgement strings exist for `zh`/`ms`/`ta` (`memory.py:126-132`), and a trilingual language
question at `memory.py:135-137`.

---

## 9. Delivery evidence — resolved, and the premise was wrong

The earlier draft of this section claimed two sources "disagree by construction". **That was wrong.**
Corrected:

- `ChannelOutbox` is constructed in exactly one place, `channel.py:523`, and only for a bound
  WhatsApp channel.
- A patient-simulator run creates **no** `ChannelOutbox` row, so the route's lookup
  (`routes.py:264`, `select(ChannelOutbox.status).where(message_id == m.id)`) returns `None` for
  every simulated message.

There is therefore no competing value to reconcile for this corpus: the outbox lookup is simply
`None`, and the simulator label `"delivery_status": "displayed_in_simulator"` (`simulation.py:995`,
`engine.py:2093`, `engine.py:2123`) is the **only non-null delivery evidence** available on a
simulated run. The fixture contract should name the simulator label as authoritative for M1 and
record the expected value per message — the schema currently names the source but never records the
expectation.

---

## 10. Bounds, timers and the clock

| Bound | Value | Site |
|---|---|---|
| per-turn step budget | `agent_max_steps`, default **40**, `ge=4`, `le=40` | `settings.py:39` |
| — budget arithmetic | `run.step_count - checkpoint["turn_start_step"]` vs limit | `engine.py:753-757`, `routes.py:159` |
| — the reset that *makes it per-turn* | `turn_start_step` reset on `body.kind == "demo_reply"` | `routes.py:562-566`; also `engine.py:1424` |
| role limit, simulator on | Coordinator **8**, specialists **6** | `engine.py:784` |
| role limit, simulator off | Coordinator **4**, specialists **6** | `engine.py:786` |
| simulator gate | demo clinic id **and** `checkpoint["patient_simulator_enabled"] is True` | `simulation.py:18` |
| "today" | derived at run time from wall clock: `utcnow().astimezone(+08:00)` | `engine.py:394` |

**Corrections this forces on the programme PRD:**

1. The role limit is **conditional**, not constant: "8/6" holds only on the simulator path
   (`engine.py:784`) and only for the demo clinic (`simulation.py:18`). The schema's
   `role_limit_coordinator: const 8` is only sound if `environment.clinic_id` is bound to the demo
   clinic; as written, an item with another clinic id and `patient_simulator_enabled: true` validates
   against 8 while the runtime would yield 4 (`engine.py:786`).
2. `agent_max_steps` is a **per-turn** budget, not a whole-run budget (`engine.py:753-757`,
   `routes.py:562-566`). "Step-budget exhaustion" in policy #4 therefore means *per turn*.
   *(Correction: the earlier draft attributed a run-wide misreading to the programme PRD. The PRD
   only states the default of 40; the attribution was unsupported and is withdrawn.)*
3. The clock is **not** frozen and has **no override seam**: `utcnow` is a free function
   (`db.py:20`) with no settings clock. Freezing it requires monkeypatching
   `forget_lah.db.utcnow` in-process, or adding a seam. That is a runtime change, not fixture
   wording. See §12.

---

## 11. Phase and step-type vocabulary

`DECISION_FORMATS` — `contracts.py:554-608`. Complete list of step types the engine can receive:

`REVIEW_NEEDS` (`:555`), `CLARIFY` (`:556`), `ASSESS_BARRIERS` (`:560`), `REPORT_SYMPTOMS` (`:576`),
`INTERPRET_ATTENDANCE` (`:581`), **`INTERPRET_SELECTION` (`:587`)**, `INTERPRET_INSTRUCTION_CHECK`
(`:593`), `TOOL` (`:599`), `DELEGATE` (`:600`), `RETURN` (`:601`), `WAIT` (`:602`),
`ESCALATE` (`:603`), `COMPLETE` (`:604`), `COMPLETE_SIMULATED_CONFIRMATION` (`:605`).

**Correction:** the programme PRD §2 lists six reply phases and **omits `INTERPRET_SELECTION`**,
which is a real first-class step type used when the patient picks from offered slots. Coverage
quotas computed from the PRD's shorter list will under-cover it.

`ESCALATE` carries no fields (`:603`). *(Earlier draft claimed this is why `AMBIGUOUS_REPLY` can
never be offered to the System One decider. `AMBIGUOUS_REPLY` is actively handled at
`engine.py:1796-1800`, and the decider branch is not on this tree, so the rationale was
unverifiable. Withdrawn.)*

---

## 12. Unresolved / needs a decision before M1 exit

| Item | Kind | Status |
|---|---|---|
| Is a run ending `escalated` after an unresolved `CLINIC_REVIEW` question the scenario's **single accepted** outcome, or a failure under policy #4? | **policy, not code** | **needs-human-decision** — decides whether `terminal_oracle` gains an `escalated` arm (required for the `questions` stratum) or those scenarios are authored as failures |
| How is the `zh`/`ms`/`ta` delivery path exercised, given `translation_configured` requires `agent_model_mode == "anthropic"` (`settings.py:20-25`)? | **policy, not code** | **needs-human-decision** |
| Clock freezing: `utcnow` has no override seam (`db.py:20`) — monkeypatch or add a seam? | engineering | open, agent-resolvable |
| `attendance_qualification.status` ∈ `{CONFLICT, COMPATIBLE, UNRESOLVED}` and its intent demotion | engineering | verified in code; schema must type it |
| `callback` / `clinical_review` consequence of an unresolved question (`questions.py:111-120`; pairing `engine.py:1727-1728`) | engineering | verified in code; no checkpoint field today |
| Per-message expected delivery value | engineering | resolved in §9; schema must record it |
| `policy.py:119` — memory-quote-in-reply binding (`MEMORY_QUOTE_NOT_IN_PATIENT_REPLY`) *(earlier draft miscaptioned this as language-tag validation)* | engineering | verified |
| `provider.py:857` — `UNSUPPORTED` bounded to non-clinical operational facts | engineering | verified |
| permitted authorship/licences for sources | policy | needs-human-decision |
| wrong-number / third-party runtime path | absent | strata stay `UNSCORED` |

---

## 13. Revision history

**Revision 2 (this file)** — corrected against the first independent review. Substance errors fixed:
the `WAITING_FOR_CLARIFICATION` checkpoint claim (§1, §2), the "delivery sources disagree" premise
(§9), the withdrawn `AMBIGUOUS_REPLY` rationale (§11), the miscaptioned `policy.py:119` row, and the
unsupported "PRD misread the step budget" attribution (§10). Added: `wait_reason` (§2), the
`escalated` terminal (§2), the `translation_configured` second gate and its consequence (§8),
`GUIDANCE`'s required `practical_issue`/`dependency` and the bounded action set (§4), positional task
ordering (§3), and the two policy questions in §12. Line citations re-derived: `models.py:39-41`,
`contracts.py:292-294`, `provider.py:857`.

**Revision 1** — first draft, never reviewed.
