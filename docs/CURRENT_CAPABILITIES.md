# Current capabilities and boundaries

Submission snapshot: 27 September 2026. This summary takes precedence over undated or earlier milestone descriptions. The dated [implementation log](IMPLEMENTATION_STATUS.md) preserves the development history.

## Implemented for the hackathon

- AWS-hosted synthetic demo; React staff dashboard, FastAPI, PostgreSQL and persistent worker.
- Coordinator, Engagement and Preparation roles, with Coordinator-only delegation.
- Automatic eligible-case detection and durable follow-up; controlled WhatsApp replies and patient-initiated questions, subject to sandbox windows and enrolment.
- Multilingual interpretation and staff-display translation; source-grounded instructions, prerequisites and contextual conflict handling.
- Source-validated confirmations and supported appointment changes. API sources own their master records; Bridge owns approved imported follow-up lifecycle state.
- Intelligent Intake with semantic mapping, REVIEW/READY, staff correction, approval and provenance.
- Staff-controlled changes, named handoff acceptance and recorded staff resolution.
- Clinic/role access controls, queued-authority checks, policy/evidence gates, bounded uploads and audit views.
- Organiser-provided model gateway for agents, intake and translations; selective calls and shared usage controls.
- Durable terminal-failure review and eligible fixed patient acknowledgement; a failed notification does not repeat a committed source update.

## Boundaries

- Synthetic clinic records and designated test participants; no demonstrated production clinical outcomes or clinical triage certification.
- Model output cannot establish identity, consent, authority or booking success.
- Patient questions are answered from available approved evidence; unsupported clinical questions go to staff.
- No unrestricted medical advice, EMR or general scheduling engine. No automatic cancellation source action or slot waitlist/availability watcher.
- Sandbox messaging is not production proactive outreach. Templates, SMS and voice are future work.
- Staff patient-check initiation remains deferred; see [the documented gap](STAFF_APPOINTMENT_CHANGE_GAPS.md).
- One deployed host is not host-level high availability. Reactive wake-ups and redundant deployments require further implementation and validation.
- Free text can contain identifying data; intake processes supplied rows. No claim of complete anonymisation, immutable audit storage or healthcare compliance.

## Evidence

[Feature guide](FEATURE_GUIDE.md), [Bridge](BRIDGE_INTAKE.md), [security](SECURITY_ARCHITECTURE.md), [performance](PERFORMANCE.md), [organiser gateway](ORGANISER_GATEWAY.md), [failure handling](FAILURE_HANDLING.md) and the [submission PDFs](submission/README.md).
