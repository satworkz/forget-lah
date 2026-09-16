# Next milestone: the first authenticated patient journey

The bounded M2a agent runtime is now implemented. See [AGENT_RUNTIME.md](AGENT_RUNTIME.md) for what the team can run today.

1. Direct Claude is connected and one fresh dental agent review has passed; see [the live validation record](LIVE_CLAUDE_VALIDATION.md). Keep simulation for repeatable offline tests. In parallel, obtain the organiser's private endpoint details and rerun the connection/journey checks there using [CLAUDE_SETUP.md](CLAUDE_SETUP.md). The organiser gateway has not been live-verified.
2. Evaluate real-model intent, specialist selection, source grounding, malformed responses and adversarial replies. Record source/model/config versions and actual usage. The engineering tests are not the proposed 60 model evaluation scenarios.
3. Add staff MFA and patient identity/consent enrolment. Implement a simple patient text flow with signed, replay-resistant inbound events. Staff demo replies must never become identity proof.
4. Add realistic source-owned booking APIs with atomic slot conflicts, idempotency and source success evidence. Re-read availability and require current explicit patient confirmation before any write. Keep the product focused on follow-up.
5. Complete the dental journey through verified attendance/booking plus approved preparation acknowledgement, or an owned staff handoff. Add explicitly confirmed preferences and reachable escalation ownership.
6. Reuse the framework for myopia and antenatal data, with clinician-reviewed instructions and escalation rules. Clinical assessment is outside the agent's authority; do not infer urgency from tone alone.
7. Spike external messaging/voice, Singpass and organiser hosting access early. Add the scoped patient UI, reviewed uploads, push/calendar and remaining channels only after the first reliable journey. Report mock/live status explicitly.
8. Automate deployment using Terraform and CI/CD after confirming the organiser's account/service constraints. Add secrets management, HTTPS, retention, monitoring, backups and rollout verification before public exposure.

Team split: agent/policy owner; source/data owner; UI/channels owner; platform/quality owner. Pair on identity/security and rehearse using measured evidence.
