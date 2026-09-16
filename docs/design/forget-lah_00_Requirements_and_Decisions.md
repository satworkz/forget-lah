# forget-lah: requirements and decisions

10 September 2026 | v2.1 | Current design baseline | All implementation work is still planned

## 1. Product promise

**forget-lah helps clinics complete patient follow-up through accessible conversations, approved preparation reminders and accountable staff handoffs.** It supports upcoming appointments, missed appointments and source-defined routine recalls that have become due or overdue without a booking.

The selected problem statement concerns dental clinics manually identifying overdue follow-ups and contacting patients individually. Dental remains the anchor demonstration. Myopia and antenatal care demonstrate reuse of the same administrative follow-up workflow with different approved source data. They are not claims of clinical efficacy or automated medical triage.

The name leaves room for future reminder products. General-purpose reminders, non-healthcare workflows, a marketplace and a configurable workflow designer are explicitly outside this hackathon.

## 2. Requirements recorded from the user

| ID | Requirement | Design response and acceptance evidence |
|---|---|---|
| R01 | Rename to forget-lah | New design pack, future UI/repository/branding use forget-lah; Python imports use remind |
| R02 | Simple, extensible and scalable | Modular Python backend, one relational store, replaceable adapters and one React frontend; demonstrate a second worker without duplicate actions, not unmeasured scale claims |
| R03 | Final-week DevOps | Git, CI, migrations, secrets hygiene and containers from day one; final week completes deployment, rollback, restore, security and performance checks |
| R04 | Automate wherever possible | One-command development start, migrations, deterministic seeds, test suites, Terraform plans and scripted deployment; external access and source approval remain explicit |
| R05 | Simple client app with intelligent voice/text | Optional installable PWA; agent-backed text, push-to-talk on a tested browser, transcript confirmation and read-aloud; text/keypad alternatives |
| R06 | Push and possible mobile calendar integration | Permission-based Web Push and explicit .ics export of a verified appointment; automatic two-way calendar synchronisation deferred |
| R07 | Clinics without appointment/record APIs | CSV schedule and note uploads, preview, validation and staff publication; source adapter exposes reviewed snapshots and limited capabilities |
| R08 | Privacy and authentication/authorisation | Tenant and patient scoping, named staff accounts, MFA, scoped patient sessions, encrypted sensitive data, consent checks, redacted traces and upload controls |
| R09 | Singpass where applicable | Patient portal authentication via dedicated adapter; staging integration if access arrives; labelled identity simulation otherwise; no fabricated Singpass success |
| R10 | Preserve Patient Follow-up | No independent slot inventory, calendar management, clinical advice, billing or full patient record system |
| R11 | Respect latest organiser AWS rules | Local development; platform integration testing and hosting in the organiser environment; supplied model endpoint; approximately USD 100 shared across hosting and inference |
| R12 | Beginner step-by-step guidance later | Guide 03 defines ordered setup/build/run/test checkpoints and expected evidence; actual commands will be verified against delivered code |
| R13 | Personal AWS available if credit becomes limiting | User is willing to fund supplementary capacity; retain the permitted Lightsail deployment shape, separate account state and prove redeployment early; organiser acceptance remains a separate question |

## 3. Scope priorities

**Committed core:** three agents and visible adaptive tool use; persistent recovery; one complete dental journey; dental/myopia/antenatal configurations and demonstrations; WhatsApp and bounded voice provider adapters; PWA text flow and tested voice input; push on a supported test device; calendar export; reviewed CSV/TXT imports; staff handoff queue; named staff/patient authentication; automated local setup and meaningful tests.

**Conditional integrations:** real Singpass staging; organiser AWS automation; actual WhatsApp templates, outbound calls and browser speech depend on credentials, approved usage and tested device support. These have early spikes and explicit evidence labels. A simulated integration must never be reported as live. If an external dependency remains unavailable, the core runs with synthetic adapters and the exact limitation is disclosed.

**Stretch only after core passes:** scanned-paper/photo/PDF extraction to a staff-review draft; a second reviewed spoken language on all channels; advanced deployment dashboards. Do not silently remove a requested core feature because it is difficult: raise a scope decision if its spike fails.

**Future only:** native App Store/Play Store applications, live speech interruption/streaming, Google/Apple calendar write-back, automatic handwriting-to-outreach, full EHR/appointment management, general-purpose reminder workflows, Kubernetes, multiple cloud environments and autonomous clinical decisions.

## 4. Decisions that protect the scope

1. Automatic routine follow-up begins after a clinic has enrolled contacts, approved templates/policies and published valid source data. This setup is distinct from approving every agent action.
2. If a clinic has booking APIs, a confirmed patient choice may be committed through that source's safe operation. forget-lah never owns slot availability.
3. If a clinic only uploads schedules, the agent can confirm attendance intent for the published appointment and collect alternative-date preferences. A change request ends in an owned staff handoff until staff records the externally confirmed outcome. No invented availability or automatic booking success.
4. Patient app use and installation are optional. Channel choice, voice access and caregiver support preserve access for people who do not use smartphones.
5. Singpass establishes an identity. Our clinic membership, patient linkage, representative authority and consent checks establish permission. A parent logging in is not automatically authorised for a child's myopia follow-up.
6. No preference on record does not mean permission to contact. Use a clinic-approved default only when the relevant channel/purpose is permitted.
7. Agent goals, tool schemas, policy checks, outcome evidence and restart recovery are mandatory. More model calls or more agent names are not success metrics.

