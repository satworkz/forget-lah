# Live Claude validation

11 September 2026 | forget-lah M2a v0.2.0 | Local synthetic demonstration

## Result

**The direct Claude connection and one fresh dental review passed.** The review used all three logical agents, resumed after a worker restart, and completed only after a named staff member accepted the handoff. This verifies the current read-only agent milestone. Patient messaging, booking updates and the full hackathon product are still pending.

| Evidence | Recorded result |
| --- | --- |
| Provider / configured model | Direct Anthropic Messages API / `claude-sonnet-4-5-20250929` |
| Run ID | `28046e99-99b1-45b4-8837-6a1f867ed8b8` |
| Source | Synthetic dental clinic, `synthetic-v1` |
| Decisions / calls | 13 decisions; 13 model attempts; zero retries or rejected steps in this run |
| Reported input / output tokens | 25,936 / 1,050 |
| Sum of recorded model-call latency | 39.509 seconds; excludes waiting for staff and worker scheduling |
| Specialist evidence | Engagement cited its own current source read; Preparation cited its approved-instruction and prerequisite reads |
| Completion | Model proposed COMPLETE after persisted named staff acceptance; gateway verified the handoff ID |
| Database | PostgreSQL 17, migrations through `0003`; previous records preserved |
| Automated tests | 111 passed, zero skipped in Docker, including eight PostgreSQL cases |
| Other checks | Ruff lint/format, TypeScript/Vite and Docker web build passed; 11 JSON documentation examples parsed |

The browser also confirmed that an earlier myopia review still displays **Simulation mode**, while the new dental review displays **Direct Claude API mode**.

The run and evidence were read back from PostgreSQL to verify role/evidence ownership, successful tool outcomes, event types, request outcomes and handoff binding. All 13 steps are model-origin and gateway-allowed. No simulation fallback was used.

Provider source SHA-256 for this verification: `0b432e80ee3e12a83905fb0911447ce5092905174ca62ea42d33a59ba7311b63`. This is an uncommitted local working-tree result, not a remote GitHub Actions run or a deployed release.

## Repeat the flow

1. Start Docker Desktop and run `./scripts/dev.ps1 up` in the project folder.
2. Open **http://localhost:8080**, refresh after an application rebuild, and sign in using your private local demo login.
3. Confirm **Direct Claude API mode**, open **Mr Lim**, then choose **Start another demo run**. A previous review keeps its original mode.
4. Watch the Coordinator read source context and delegate to Engagement. Wait until the screen says it is waiting for a fictional reply. No patient has been contacted.
5. Optional persistence check: run `docker compose restart worker`, refresh the page and reopen Mr Lim. The saved waiting review should still be present without another model call.
6. Submit this fictional reply: **Can I come next Friday? What should I bring?**
7. Inspect the two specialist reports. In the verified run, Engagement returned the alternative-date intent first; Preparation then read both instructions and prerequisites. The agent may choose another valid order.
8. The screen should show an **unowned Amber handoff** because booking changes are not available in this release. Click **Accept handoff as me**.
9. Confirm **Completed**, a named owner, and the final `STAFF_HANDOFF_ACCEPTED` decision. The clinic's task stays open; the application has not booked an appointment.

The recorded initial waiting state survived a worker restart. During a web-container replacement the browser needed a refresh before submitting the reply; the saved review was preserved and the database confirmed no duplicate event. The completed run contains exactly one demo-reply event and one acceptance event.

## Why the implementation changed during testing

Earlier live attempts are retained in the database. They are not counted as clean passes:

| Earlier run | Outcome and learning |
| --- | --- |
| `9dd91ff3-584d-4995-ad13-c34362331840` | Reached staff ownership too early because booking tools were unavailable; it did not demonstrate both specialists. |
| `538423c7-606b-4641-b4c9-10351dc60cd6` | Preparation initially omitted prerequisite evidence. The gateway blocked it. After adding explicit missing-evidence input and a staff retry, both specialists and owned handoff completed. |
| `1e41cfab-a164-4c87-a005-4a275f7d341b` | Exposed an early intent assertion, an extra JSON field, a target/reason mismatch and repeated delegation. It eventually completed a handoff after repairs, but did not satisfy the two-specialist success criterion. |

The fixes were exact native output schemas for direct Claude, explicit decision schemas in the organiser prompt, current-role evidence requirements, delegation target/reason binding, omission of already-returned specialists for an unchanged event, and a policy check preventing Engagement intent returns before a reply event. Full application validation still runs after native schema generation. Unknown fields and invented evidence are rejected rather than stripped away.

## Usage and limits

At the end of verification, the local database recorded **55 reserved live calls against a temporary limit of 80** for the UTC day. These include earlier attempts and diagnostic/connection checks; they are not all part of the final 13-call journey. The repository default remains 40. Resets follow UTC dates. The local cap is a request guard, not an account-credit balance or dollar limit; consult the provider Console for actual charges.

The API key remains in ignored local configuration. The record contains no credentials, raw model reasoning or real patient data. Schema definitions contain protocol constants only; case identifiers remain in request context.

## What this does not establish

- General model reliability or completion of the proposed 60 routine, edge and safety evaluations. This is one successful fresh dental journey following development fixes, not an accuracy percentage.
- Live myopia or antenatal behavior. Their existing recorded demonstrations used simulation; the staff clinical-concern button demonstrates a deterministic rule.
- Automatic clinical triage, real-patient identity/consent, messaging, preference learning, bookings, uploads, push/calendar, Singpass or production readiness.
- Organiser gateway compatibility with these prompts in a live account. Its HTTP adapter is tested with simulated responses and must be exercised against the private team endpoint before submission.

Use [CLAUDE_SETUP.md](CLAUDE_SETUP.md) for connection/provider settings and [NEXT_MILESTONE.md](NEXT_MILESTONE.md) for the next implementation steps. The 111 engineering tests include HTTP test doubles; they make no paid calls. Two existing third-party deprecation warnings remain.
