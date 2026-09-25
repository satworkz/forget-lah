# Patient workflow failure handling

Implemented 25 September 2026. Deployment verification is recorded in AWS_DEMO.md.

Business and policy failures are first-class failures, not just infrastructure errors. A terminal policy denial, exhausted model/source retries or step budgets, stale workflow context, unsupported request that already requests staff review, or unexpected case-processing exception must leave a durable staff review. An eligible current patient reply also receives one fixed acknowledgement. The fallback does not execute the rejected action or invent a successful appointment outcome.

## Deterministic correction and policy

A coordinator delegation's reason is derived from its typed target: Preparation uses PREPARATION_REVIEW_REQUIRED; Engagement uses FOLLOWUP_REVIEW_REQUIRED. The original mismatched proposal is retained in the step observation. The corrected proposal still passes the full policy gate, including request/version, role, authority, evidence and consent checks. Other denied proposals remain denied and visible in the case evidence.

## Durable review and acknowledgement

The runtime completes recovery in a fresh transaction, locks the current run, verifies clinic/case ownership and current staff authority, creates or reuses a staff handoff, and records a security event. Recovery preserves an existing handoff's reason and risk. Review is not owned until named staff accept it.

Fixed English, Malay, Mandarin and Tamil text explains that the request could not be completed safely and has been sent to the clinic team. It asks the patient to confirm with the clinic before assuming an appointment change is complete. No model call is needed to generate or translate this acknowledgement. It is stored with the current reply and delivered through the existing enrolled channel/outbox.

Repeated recovery cannot create duplicate tasks or acknowledgements. A periodic worker pass recovers persisted terminal pauses after a restart. Unexpected processing errors are recovered only for the matching worker lease; no exception body is exposed to patients or stored in the recovery event. Pending bounded retries continue normally. Manual staff pauses and deliberate model-mode configuration pauses stay paused.

## Boundaries and limitations

- Outreach requires a saved case-bound patient reply, enabled patient messaging, an allowed language and contact permission. Channel enrollment and delivery rules continue to apply. Without these, the staff review is recorded and the notice is marked withheld. Revoked authority or mismatched clinic/case binding cannot be bypassed by the fallback.
- A database outage can prevent persistence itself. Recovery depends on the supervised worker and database returning; it cannot guarantee an immediate acknowledgement during an outage. Messaging outages follow existing delivery retry rules; queued does not mean delivered.
- An uncertain external source write is not automatically replayed by the fallback. Staff must inspect source evidence before confirming an outcome. API-backed sources and Bridge-owned lifecycle tables retain their existing ownership boundaries.
- Generic HTTP errors return a safe response; an HTTP error without an authenticated, bound patient workflow is not permission to message a patient or create a clinical review.
- This is a case-workflow safety boundary, not a guarantee that every infrastructure/process failure can be handled synchronously. No new centralized monitoring, incident management or production service-level guarantee is claimed.

## Verification

Offline tests cover policy/model/source failures, unexpected exceptions, consent stop, revoked authority, clinic mismatch, stale lease, static Malay acknowledgement, existing business handoffs, duplicate recovery, full policy recheck after reason correction, and generic HTTP-error redaction. PostgreSQL concurrency verifies two simultaneous recoveries produce exactly one handoff and acknowledgement. No migration or secret change is required.


## Files in this failure-handling change

- Runtime: `src/forget_lah/runtime/failures.py` (new), `runtime/engine.py`, `worker.py`, `api.py`.
- New checks: `tests/test_failure_handling.py`; PostgreSQL concurrency added to `tests/test_postgres.py`.
- Updated regression expectations: `tests/test_runtime.py`, `test_attendance_qualification.py`, `test_availability_progress.py`, `test_clinical_review.py`, `test_demo_reset.py`, `test_doctor_actions_dynamic.py`, `test_doctor_scheduling.py`, `test_patient_memory.py`, `test_patient_simulation.py`, `test_recall_booking.py`.
- Documentation: this file, `docs/ADR_SECURITY_HARDENING.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/AWS_DEMO.md`.
- Migrations: none. Existing organiser-gateway changes remain in the working tree and are included unchanged from the previous AWS release.
