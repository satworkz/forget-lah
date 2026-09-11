# Implementation status

## M2a: local agent runtime — v0.2.0

Implemented on top of M1: three logical agents in a persistent Python worker; Coordinator-only delegation; six strict decision types; role-specific source read tools; saved observations, decisions, gateway verdicts and tool results; specialist intent/evidence reports; durable waiting/resumption; staff pause/retry controls; escalation and named staff acceptance; a staff timeline; forward database migration `0002`; an organiser JSON HTTP adapter; an explicitly labelled deterministic simulation; bounded retries, steps, request sizes and a shared live-call budget.

**Direct Claude addition (11 September):** `anthropic` mode uses the Messages API through the same typed decision/policy boundary. Migration `0003` preserves runs and allows the new provider. Both live providers and the one-call `model-check` share the persisted call limit and pacing. Provider credentials are backend-only. Follow [CLAUDE_SETUP.md](CLAUDE_SETUP.md). Direct Claude is now connected and tested with paid synthetic dental reviews. The direct adapter uses native JSON schema constraints, followed by the same strict parser and policy gateway. See [live validation](LIVE_CLAUDE_VALIDATION.md) for the outcomes, including earlier rejected attempts.

The organiser adapter follows the public starter-kit protocol and is tested using simulated HTTP responses. **The organiser endpoint has not been live-verified: its private team API URL/key have not been supplied.** Default mode is `mock`; model, mock and rule origins are distinct. No failed organiser call falls back to simulation.

Dental, myopia and antenatal cases use the shared runtime. A mixed date/preparation request exercises both specialists. Reply intent is unverified staff-entered demo data. A staff clinical flag creates a rule-origin RED handoff without requiring a model. Automatic clinical text/voice detection is pending.

M1 authentication, current clinic membership checks, Origin/CSRF protection, synthetic detection and leased foundation jobs remain. The old two-action draft validator is replaced by the current runtime contract; see [agent-decision-v1.json](contracts/agent-decision-v1.json).

## Completion and data boundary

`FollowupCase.state` remains `NEW`. Agent runs have their own status. An escalated run is not complete until a named staff member accepts its handoff and the Coordinator verifies that evidence. This completes automation only; the staff task remains open. No appointment has been booked, updated or clinically resolved by this release.

Six new tables store runs, steps, delegations, staff events, handoffs and the shared budget. Original migration `0001` is unchanged. The mock source has no write operation or separate source database. Three agents are logical roles, not three independently deployed services. No LangGraph dependency is used.

## Still pending

Patient identity/consent, staff MFA, patient app/text/voice conversation, preference storage, source-owned booking writes, reviewed uploads, reminder delivery, WhatsApp/SMS/telephone, push/calendar, Singpass, clinically reviewed content/policies, retention controls, Terraform and cloud hosting are not implemented. Future features in the historical design pack should not be presented as delivered.

The application is local and synthetic, with the web port bound to 127.0.0.1. Existing HTTP session authentication does not make it suitable for public hosting or real patient data. Distributed login limits and reviewed immutable deployment image/action references remain deployment work.

## Verify and demonstrate

Use [AGENT_RUNTIME.md](AGENT_RUNTIME.md) for the updated team walkthrough and [VALIDATION.md](VALIDATION.md) for recorded checks. GitHub Actions must be verified after a commit is pushed; local tests do not establish remote CI success. Engineering tests are separate from the planned 60 hackathon evaluation scenarios.
