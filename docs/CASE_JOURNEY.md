# forget-lah | Read a case from start to finish

The **Case Journey** page brings the saved case records, staff messages, agent decisions, gateway checks and tool results into one timeline. It is a learning and debugging view for your team.

New [patient simulator](PATIENT_SIMULATOR.md) reviews also show the outgoing reminder, source confirmation receipt, acknowledgement and evidence-backed completion. Earlier reviews retain their original capability mode and history.

For a fresh demonstration, use the optional [Reset demo data button](DEMO_RESET.md). New cases receive new identifiers and fresh source snapshots; old case links no longer work after reset.

## 1. Open the page

1. Start Docker Desktop and the app using `./scripts/dev.ps1 up` from the project folder.
2. Open **http://localhost:8080**, refresh the browser and sign in.
3. Beside a patient, select **View full case journey →**. The same button is available inside **Agent activity**.
4. Leave **Review history** on **Latest review**, or select an earlier review. The label shows when it started, its status and whether it used Claude or simulation.
5. Read from the top down. Expand **Inspect input and output** whenever you want the saved message details.

The page refreshes every four seconds. It only reads stored evidence: opening it, switching reviews and refreshing it do **not** call Claude or spend model credits. Use **Back to dashboard** to submit a demo reply, accept a handoff or control a review.

## 2. Follow the story

A typical journey looks like this. Actual decisions can differ between reviews.

| Event | What happened | Component responsible |
| --- | --- | --- |
| Case Identified | A source-defined follow-up was saved as a case. | Candidate detector → PostgreSQL |
| Foundation Case Ready | The foundation job marked the case ready for review. | Foundation worker → PostgreSQL |
| Worker automatically queued this review | Foundation processing finished and the worker registered a review under the clinic service identity. | Worker → PostgreSQL |
| Decision 1: read source | An application rule requested initial clinic context through the gateway, with zero model calls. Inspect the actual result to check whether it succeeded. | Worker, gateway and clinic adapter |
| Decision 2: delegate | The Coordinator assigned a goal to Engagement or Preparation. | Coordinator → worker → specialist role |
| Initial demo wait | After Engagement delegation, the worker reuses saved source evidence and waits for a fictional reply. No Claude call or patient contact occurs. | Worker application rule → gateway → PostgreSQL |
| Staff: demo reply | Staff entered a fictional patient reply in the dashboard. | Staff UI → FastAPI → PostgreSQL |
| Further decisions | The worker resumed the review. Roles read evidence, returned findings or requested staff help. | Worker and agent roles |
| Staff handoff created | A task was added to the staff queue. It does not yet have an accepting staff owner. | Worker → PostgreSQL → staff UI |
| Staff: accept handoff | A signed-in staff member accepted responsibility. | Staff UI → FastAPI → PostgreSQL |
| Complete | The Coordinator verified acceptance and finished automation. The clinic still owns the follow-up work. | Coordinator, gateway and worker |

The **WHERE THIS REVIEW IS NOW** card explains the selected review's current status, including pauses, waiting and staff ownership. A completed review does not mean an appointment was booked or clinical work was completed.

Older reviews keep their original staff-start and model-read records. They are not rewritten to look automatic. Case readiness, automatic registration and a successful source read are separate facts. A missing model configuration creates a paused review with a visible reason.

## 3. Read one decision card

Each decision is broken into numbered activities:

1. **Saved context:** the worker's saved observation contains the selected role, goal, latest event and relevant evidence. Claude does not query PostgreSQL itself.
2. **Proposed decision:** the validated structured response, such as `TOOL`, `DELEGATE`, `RETURN`, `WAIT`, `ESCALATE` or `COMPLETE`.
3. **Permission check:** the deterministic gateway's verdict. `ALLOW` gives permission to proceed; it does not prove an operation succeeded. `DENY` blocks the action.
4. **Actual tool result or saved action:** the returned source evidence, or an explanation of a completed permitted delegation/wait/handoff action.
5. **Recorded outcome:** the saved step status, error code, attempt count and reported token usage where available.

For every activity, the **Input** panel shows the saved data supplied to that stage, or its identifying metadata. The **Output** panel shows what was returned or saved. The small explanation above the panels tells you whether this is saved evidence or an explanation derived from it.

For example, these are three different pieces of evidence within the same decision:

| Evidence | Example | Meaning |
| --- | --- | --- |
| Agent proposal | `tool_name: read_followup_context` | The agent requested this source read. |
| Gateway verdict | `decision: ALLOW`, `risk: GREEN` | Application policy permitted the read. |
| Tool result | `status: succeeded`, `data: {...}` | The adapter actually returned the source data. |

## 4. Understand the counts and labels

- **7 decision steps used** means seven saved decision steps in that review. It is not a checklist with seventeen unfinished tasks. The dashboard's maximum of 24 is a guardrail.
- The numbered activities inside a decision are **not additional Claude decisions**. An API request, a gateway check, a tool result and a database save are separate activities.
- **Model attempts** is the saved attempt counter for a live-model step. Retries can increase it without creating another decision step. It is not a provider billing receipt; a reserved attempt can be interrupted before delivery.
- **Claude decision** indicates live-model origin. **Simulated decision** indicates the deterministic model substitute. **Application rule** identifies ordinary code, including the initial demo wait and staff-flagged escalation. **Application record** identifies other saved staff/run events.
- A rule step still occupies one saved step in the 24-step guardrail, but uses **zero model calls**. Its context shows the rule name and source/delegation references where recorded. Older reviews keep their original model/mock WAIT evidence.
- An observation prepared for a pending step does not itself prove Claude was called. Check its attempt count and outcome.

Use **Show → Agent decisions** to focus on the agent loop, or **Case and staff events** to focus on its triggers and handoff. **Expand all messages** opens the input/output panels; **Collapse messages** makes the page shorter again.

## 5. What the history can show

The page uses the records already persisted by the application. New case detections additionally save the validated synthetic source candidate. Existing cases remain intact; if their original candidate payload was not retained, the page says so and shows the source reference instead.

Times belong to the main saved records. Activities inside a decision are displayed in logical execution order, not as individually timestamped network calls. Historical exact prompts, HTTP headers, individual retry responses and empty worker polls were not saved and cannot be reconstructed. Invalid raw model text and private model reasoning are not displayed.

All reviews for the case are selectable. The timeline combines the case's foundation records with the selected review; it does not mix decisions from different reviews. Staff must be signed in and authorised for that clinic.

This milestone still uses synthetic clinic records and staff-entered demo replies. Patient messaging, voice calls and appointment writes remain future work.