## 5. What the attached kickoff slides actually say

Source: user-provided `IMG_1658.jpeg`, titled AWS Resource Usage Model.

- AWS resources are provided for deployment and LLM prompts.
- Participants are advised to develop locally using their own AI client tools; examples include Kiro, Claude Code, Cursor and Copilot.
- Allowed AWS usage lists Lightsail and JSON API calls to AWS Bedrock's Claude Sonnet 4.5 model.
- JSON format and API usage plan will be shared through Slack; each team's API key will be emailed.
- Exceeding the AWS usage limit may pause the account and affect competition standing.

Source: user-provided `IMG_1657.jpeg`, titled AWS Resource & Kiro Credits.

- Shortlisting round: **7-28 September 2026**; AWS credits shown as **USD 100**; Kiro credits **USD 20 per participant**.
- Finale: **6-10 October 2026**, five public teams plus five SME teams; slide literally says **AWS tokens: 100** and Kiro credits USD 20 per participant.
- The finale's AWS unit is ambiguous. Do not interpret it as 100 model tokens or assume it means another USD 100 credit.

The later organiser clarification supplied by the user takes precedence over earlier slide ambiguity. It specifies an AWS account created in the organiser environment, platform testing/hosting and model inference, and approximately USD 100 per team shared across Lightsail and LLM/API usage. Training and fine-tuning on the platform are prohibited. The private API key identifies team usage; it is separate from AWS account credentials. Preference learning in forget-lah means consented database updates, not model training.

The user is willing to use a personal AWS account for extra development capacity. Plan for portable deployment, but do not interpret this as organiser approval for alternative hosting or model services. Calling the team endpoint from a personal server still uses the team API allowance. Additional AWS services and third-party provider coverage remain unconfirmed. See [the platform review](forget-lah_05_Platform_Alignment.md) for technical evidence and the first implementation checks.

## 6. Coordinator questions: prepared for the user to send

We are building forget-lah for Patient Follow-up and plan to develop locally, deploy using Lightsail and call the supplied Claude Sonnet 4.5 JSON endpoint. Please clarify:

1. May personal AWS provide supplementary development/testing while we also test and host on the supplied platform? May the team API be called from local/personal environments, is there an IP allowlist, and can its allowance be topped up? We understand hosting and inference share the approximately USD 100 team allocation.
2. Which Lightsail region, bundle sizes and resources are permitted? Are static IPs, snapshots, DNS, Terraform and limited IAM/API credentials available?
3. Are additional services such as S3, Cognito, SES, Transcribe, Secrets Manager, CloudWatch or GitHub-to-AWS OIDC allowed, or should the solution stay within Lightsail and the provided model endpoint?
4. Please confirm the current team request/response contract, model identifier, supported roles/parameters, request-byte and output limits, timeout, concurrency/rate limits, error responses and usage reporting. We plan a direct HTTP client and application-validated JSON agent steps, without relying on native tool calling. Is that supported, and is any named agent framework mandatory?
5. What are the model region, logging/retention settings and data-handling rules? Are third-party messaging, speech, push services and Singpass staging permitted?
6. What does the finale slide's 'AWS tokens: 100' mean, and what are the exact shortlisting submission/demo times and presentation/Q&A limits?

These remaining questions concern access and external policy, not a reason to stop local synthetic development. Prove a minimal organiser deployment and live model round trip early; do not defer compatibility to the final week. Do not assume permission to add supplementary AWS services. No message has been sent on the user's behalf.

## 7. Seven rubric items mapped to evidence

Source: user-provided `IMG_1653.jpeg`. No weights are visible; none are invented.

| Exact rubric item | Evidence to show |
|---|---|
| Goal & Scope Definition | Dental staff baseline, three follow-up triggers, explicit completion and handoff definitions, inclusion benefit |
| Architecture & Reasoning Loop | Three role-specific agents, observe/decide/tool/inspect/adapt loop, checkpoints, non-obvious delegation and restart recovery |
| Tool Use & Integration | Typed tools, source capability checks, API and import adapters, actual model/provider results with source versions |
| Autonomy & Human-in-the-Loop | Green/Amber/Red policy, bounded retries, exact confirmation evidence and named staff acceptance |
| Safety, Security & Guardrails | Prompt-injection resistance, least privilege, tenant isolation, import quarantine, consent revocation and identity checks |
| Observability & Evaluation | Redacted agent traces; golden-path, integration and adversarial cases; measured results and denominators |
| Platform & Tooling Usage | Idiomatic FastAPI/Pydantic, tested multi-agent runtime, reproducible Compose/Terraform workflow and actual organiser endpoint integration |

## 8. Design decisions awaiting implementation evidence

Technology versions, phone/browser support, speech-language quality, source-import freshness thresholds, approved medical wording, real identity onboarding, cloud permissions and model quotas must be verified during early spikes. The design offers a feasible path, not a claim that those external integrations are already available.

This document is the durable project note requested by the user. The future generic-product direction is recorded but must not expand the hackathon backlog.
