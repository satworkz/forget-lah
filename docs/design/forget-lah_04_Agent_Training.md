# forget-lah: worked agent journeys

10 September 2026 | v2.0 | Synthetic teaching examples, not executed patient interactions

## 1. The responsibilities in one sentence each

The **source system or reviewed upload** says what follow-up is due and which instructions the clinic approved. The **Candidate Detector** identifies eligible records. **PostgreSQL** remembers verified state. The **worker** wakes due jobs. The **runtime** restores context and runs the relevant agent. The **agent** interprets context and proposes permitted next steps. The **gateway** checks permission and calls a known function. The **source/provider result** says what actually happened.

The application owns identity, consent and facts. Claude helps interpret and plan within those boundaries. It does not need to memorise the architecture or hold a running conversation overnight.

## 2. Example A: connected dental clinic

Mr Lim, a synthetic 76-year-old patient, has appointment A100 on Thursday 17 September 2026 at 9:30 AM Singapore time. His authorised test contact is enrolled. He asks for Friday afternoon, a first source slot conflicts, he confirms another offered slot, and he acknowledges the applicable approved preparation note.

| Step | What happens technically | Agent contribution |
|---|---|---|
| 1. Detect | Source adapter reads A100 and authorisation; detector applies the upcoming/unconfirmed rule and inserts C100 + job + audit atomically | None needed to compare dates/status |
| 2. Start | Worker leases job; runtime restores C100 and assigns Engagement for the obvious initial task | Agent role owns the conversational goal; initial approved message can be selected by rule |
| 3. Contact | Gateway checks consent, recipient, source freshness and channel limits; provider accepts the approved message | No claim of confirmation merely from delivery |
| 4. Receive | Signed webhook is validated and deduplicated; message 'Can I come Friday afternoon?' is attached to the verified case/question | Fresh Engagement call interprets the scheduling intent |
| 5. Decide | Model proposes search_slots with Friday 18 September afternoon and a reason code | Contextual date interpretation and tool choice |
| 6. Search | Gateway validates the proposal and calls AppointmentSource.search_slots; real result supplies eligible slots | Agent observes actual availability |
| 7. Adapt | Source reports a selected slot has become unavailable; original booking remains | Agent asks a clarifying question or proposes another permitted search instead of claiming success |
| 8. Confirm | Exact available date/time is offered; Mr Lim confirms that offer, from WhatsApp or an authenticated PWA session | Free text may need interpretation; structured button binding can be handled by code |
| 9. Commit | Gateway checks the current case/source version, offer expiry and confirmation evidence; source atomically reschedules | Model cannot override a source failure |
| 10. Prepare | Runtime verifies booking result and routes to Preparation; tool retrieves current approved instruction text | Preparation interprets questions/uncertainty; displayed clinical text is source-owned |
| 11. Acknowledge | Mr Lim acknowledges the exact instruction version; runtime records evidence | Acknowledgement is distinct from actually completing preparation |
| 12. Close | Runtime checks source result, confirmation and required acknowledgement; then records routine completion | A model saying 'done' is not enough |

If a reply combines 'I cannot find the requested document' and 'could I visit later?', the runtime supplies both goals to the Coordinator Agent. It chooses a permitted delegation or review plan; it cannot decide whether a clinical prerequisite is medically optional. This is a useful non-obvious Coordinator demonstration.

## 3. What Claude receives each time

We send five things: the agent's instructions; fresh case/source context; the latest patient event; allowed tools with argument schemas; and the expected response schema. Relevant previous tool observations and the current question are included. The model adapter translates this internal structure into the organiser's actual API format when available.

We do not send every patient record, every database table or the whole design guide. Prompt text is not the enforcement mechanism for access. The gateway reloads trusted evidence regardless of the model's claim.

## 4. Why reason_code exists

Developers define a fixed vocabulary so code/tests/staff traces can recognise the model's concise explanation. `enum` means the value must be one of the listed strings. The following must actually appear in the schema supplied to the model, not only in a PDF explanation or filename:

