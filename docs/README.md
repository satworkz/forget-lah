# Documentation guide

## For judges

Start with the [submission index](submission/README.md) and [current capabilities](CURRENT_CAPABILITIES.md). The application is an intelligent patient follow-up layer; use the current summary to distinguish delivered behaviour from historical plans.

| Document | Purpose |
| --- | --- |
| [Business proposal](submission/Forget-lah_Business_Proposal.pdf) | Problem, workflow value, pilot targets and delivery assumptions |
| [Technical document](submission/Forget-lah_Technical_Document.pdf) | Architecture, agent roles, source ownership, security and evidence |
| [Feature guide](FEATURE_GUIDE.md) | Detailed scenarios and capability boundaries |
| [Bridge intake](BRIDGE_INTAKE.md) | No-API route, review/approval and follow-up ownership |
| [Security architecture](SECURITY_ARCHITECTURE.md) | Implemented controls and future hardening |
| [Case journey](CASE_JOURNEY.md) | Saved decisions, source evidence, policy and human ownership |
| [Performance](PERFORMANCE.md) | Selective model calls, worker concurrency and planned reactive wake-ups |
| [Organiser gateway](ORGANISER_GATEWAY.md) | Provider integration, bounded requests and recorded checks |
| [Failure handling](FAILURE_HANDLING.md) | Durable review, acknowledgement and recovery limits |
| [Validation](VALIDATION.md) | Dated verification records; not a substitute for current CI |
| [Roadmap](NEXT_MILESTONE.md) | Future scope and pilot/production gates |

## Maintainer and test operations

These guides are for authorised team members operating synthetic test environments. They are not a request for judges to reset records, enrol phones or send messages.

- [Cloud testing](TEAM_CLOUD_TESTING.md) and [AWS deployment history](AWS_DEMO.md)
- [Windows/team setup](TEAM_START_HERE.md), [Linux setup](UBUNTU_QUICK_START.md), [first run](FIRST_RUN.md)
- [Provider setup](CLAUDE_SETUP.md), [WhatsApp setup](WHATSAPP_SETUP.md), [clinic simulator](CLINIC_SIMULATOR.md), [reset controls](DEMO_RESET.md)
- [Staff appointment-change design](ADR_STAFF_APPOINTMENT_CHANGE.md) and [deferred gaps](STAFF_APPOINTMENT_CHANGE_GAPS.md)
- [Typed agent contract](contracts/agent-decision-v1.json)

Credentials, real contact details and deployment recovery files remain outside Git. Never publish `.env`, private keys, database dumps or screenshots containing real participant details.

## Historical records and experiments

Keep these as evidence of design evolution, not as current product claims:

- [Implementation chronology](IMPLEMENTATION_STATUS.md): dated entries supersede earlier states.
- [M2a runtime guide](AGENT_RUNTIME.md), [patient simulator milestone](PATIENT_SIMULATOR.md), [early direct-Claude validation](LIVE_CLAUDE_VALIDATION.md).
- [Original design pack](design/forget-lah_README.md) and [v0.1 setup PDF](forget-lah_Team_Quick_Start.pdf).
- [DSPy/GEPA experiment](DSPY_GEPA_SPIKE.md): separate scratch experiment, not the deployed runtime or a production accuracy claim.
- [Video rehearsal materials](video/START_HERE.md): earlier recording instructions; the final submission video supersedes those cuts.
