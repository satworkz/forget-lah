# Next milestone: a complete dental follow-up journey

1. Run this foundation in the actual project folder and verify Docker/CI. Preserve the current design constraints.
2. Obtain the organiser's redacted API contract and configure the team key privately. Prove the largest realistic prompt → JSON proposal → permitted read tool → actual result → adapted model decision loop. Use direct HTTP and strict validation; do not assume native tool calls.
3. Add full AgentStep and ToolResult unions, authoritative policy context and database evidence; then add agent run/step/delegation/checkpoint persistence. Only the Coordinator delegates. Test restart, stale results and permission revocation.
4. Complete staff MFA and patient identity/consent enrolment; implement the patient text flow and a realistic mock booking API with atomic slot conflicts. Every appointment write requires current explicit confirmation and source success.
5. Implement the dental journey through verified booking/attendance plus preparation acknowledgement or owned staff handoff. Add patient preferences with explicit confirmation. No clinical advice or urgency downgrade based on tone.
6. Start external WhatsApp/voice/Singpass and organiser HTTPS deployment spikes while the local journey is built. Report access blockers and simulated/live status explicitly. Do not leave transport compatibility to the final week.
7. Reuse the workflow for myopia and antenatal fixtures; add reviewed imports, speech/push/calendar and the remaining scoped channels. Complete the 60 evaluation scenarios and measured demo evidence.

Recommended team pairing: lead owns agents/policy; data owner owns source contracts/migrations; UI/channels owner owns patient/staff experience; platform/quality owner owns deployment and reproducible tests, pairing with the lead on identity/security.