```json
{
  "reason_code": {
    "type": "string",
    "enum": [
      "PATIENT_CONFIRMED_ATTENDANCE",
      "PATIENT_REQUESTED_ALTERNATIVE_DATE",
      "AMBIGUOUS_REPLY",
      "CLINICAL_REVIEW_REQUIRED"
    ]
  }
}
```

Our instructions explain the mapping. 'Yes, I will come at the scheduled time' may map to PATIENT_CONFIRMED_ATTENDANCE. 'Can I come on another date?' maps to PATIENT_REQUESTED_ALTERNATIVE_DATE. An unclear reply requires clarification. A question asking for clinical judgement requires staff review.

This is the shared starter vocabulary; the full action-specific schema adds more codes when needed and restricts incompatible action/reason pairs. No reason code establishes identity, safety or permission. This is not a built-in Claude feature.

## 5. A complete small TOOL branch

This teaching schema is the search_slots branch only. The full AgentStep schema also defines other tools, delegation, wait, completion and escalation. It must be generated/validated from our Pydantic models so every branch has required fields, enums and `additionalProperties: false`.

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["step_type", "action", "arguments", "reason_code", "expected_case_version"],
  "properties": {
    "step_type": {"type": "string", "const": "TOOL"},
    "action": {"type": "string", "const": "search_slots"},
    "arguments": {
      "type": "object",
      "additionalProperties": false,
      "required": ["local_date", "timezone", "time_band"],
      "properties": {
        "local_date": {"type": "string", "format": "date"},
        "timezone": {"type": "string", "enum": ["Asia/Singapore"]},
        "time_band": {"type": "string", "enum": ["morning", "afternoon"]}
      }
    },
    "reason_code": {
      "type": "string",
      "enum": ["PATIENT_REQUESTED_ALTERNATIVE_DATE", "SOURCE_SLOT_UNAVAILABLE"]
    },
    "expected_case_version": {"type": "integer", "minimum": 1}
  }
}
```

Even a well-formed date needs business validation: allowed search window, appointment type, local interpretation and source eligibility. If the organiser supports schema-constrained output, use it; otherwise include the schema/instructions and validate the returned JSON locally. A malformed response never executes a partial action.

## 6. What comes back and how Python reads it

```json
{
  "step_type": "TOOL",
  "action": "search_slots",
  "arguments": {
    "local_date": "2026-09-18",
    "timezone": "Asia/Singapore",
    "time_band": "afternoon"
  },
  "reason_code": "PATIENT_REQUESTED_ALTERNATIVE_DATE",
  "expected_case_version": 7
}
```

The model adapter extracts the response body. Pydantic parses/validates it into a typed object. Python reads `action` and looks it up in a registry of functions written by our developers. It reads `arguments` and passes the validated date/time filters to that function. `reason_code` is logged and checked for consistency, not used as an access token.

```python
# Illustrative application flow; helper implementations are future code.
step = AgentStepAdapter.validate_json(model_text)
ctx = load_trusted_context(job.case_id, job.agent_name)
check_case_version(step.expected_case_version, ctx.case_version)
check_action_reason_consistency(step)
tool = registry.allowed_tool(ctx.agent_name, step.action)
args = tool.validate_arguments(step.arguments)
decision = policy.evaluate(ctx, step.action, args)
if decision.decision != "ALLOW":
    return record_and_handle_denial(decision)
