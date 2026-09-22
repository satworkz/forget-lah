# Deferred gap: starting patient checks from Change appointment

Recorded: 22 September 2026  
Status: **Open — explicitly deferred by the user. Document only; do not implement or deploy this gap without a future request.**  
Reference: GAP-STAFF-CHANGE-001

## Observed behavior

After **Change appointment → Review doctor instructions**, the panel can identify unanswered patient checks and block slot selection. It tells staff to complete them through the existing patient follow-up conversation, but provides no action to start or resume those questions from this panel.

The reported example contains two checks in approved doctor instructions:

- Whether the patient has completed the blood test.
- Whether the patient has taken medicines regularly.

The instruction says to postpone when a condition is not met. The panel displays each outstanding check, but staff cannot proceed if the conversation has not already asked it. **Refresh availability and delivery status** only reloads the state; it does not initiate the questions. Re-running the read-only instruction review does not collect patient answers either.

This is a workflow dead end, not a missing staff click. The existing conversation is a possible workaround only when the required questions are already active or can be reached through its normal flow. Do not claim that both answers must be yes: a negative answer may require the existing postponement/rescheduling path.

## Proposed future behavior — not yet implemented

Provide a clear action in the panel to start or resume the outstanding patient checks through the existing Coordinator/Preparation workflow, or navigate directly to an already pending check. Show whether questions are awaiting answers, resolved, or require clinic review. After resolution, refresh eligible slots or explain the remaining restriction.

Before implementation, clarify which source instructions gate attendance confirmation, which gate a staff-initiated appointment change, and which explicitly require postponement. Do not silently treat confirmation-only conditions as universal rescheduling prohibitions or bypass genuine doctor constraints.

## Acceptance criteria for future work

- Start the applicable source-grounded questions from this panel without asking staff to invent a patient reply or confirm attendance to unlock scheduling.
- Resume pending questions without duplicates; handle retries, cancellation and delivery failure visibly.
- Record real patient responses and evidence. Route negative answers according to the approved instruction and existing workflow; preserve preparation-question and RED clinical-concern handling.
- Keep the appointment unchanged while checks are pending. Completing checks alone must not move the appointment or imply patient agreement to a new time.
- Revalidate source versions, patient/case binding, doctor constraints and slot availability before the eventual staff change.
- Preserve source ownership: Bridge uses Forget-lah-owned follow-up tables; API-backed clinics use their authorized source adapter. Bridge must never touch mock-clinic tables.
- Audit question initiation, answers and resolution; retain conversation history and notification delivery state.
- Test both source paths, multiple checks, negative/uncertain answers, existing pending questions, stale source data, failed delivery/retry, and clinical concerns using offline fixtures before live verification.

## Related documentation

- [Staff appointment-change architecture and behavior](ADR_STAFF_APPOINTMENT_CHANGE.md)
- [Implementation status](IMPLEMENTATION_STATUS.md)

No application code, patient data, messages or deployment were changed when recording this gap.
