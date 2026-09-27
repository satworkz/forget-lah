# Roadmap and pilot gates

Updated 27 September 2026. All items below are future work or validation gates, not delivered-product claims. For implemented behaviour, use [Current capabilities](CURRENT_CAPABILITIES.md).

## Controlled clinic pilot

Agree eligible cases, approved clinical instructions, access, consent arrangements and staff escalation cover. Use representative cases to establish a baseline and measure the [proposed pilot targets](submission/Forget-lah_Business_Proposal.pdf). Replace the synthetic Clinic API with an authorised integration, or validate the clinic's approved Bridge data and scoped options. Complete production messaging enrolment/templates and governance before contacting real patients.

## Availability, performance and operations

Preserve durable PostgreSQL work, leases, policy and receipts while adding reactive wake-ups with polling recovery. Validate redundant application/worker operation, database failover, off-host backups and restore exercises. Measure concurrency, queue age, provider quotas, source contention and end-to-end delivery before claiming production capacity or availability.

Extend saved case evidence with correlated operational traces, dashboards, alert ownership and retention. Complete the production hardening items in [Security architecture](SECURITY_ARCHITECTURE.md), including managed secrets, MFA, verified encryption-at-rest and incident procedures.

## Patient and integration roadmap

- Patient Companion with offline reminders and calendar integration.
- Voice-enabled interaction and accessibility.
- Caregiver-authorised support and trusted identity/consent integration, including potential Singpass integration subject to approval.
- Follow-up Pattern Intelligence for clinic-reviewed proactive outreach.
- Diagnostic, laboratory, physiotherapy and X-ray integration using authorised availability; nearby-provider preferences where consented.
- Consent-based group reminders; education reminders remain exploratory reuse outside the clinical submission scope.
- Availability watching/waitlisting and unresolved staff patient-check initiation require separate design and validation.

The earlier M2a planning list remains in Git history. Organiser gateway integration, controlled WhatsApp, reviewed intake and supported source changes are now implemented; they should not be presented as unstarted milestones.
