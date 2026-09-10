# re-mind: platform alignment and early technical checks

10 September 2026 | v2.1 addendum | Documentation review complete; live integration checks not yet performed

## 1. Decision

Keep the agent-centric architecture: three role-specific agents, one durable Python runtime, a deterministic Policy/Tool Gateway, FastAPI, PostgreSQL, React/PWA and replaceable source/channel/model adapters. The clarification calls for a focused integration update, not a product redesign.

Use local development with synthetic fixtures and test doubles. Integrate and test against the organiser platform early. The user is willing to fund a personal AWS environment if needed; treat that as supplementary capacity subject to organiser acceptance, not the only environment until the last week.

The latest organiser clarification supplied by the user is the event-specific authority: organiser-environment AWS account; testing and hosting plus model inference on that platform; approximately USD 100 shared across Lightsail and LLM/API usage; no platform training or fine-tuning. The actual private onboarding document and team endpoint contract have not been provided in this workspace. No account or endpoint has been accessed.

## 2. What the starter kit establishes

The [starter kit's tool-calling section](https://github.com/kenken64/ShowMeYourAgent-Starter-Kit#how-tool-calling-works-here) describes an Ollama-compatible /api/chat interface, X-API-Key authentication in its direct example, and JSON tool requests embedded in model text. It says native tools are ignored. Its LangGraph example uses custom parsing; that is not evidence of full native compatibility. Other client examples use different headers/aliases, so the team's current contract must settle those details.

The [known-issue guidance](https://github.com/kenken64/ShowMeYourAgent-Starter-Kit#step-11--known-issue-aws-waf-blocks-large-request-bodies) reports request-size/WAF failures, including around 8 KiB in an example setup, and the README also reports 403 responses under rapid calls. These are warnings to validate against our endpoint, not a measured limit or error contract for our team.

This review inspected the README. Linked Python file bodies were unavailable through the web reader; filenames, including a native-tool example, are not verification that the deployed API supports a feature. Record the repository commit and the actual endpoint contract when implementing.

## 3. Technical implementation consequences

| Area | Decision for re-mind | Acceptance evidence |
|---|---|---|
| Transport | Small httpx adapter; configuration selects endpoint, model and proven authentication. No local Ollama server or GPU is needed merely to speak the remote protocol. Do not assume OpenAI or Anthropic SDK wire compatibility. | A successful synthetic request using the team's actual contract, with sanitised request/response fixtures |
| Agent tool use | Put compact allowed-tool definitions and AgentStep schema in the prompt; strict JSON parsing, Pydantic validation, policy checks, known-function dispatch, actual result feedback | Real model chooses a tool, application executes it, next model decision changes when the source returns no suitable result |
| Framework | Retain our typed Python loop. Named working clients are compatibility examples unless organisers state they are mandatory. Do not add a general-purpose shell agent to solve a model transport problem. | Explicit checkpoints, bounded delegation, restart/resume and traceable role-specific decisions |
| Output handling | Verify model text extraction, truncation/finish indication and usage metadata. Missing usage stays unknown. No fabricated tool results, tolerant execution of arbitrary XML, or eval of model code. | Malformed JSON, unknown tool, wrong reason/action pairing and truncated output cause no patient action |
| Prompt size | Send only current case evidence and relevant tools. Keep full history/uploads in our database, not every prompt. Measure complete serialised UTF-8 bytes, including non-English text. | Largest representative role prompt succeeds, not only a hello-world message |
| Quotas and errors | Bound decisions, output, time and concurrency across workers. Classify authentication, quota, body-limit and transient errors from documented evidence. Do not retry every 403 or weaken shared WAF controls. | Controlled low-volume checks; safe pause on persistent failure; bounded retry only for proven transient conditions |
| Persistence | Store jobs, evidence and resumable state in PostgreSQL; acknowledge valid webhooks after durable enqueue | Duplicate callback plus process restart produces one business effect |
| Permissions | Model key stays server-side; the local gateway reloads patient/clinic identity, consent and source state | Cross-tenant, revoked-consent and prompt-injection attempts cannot execute tools |

The organiser's remote LLM gateway provides model access. Our local Policy/Tool Gateway decides whether an action is authorised. They are different components. Native function calling is a transport convenience; genuine agent behaviour is demonstrated by decisions, tool outcomes, adaptation and durable completion evidence.

A patient preference saved for the next visit is application memory. It does not train or fine-tune Claude.

## 4. Personal AWS and moving to the organiser account

Recommended approach: recreate the permitted infrastructure and redeploy the same release. AWS recommends stateless compute and infrastructure as code for account transitions; its documented Lightsail snapshot migration route introduces EC2 and key-sharing steps, which would add dependencies outside our baseline. We should not depend on that route. [AWS migration guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/transitioning-to-multiple-aws-accounts/resource-migration.html).

1. Parameterise account, region, instance shape, domain, model URL and provider settings. Use separate Terraform state per account and an expected-account check before apply. Never point an existing personal-account state at organiser credentials to try to move resources.
2. Build one versioned set of Linux container images. Use an approved private registry or transfer release archives securely; do not make ECR, S3, Cognito or another unapproved AWS service a hidden prerequisite.
3. Provision the destination's permitted Lightsail server through Terraform if API permissions allow. If only a supplied server is available, automate application installation and deployment onto that host. Report this limitation accurately.
4. For synthetic demos, prefer migrations plus deterministic reseeding. When preserving state is necessary, pause source outreach and jobs, take a consistent encrypted logical database backup and include required uploads. Restore with outbound actions disabled and preserve idempotency/consent evidence. Data decryption requires the correct protected keys; copying encrypted rows alone is insufficient.
5. Inject destination credentials separately. Reissue sessions as appropriate. Keep a stable controlled HTTPS hostname where possible; reconfigure provider webhooks and identity redirects if URLs change. Test browser push permissions/subscriptions; a different origin may need re-enrolment. Do not assume IPs, keys or registrations follow the server.
6. Run source, auth, webhook, model, restore and worker-restart checks. Enable outreach in one environment only after verification. Leave the old environment available for a controlled rollback with sends paused; never run two copies of the same restored reminder queue.

**Separate costs:** personal AWS pays for resources there. Requests using the organiser model key still consume its team allowance. A personal Bedrock/model adapter is only an optional contingency if the organisers permit it; it does not replace required tests on their gateway. Third-party messaging/voice charges are separate unless the organisers explicitly cover them.

## 5. External dependencies that money alone does not resolve

| Dependency | Verified constraint or unresolved access | Early action |
|---|---|---|
| WhatsApp | Twilio Sandbox requires joined recipients and restricts outbound templates; free-form replies use the service window. A custom recall template needs the appropriate sender/template setup. [Sandbox documentation](https://www.twilio.com/docs/whatsapp/sandbox) | Test one real appointment reminder and reply. Start custom recall-template onboarding immediately if required; never relabel an overdue recall as a booked appointment to fit a template. |
| Telephone | Trial capabilities and verified destinations depend on the actual account. [Current trial guide](https://www.twilio.com/docs/usage/trials/try-out-voice). Singapore domestic outbound calls have caller-ID restrictions. [Singapore provider guidance](https://www.twilio.com/en-us/guidelines/sg/voice) | Prove a call to a team-controlled Singapore number, speech/keypad capture, callback and timeout. Use the provider's permitted caller identity; budget for an appropriate paid account if needed. |
| Speech | The supplied text-model endpoint is not a documented speech service. Browser SpeechRecognition has limited support and can send audio to a remote processor. [MDN](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition) | Separate speech-to-text and text-to-speech from agent reasoning. Test target device/language, transcript review and text/keypad fallback. Do not promise arbitrary-language or emotion-based clinical triage. |
| Mobile push | Apple's Web Push support requires a Home Screen web app and user-granted permission. [WebKit](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/) | Test on the actual demo iPhone/Android device over HTTPS. Push is an optional access route, not an emergency delivery guarantee. |
| Singpass | Developer access requires organisational Corppass authorisation; staging app/test accounts precede integration. [Portal access](https://docs.developer.singpass.gov.sg/docs/singpass-developer-portal-sdp/user-guide/obtaining-access-to-the-singpass-developer-portal-sdp), [quick start](https://docs.developer.singpass.gov.sg/docs/getting-started/quick-start) | Request access now. Keep scoped demo authentication working independently. Label a simulation clearly; personal Singpass possession does not grant developer access. |
| Hosting/network | Account IAM/API permissions, region, domain control, public HTTPS and outbound provider connectivity have not been verified | First deployment must prove these. Build images in CI/local, not on a small demo server. Measure combined API/worker/database memory. |
| Clinical sources | No real clinic API is available; uploaded notes cannot supply an authoritative slot inventory | Use realistic synthetic API contracts with conflicting slots and revisions. Import-only rescheduling ends in an owned staff handoff. |
| Data handling | Model, speech, messaging and push processors may have different locations and retention | Confirm organiser handling rules; use synthetic patients, approved test contacts and minimal model context. Do not claim Singapore-only processing from a Singapore server location. |

PWA text and staff handoffs remain useful while provider approvals are pending. This fallback preserves progress; it does not count as implementing a requested live telephone or Singpass integration. Record each integration as live, simulated, blocked or deferred by an explicit scope decision.

## 6. First 48 hours of implementation: prove the dependencies

These are planned checks, not tests already passed. Start when credentials/access are available; missing access gets a named owner and does not block unrelated local work.

| Owner | Check | Pass condition |
|---|---|---|
| Lead: agents/policy | Gateway round trip using the largest realistic prompt and a bounded read-only tool | Valid AgentStep, actual source result, adapted next decision; malformed/forged output denied |
| Platform owner | Minimal organiser-hosted release | Trusted HTTPS, private database, model connectivity and restart recovery; Terraform or documented supplied-server path |
| Channels/UI owner | WhatsApp and telephone proof; target-device PWA proof | One message/reply and one voice interaction on permitted numbers; microphone/push refusal handled; measured latency |
| Data owner | Migration, seed and source capability contracts | Fresh database plus repeat seed succeeds; unavailable slot and no-API source produce correct outcomes |
| Platform owner with lead | Singpass prerequisites and basic app authorisation | Staging access status recorded; demo tenant/patient isolation passes independently |

Within week one, deploy a small vertical slice to the organiser account. During week two, rehearse rebuilding it from the same release with reseed/restore. Keep final week for hardening, evaluations and presentation. Source deadlines remain those in the requirements register.

## 7. Remaining organiser questions

These are prepared questions, not messages sent on the user's behalf.

1. Is a custom Python client with application-managed JSON tools accepted, and is any agent framework mandatory?
2. What are the exact team API model/envelope, authentication, supported roles/parameters, maximum request bytes/output, timeout, rate/concurrency limits, error meanings and usage dashboard? Is the README's body-size issue still present?
3. May we call the team endpoint from local/personal AWS hosts? Are there IP restrictions, and is top-up or a separately funded model endpoint permitted for supplementary testing?
4. What permissions do we receive for Lightsail/Terraform, static IPs, DNS, certificates, SSH and outbound HTTPS? Are any additional AWS services mandatory or permitted?
5. Are third-party messaging, speech and Singpass staging permitted, and what are the platform's data location/logging/retention rules?
6. Are personal AWS development and later redeployment acceptable while also meeting the required platform testing/hosting? Which deployment and evidence must judges be able to access?

Use the latest account-creation document for actual onboarding. Keep API keys and AWS credentials in private local/server configuration, never in these guides or chat. No application, cloud resources or live provider calls were created as part of this review.
