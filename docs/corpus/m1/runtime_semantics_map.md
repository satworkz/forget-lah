# Runtime semantics map — graded fields for the conversation corpus

**Milestone:** M1 · **Status:** Draft for standup review · **Date:** 2026-09-23
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
| **Run terminal state** | the whole conversation | `run.status` (`models.py:41-42`) **plus** `checkpoint["outcome"]` (`engine.py:1821`, `1853`, `1856`) |

`ANSWERED`/`GUIDANCE`/… answer *"what happened to the patient's question"*. They do not say the
conversation finished, and a run can hold several of them at once — one per task. Treating them as
thread outcomes (as the PRD's wording invites) would grade the wrong object.

---

## 2. Run terminal state

**Run status** — `models.py:41-42`, CHECK constraint:
`queued`, `running`, `waiting`, `paused`, `escalated`, `completed`

**Checkpoint outcome** — only three values are ever written:

| Value | Written at | Meaning |
|---|---|---|
| `WAITING_FOR_CLARIFICATION` | `engine.py:1821` | run paused awaiting the patient |
| `OWNED_STAFF_HANDOFF` | `engine.py:1853` | completed via `CompleteDecision` |
| `SIMULATED_ATTENDANCE_CONFIRMED` | `engine.py:1856` | completed via `CompleteSimulationDecision` |

**Failure/pause codes** (`pause()` at `engine.py:115`):

| Code | Site | Approved policy #4 |
|---|---|---|
| `STALE_CHECKPOINT` | `engine.py:749-750`, `1993-1994` | failure |
| `STEP_BUDGET_EXHAUSTED` | `engine.py:757` | failure |
| `ROLE_BUDGET_EXHAUSTED` | `engine.py:788` | failure |

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
`(run.status, checkpoint.outcome | pause code)` — plus, for handoff, a fixture-supplied
staff-acceptance record. The PRD's "permitted terminal alternatives" must be deleted: the accepted
policy is exactly **one** expected end state per scenario.

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
| `outcome` | completion / waiting paths | see §2 |

**Therefore `PLAN` and `QUESTION` are not free labels.** `QUESTION` ≡ an entry in
`patient_questions`; `PLAN` ≡ an entry in `preparation_plans`
(`contracts.py:350`, `:355`). The schema should state this rather than let authors assign task
types by hand — and note the arrays are *concatenated*, so the type list is positional.

---

## 4. Per-question outcomes

Literal at `contracts.py:88`; evidence rules at `contracts.py:136-140`; validation at
`questions.py:45-73`.

| Constraint | Site | Schema consequence |
|---|---|---|
| Every stored task must be answered, indices exactly `0..n-1` | `questions.py:16-17` | oracle must supply one answer per task; `QUESTION_COVERAGE_INCOMPLETE` otherwise |
| `PLAN` may only be `GUIDANCE` or `NOT_REQUIRED` | `questions.py:45-46` | reject other combinations at authoring |
| `GUIDANCE`/`NOT_REQUIRED` require `PLAN` | `questions.py:47-48` | symmetric rule |
| `ANSWERED`/`GUIDANCE` need `instruction_id` **and** a non-empty quote | `contracts.py:136-140` | |
| the quote must be a substring of the **approved instruction text** | `questions.py:49-54` | cannot be graded against free prose |
| `GUIDANCE` also needs a matching `INFORMATION` item in `scheduling_review` | `questions.py:55-60` | |
| `CONFLICTS` must include `FOLLOW_CLINIC_INSTRUCTION` | `questions.py:63-64` | |
| `POSSIBLE_SUBSTITUTION` needs `CONTACT_CLINIC` or `FOLLOW_CLINIC_INSTRUCTION` | `questions.py:65-68` | |
| `OFFER_RESCHEDULE` requires `appointment_intent` in `{CONFIRM, CHANGE}` | `questions.py:69-73` | |
| an unresolved question defaults to `CLINIC_REVIEW` and raises a callback | `questions.py:85`, `106-120` | `CLINIC_REVIEW` is the fallback, so it is a *plausible* end state, not necessarily a correct one |

`UNSUPPORTED` is the sanctioned answer for a non-clinical operational fact the clinic sources cannot
answer (`provider.py:857-858`). Clinical/preparation questions without an approved answer still take
`CLINIC_REVIEW`.

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
- `attendance_qualification` is valid **only** with `CONFIRM` (`contracts.py:386-389`).
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
| `remove` + `contact_permission` | **rejected** — "Contact permission requires explicit simulator control to resume" | `contracts.py:289-293` |
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
3. `contact_permission` cannot be unset by the model at all (`contracts.py:289-293`), so no scenario
   may expect the conversation to clear a contact stop.

---

## 8. Delivery gate and translation

`delivery_block` — `memory.py:115-123`:

- `proactive` + `contact_permission == "stopped"` → `CONTACT_STOPPED` (`memory.py:117-118`).
- language defaults to `en`; **supported set is `{en, zh, ms, ta}` only when
  `settings.translation_configured`**, otherwise `{en}` (`memory.py:119-120`).
- unsupported or excluded language → `LANGUAGE_SUPPORT_REQUIRED` (`memory.py:121-122`).

**Consequence:** the gate's behaviour is *configuration-dependent*. The fixture must pin
`translation_configured` explicitly, or the same scenario yields different graded outcomes.
Acknowledgement strings exist for `zh`/`ms`/`ta` (`memory.py:126-132`), and a trilingual language
question at `memory.py:135-137`.

---

## 9. Delivery evidence (needs one authoritative source named)

Two different sources exist, and they disagree by construction:

- Simulator messages label themselves `"delivery_status": "displayed_in_simulator"` —
  `simulation.py:995`, plus `engine.py:2093` and `engine.py:2123`.
- The case-view route **replaces** that field with an outbox-status database lookup —
  `routes.py:264` (`"delivery_status": db.scalar(...)`).

The fixture contract must name **one** of these as authoritative. Grading delivery from both would
compare a label against a lookup. **Open — agent-resolvable.**

---

## 10. Bounds, timers and the clock

| Bound | Value | Site |
|---|---|---|
| per-turn step budget | `agent_max_steps`, default **40**, `ge=4`, `le=40` | `settings.py:39` |
| — measured **per turn**: `run.step_count - checkpoint["turn_start_step"]` | | `engine.py:753-757` |
| role limit, simulator on | Coordinator **8**, specialists **6** | `engine.py:784` |
| role limit, simulator off | Coordinator **4**, specialists **6** | `engine.py:786` |
| simulator gate | demo clinic id **and** `checkpoint["patient_simulator_enabled"] is True` | `simulation.py:18` |
| "today" | derived at run time from wall clock: `utcnow().astimezone(+08:00)` | `engine.py:394` |

**Corrections this forces on the programme PRD:**

1. The role limit is **conditional**, not constant: "8/6" holds only on the simulator path. Applies
   to the corpus, but the PRD must say so.
2. `agent_max_steps` is a **per-turn** budget, not a whole-run budget (`engine.py:753-754`).
   "Step-budget exhaustion" in policy #4 therefore means *per turn*, and the schema should record
   `turn_start_step` semantics rather than a single run-wide count.
3. The clock is **not** frozen in the runtime — it reads the wall clock. The fixture contract must
   freeze it (inject the date) or every relative-date scenario is non-reproducible. **Open —
   agent-resolvable.**

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

`ESCALATE` is `{}` (`:603`) — no fields — which is why `AMBIGUOUS_REPLY` can never be offered to the
System One decider.

---

## 12. Unresolved / to verify before M1 exit

| Item | Status |
|---|---|
| Authoritative delivery-evidence source (§9) | **open, agent-resolvable** |
| Clock-freezing mechanism (§10) | **open, agent-resolvable** |
| `engine.py:682` — callback/clinical-review resolution before completion | **UNVERIFIED** |
| `routes.py:387` — handoff route evidence | **UNVERIFIED** |
| `provider.py:838` — visit-only comprehension-repair instruction | **UNVERIFIED** |
| `policy.py:119` — language-tag/quote validation for preference changes | **UNVERIFIED** |
| `contracts.py:310` — language-tag shape check | **UNVERIFIED** |
| `questions.py:13` — cited by the M1 PRD for the same rule as `:45` | superseded by `:45-48` |
| permitted authorship/licences for sources | **needs-human-decision** |
| wrong-number / third-party runtime path | absent; strata stay `UNSCORED` |