return execute_with_revalidation_and_evidence(ctx, tool, args)
```

The gateway verifies the source supports this tool, the contact/patient/clinic link is authorised, the current case permits this step and the evidence is fresh. Unknown tools are denied; it does not eval model-generated code. No second AI is needed to understand the JSON.

Application-generated permission result:

```json
{
  "request_id": "REQ100", "case_ref": "C100", "case_version": 7,
  "action": "search_slots", "arguments_hash": "sha256:DEMO_DIGEST",
  "decision": "ALLOW", "risk": "GREEN",
  "reason_codes": ["CONTACT_AUTHORITY_VALID", "SOURCE_TOOL_SUPPORTED"],
  "policy_version": "demo-v2"
}
```

This means only: 'Allow this particular search request, with these arguments, for this case version.' It is the meaning of request/action/case binding. Changed arguments or state need another check. `reason_code` is the model's explanation; `reason_codes` are the gateway's actual checks. Identity is proven by trusted session/contact evidence, not by Claude returning identity_verified=true.

Source adapter result:

```json
{
  "action": "search_slots", "status": "succeeded",
  "source_version": "slots-v12",
  "data": {
    "slots": [{"slot_id": "S240", "starts_at": "2026-09-18T07:00:00Z"}]
  },
  "retryable": false
}
```

The slot is 3 PM Singapore time. It is availability, not a reservation. The runtime/agent then offers it and waits for exact confirmation. Later mutation success must come from the source's atomic operation, with idempotency and source-version checks. On a timeout, the app reconciles; it does not tell Mr Lim the change succeeded without evidence.

## 7. Example B: a clinic with uploaded schedules

Staff uploads a strict CSV of synthetic schedules and a TXT note. Parser checks schema, size, timestamps, duplicate IDs and patient mapping. Staff previews the content, marks the exact patient-facing instruction as approved and publishes a version. Contact authority is separately enrolled.

The imported source exposes read_schedule and read_approved_instructions. It exposes no search_slots/book/reschedule capability. Detector creates an eligible case and normal outreach begins. If Mr Lim confirms the published time, forget-lah records attendance intent for staff; it does not claim to update another system.

If he requests Friday instead, Engagement records the requested window and creates an escalation for scheduling help. Staff member STAFF01 claims it. The case can record handed_to_staff, while the staff task remains open. Staff checks the clinic's real schedule, confirms with the patient and publishes the resulting appointment snapshot; only that evidence supports a later confirmed result. The UI never invents a slot inventory.

If a snapshot is stale, a newer import changes the appointment or the patient cannot be mapped, outreach pauses and the UI shows why. Repeated uploads do not generate repeated contacts.

## 8. Example C: PWA, voice and Singpass

A patient opens the forget-lah link, signs in using the enabled identity method and sees only linked follow-up cases. With actual Singpass staging enabled, the callback is verified and mapped to the existing enrolment. Without it, the demo says 'Demo identity' and uses synthetic accounts; no real Singpass success is implied.

The patient taps Talk on a supported device, reviews the transcription 'Please call me in Mandarin next time' and sends it. The same Engagement Agent proposes a preference change. forget-lah asks for explicit confirmation, stores evidence and respects the chosen channel only when supported and permitted. On unsupported speech devices the text interface still works; browser speech may involve an external processor and requires consent.

The patient can enable generic push notifications and explicitly export the verified appointment to the device calendar. Neither operation confirms attendance or reserves a slot. Denied notification permission falls back to another permitted channel; calendar copies can become stale after changes.

The staff view uses its own authorised API routes and includes the source import, patient messages, action evidence and handoff queue. Installing the PWA is optional, so seniors can continue through WhatsApp, telephone or an authorised caregiver.

## 9. What the judges should see

Show the **Agent Activity** view, not private reasoning: goal, observation summary, model/rule origin, selected tool/delegation, gateway result, actual tool result, next event and evidence. Demonstrate a genuine model proposal adapting after a tool failure, then a restart that resumes the correct pending question from PostgreSQL.

Dental anchors the original problem. Myopia shows approved preparation and inclusion. Antenatal shows ordinary scheduled follow-up plus a synthetic concern that pauses routine automation and becomes an accepted staff task. Clinical routing comes from approved rules; the system does not diagnose or determine urgency from vocal tone.

Completion means an evidenced follow-up outcome or owned staff handoff. It does not mean the patient attended, received care or achieved a clinical benefit. Those real-world effects would need later evidence.
