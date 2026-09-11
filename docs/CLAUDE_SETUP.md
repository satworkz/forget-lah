# forget-lah: connect your own Claude API

11 September 2026 | Team setup guide | Direct Claude connection added to M2a

Use this guide first. It connects the existing agents to a real model. Patient messaging, booking updates and the other product features still need the delivery steps at the end.

## 1. What you are creating

Create an **Anthropic Claude Console account and API key**. Anthropic already hosts the model. You do not need to create an AWS account, deploy a model server or install Python on your laptop for this connection.

The backend worker calls `https://api.anthropic.com/v1/messages`. The browser continues to call only our FastAPI backend. All three agents use the same private backend connection.

Claude chat subscriptions and API billing are separate. Buying Claude Pro is not necessary for this application. API usage is charged according to usage, rather than unlimited chat questions. [Official explanation](https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-do-i-have-to-pay-separately-to-use-the-claude-api-and-console).

## 2. Create the account and key

1. Open [Claude Console](https://platform.claude.com/). Sign up or sign in and complete the account onboarding.
2. Open **Settings → Billing → Buy credits**. For the first connection tests, I suggest a small balance, such as USD 10 if offered. This is a starting budget, not an estimate for the entire project. Leave automatic reload off initially. Follow the amount and payment options shown in your account. [Official billing instructions](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage).
3. Open **Settings → API keys → Create key**. Name it `forget-lah-local-dev`. For your own local development, link it to yourself. If workspace selection is available, scope it to the workspace you will use for this project. Set an expiry after the demo period.
4. Copy the full key when it is shown. Save it in a password manager and in the private local file described below. The Console shows the full key only at creation. Do not paste it into chat, GitHub, screenshots or a team document. [Official key instructions](https://platform.claude.com/docs/en/get-api-key).

For shared hosted use later, create a service-account key with access restricted to the project workspace. Teammates should not copy your personal development key.

## 3. Save the configuration on your laptop

Open `C:\working\projects\forget-lah` in VS Code. Open the existing **`.env`** file at the top of that folder. Preserve all database passwords and login settings already there. Add the following lines, or edit their existing entries so each setting appears only once:

```dotenv
AGENT_MODEL_MODE=anthropic
ANTHROPIC_API_KEY=PASTE_YOUR_PRIVATE_KEY_HERE
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
AGENT_DAILY_CALL_LIMIT=40
AGENT_MIN_INTERVAL_SECONDS=2
```

Replace the key placeholder with your real key, then save. Do not place the key in `.env.example`, a frontend file or a variable beginning with `VITE_`.

If your key has access to multiple workspaces, also add `ANTHROPIC_WORKSPACE_ID=` with your selected Console workspace ID. A key scoped to one workspace does not need this extra setting. This controls the `anthropic-workspace-id` request header. [Authentication guidance](https://platform.claude.com/docs/en/get-api-key).

**Model choice:** start with Sonnet 4.5 to match the organiser's stated model family. Anthropic currently lists `claude-sonnet-4-5-20250929` as active. Its “not sooner than” retirement date is not an announced retirement date. Check availability before the final demo. The model name is configurable; changing models requires rerunning the evaluations. [Official model lifecycle](https://platform.claude.com/docs/en/about-claude/model-deprecations).

The organiser's Bedrock-style model ID belongs in `LLM_MODEL`. It is different from the direct Claude model ID above. Leave the organiser URL and key empty until you receive them.

## 4. Start and check the connection

Before switching providers, finish any active simulation runs through named staff handoff, or leave the application in simulation until they are finished. A run keeps its original provider; switching the server configuration does not convert an existing run.

In VS Code, open **Terminal → New Terminal**. With Docker Desktop running, enter:

```powershell
./scripts/dev.ps1 up
./scripts/dev.ps1 model-check
```

`up` rebuilds the application and applies database migration `0003`. It preserves your cases, previous runs, passwords and usage counter. `model-check` sends **one synthetic request** through the chosen provider and validates the returned agent proposal. It does not contact a patient, execute a tool or change an appointment. It reserves one call against the application's daily limit.

Success includes:

```text
'ok': True, 'code': 'MODEL_CONNECTION_VERIFIED', 'provider': 'anthropic'
```

This proves the API connection and one valid decision. It does not prove that every patient journey or safety scenario works.

Common results:

| Result | What to do |
|---|---|
| `SIMULATION_SELECTED` | Set `AGENT_MODEL_MODE=anthropic`, save, and run `up` again. |
| `MODEL_NOT_CONFIGURED` | Check that your key is saved in the root `.env`, with no duplicate entries. |
| `MODEL_ACCESS_DENIED` | Check the key, expiry and workspace access in Console. Do not share the key to troubleshoot. |
| `MODEL_HTTP_ERROR` | Check billing balance and the exact model ID. Share only this error code for investigation. |
| `MODEL_RATE_LIMITED` / `MODEL_UNAVAILABLE` | Wait before one retry; avoid repeatedly running checks. |
| `MODEL_PACING` | Wait the reported number of seconds, then try once. |
| `DAILY_MODEL_BUDGET_EXHAUSTED` | The shared local call limit has been reached. It resets by UTC date. Review actual Console usage before changing the limit. |
| `MODEL_SCHEMA_INVALID` / `MODEL_UNEXPECTED_DECISION` | Connection responded, but the agent contract did not pass. We need to inspect the integration before claiming success. |
| `DATABASE_NOT_READY` | Run `up`, check service status, and retry after the database migration finishes. |

The call limit counts reserved requests, including failed attempts, across both live providers and the connection check. It is not a dollar limit. Console billing is the authority for actual charges. Other laptops and applications using your account do not share this local database counter.

## 5. Run one live agent journey

1. Open **http://localhost:8080** and sign in with your existing local demo login.
2. Confirm the banner says **Direct Claude API mode**.
3. Open Mr Lim's dental case and start a **new** agent review. Earlier completed simulation runs remain simulation evidence.
4. Watch the Coordinator's decision, the actual mock-clinic read result and delegation to Engagement. A valid initial journey reaches a saved wait for a fictional reply. Live model choices may differ; an error or unexpected handoff needs investigation.
5. Enter a fictional reply such as `Can I come next Friday? What should I bring?`.
6. Inspect the specialist findings and source evidence. The current release can only read source records, so it should reach a staff handoff when a booking change is needed.
7. Accept the handoff as the signed-in staff member. Confirm that the Coordinator completes using that acceptance evidence.

Use [the agent walkthrough](AGENT_RUNTIME.md) for the myopia and antenatal flows. The clinical-concern button is a deterministic staff flag; it does not demonstrate automatic clinical triage by Claude. Keep using synthetic records and fictional replies.

## 6. Switch to the organiser later

Finish active direct-Claude runs first. Save the organiser's private values locally, then change these settings:

```dotenv
AGENT_MODEL_MODE=organiser
LLM_GATEWAY_URL=PASTE_THE_ORGANISER_BASE_URL_HERE
LLM_GATEWAY_API_KEY=PASTE_THE_ORGANISER_TEAM_KEY_HERE
LLM_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Use the actual URL/model from the latest organiser email. Run `up`, `model-check`, and the same journey/evaluation suite again. The provider adapters are implemented, so the agents, policy and database do not need a redesign. Provider prompts, limits and model behavior can still differ.

The direct API uses Anthropic's Messages format with native structured output; the organiser adapter uses its Ollama-style `/api/chat` format. **Changing only the URL is insufficient.** `AGENT_MODEL_MODE` selects the correct adapter and credential. Failed live calls never fall back to simulated decisions.

Your account supports development while organiser access is pending. Complete the required testing, hosting and inference checks on their platform before submission; confirm any competition-specific exception with the coordinators. Buying your own API credits does not change their rules.

## 7. Steps to complete the hackathon product

The API connection is one milestone. The full product is still in progress. Deliver in this order:

| Order | Deliverable | Evidence that it is ready |
|---|---|---|
| 1 | Live Claude agent loop | Connection check and dental read/delegate/wait/handoff journey pass with recorded model usage. |
| 2 | Patient text interface, identity and consent; staff MFA | A patient can access only their own case, reply and confirm contact preferences; staff-only demo replies cannot establish patient identity. |
| 3 | Source-owned booking integration | The agent finds authoritative slots, obtains explicit patient confirmation and verifies the source's booking response; retries do not duplicate bookings and stale slots are rejected. |
| 4 | Complete dental follow-up | Upcoming, missed and due-but-unbooked cases reach confirmed attendance/booking and approved preparation acknowledgement, or an owned staff handoff. No appointment engine is built inside forget-lah. |
| 5 | Myopia and antenatal journeys; reviewed uploads | The same agents handle specialty fixtures and approved notes; import-only clinics route rescheduling to staff when no booking API exists. |
| 6 | Messaging, voice and mobile features | Prove provider callbacks and permissions with team-controlled test contacts; add WhatsApp/SMS, voice fallback, optional PWA push/calendar. Integrate Singpass staging when authorised access is available. |
| 7 | Evaluation and deployment | Run the 60 agreed routine/edge/safety scenarios, rehearse the three-use-case demo, then deploy through Terraform/CI with HTTPS, secrets, monitoring and backup/restore verification. |

Start provider and Singpass onboarding early, alongside the patient journey work. External approvals are separate dependencies; show each integration honestly as implemented, simulated or pending. Keep the default offline test suite repeatable and free of paid model calls.

The direct connection is verified. Paid synthetic dental reviews have exercised the agent loop, including failures that led to stricter schemas and evidence requirements. Read [the live validation record](LIVE_CLAUDE_VALIDATION.md) for exact outcomes; one journey does not establish general model accuracy. The organiser endpoint and the full product remain pending.
