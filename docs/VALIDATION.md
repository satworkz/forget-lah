## 2026-09-17 — Patient questions separated from preference memory

- Added typed per-turn questions and Preparation answer coverage. Gateway rejects missing/duplicate coverage and invented source quotations. Old `other_concern` records are excluded from effective planning memory, with audit history preserved.
- Automated question tests cover confirmation with an approved answer, unanswered clinic question/callback, unsupported lookup, question without confirmation, and invalid evidence/coverage.
- Full local suite: 268 passed, 15 skipped, one long-conversation request-size regression. Removed unnecessary prompt content; that regression passed on a targeted rerun. Final provider/question suite: 62 passed. Docker PostgreSQL plus question suite: 21 passed. Ruff passed; canonical JSON schema exported; web image built successfully (unchanged frontend build cached).
- Four isolated live Anthropic scenarios passed: exact accompaniment question with an answering note; same question without an answering note; accompaniment question alone (no attendance write); confirmation plus traffic question (limitation, no staff handoff). Confirmation and callback persisted separately; one patient reply per turn. These tests used synthetic source data, not existing dashboard cases. Initial live runs exposed prompt-field confusion, a transient connection failure and request-size issues; corrected runs are the evidence for the result.
- Scope: up to three questions per decision. Source quote validation cannot guarantee semantic relevance, and unknown medical questions require staff review. Organiser live endpoint remains unverified.

## Calendar grounding and composed replies (17 September 2026)

- Live Claude: exact “I already told staff not to schedule on Saturday” with source Friday 18 September produced one combined acknowledgement/clarification, with no booking write or handoff. The next reply confirming the Friday visit completed with one source confirmation receipt.
- A Sunday restriction against a UTC timestamp that falls on Monday in Singapore produced the correct Monday clarification. An explicit request to move to available weekday slots with an empty source produced one truthful no-slots message and the NO_AVAILABLE_SLOTS handoff.
- Final local memory/adaptation/provider/turn-response selection: 84 passed. Full Docker run: 272 passed, three failures were assertions for intentionally replaced wording. Those assertions were aligned with the new text while retaining source-write, availability and handoff checks; the final Docker selection covering those flows and all new turn-response tests passed (11 tests). The full 275-test suite was not repeated after the final explicit-change guard refinement.
- Tests cover a nonconflicting excluded day, a nonconflicting excluded time, Singapore date rollover, absence of intermediate patient acknowledgements, combined response evidence, and an explicit change request that must not be overridden by a compatible existing appointment.
- Ruff and formatting passed; TypeScript/Vite and backend/frontend Docker builds passed. Rebuilt containers are running, readiness is HTTP 200, and authenticated deployed views were checked. Historical messages were preserved; use Start fresh simulator test for a clean replay.

## General patient memory validation (17 September 2026)

- Full Docker regression suite: 270 tests passed, including the existing PostgreSQL checks. After the final audit-ID length and provider output-budget refinements, 73 focused memory/provider/PostgreSQL tests passed against the final source, including a new PostgreSQL memory revision/retraction test. The final source collects 271 tests; the entire 271-test collection was not repeated after those refinements.
- Live Anthropic: all four requested examples passed (Saturday exclusion, English restriction, stop contact, recurring lateness). An independent routine attendance-plus-bring-instructions flow completed successfully after the new needs-review phase. These are synthetic measured examples, not a guarantee for arbitrary language.
- Testing caught and fixed a provider grammar-size error, overlap with the legacy exclusion-saving path, and repeated audit-event uniqueness/length issues. A test with only excluded slots correctly asked for other availability. The language restriction produced the multilingual chooser; known Mandarin is covered by the fixed-acknowledgement/staff-handoff test.
- Automated coverage includes source-quote binding, visit versus future scope, clinic isolation, superseded/retracted history, stop persistence into a fresh review, explicit resume requirements, language handling, and mixed symptom/stop-contact retention.
- Ruff lint/format, TypeScript/Vite build and Docker builds passed. Application migrated to `0006`; readiness returned HTTP 200. Authenticated deployed case views and the preference-control bundle were checked for all three existing demo cases. Existing histories were preserved; no real patient contact or public deployment.
- Remaining limits: full multilingual conversations, real channel opt-out enforcement and real patient consent verification are not implemented. Language restrictions block the English simulator flow and request staff assistance. See FEATURE_GUIDE.md.

## Empathy and recurring concern memory (17 September 2026)

- Live Claude: exact repeated 10 am complaint produced apology, saved excluded time, then clarification; a fresh follow-up recognised the source appointment conflict. A separate one-off complaint produced an apology without persistent exclusions.
- Tests cover both barrier and clarification proposals, acknowledgement order, same-patient reuse, clinic isolation, forgetting, and conflict-aware reminders. Final adaptation/provider/request-size selection: 73 passed. The earlier broader selected Docker run found a request-size failure; compacted Coordinator context and instructions fixed it and the failing check was rerun successfully. That broader selection was not repeated in full after the final refinement.
- Web TypeScript/Vite build and Ruff checks passed. Backend/frontend rebuilt locally; no case history reset and no real patient communication.

## General clarification validation (16 September 2026)

Live Claude produced a waiting clarification (no handoff or booking write) for three distinct ambiguous replies, including “ok, can I send my son?”. A follow-up specifying attendance instead of the patient correctly reached staff review without a source write.

Full Docker suite: 258 tests ran, initially 256 passed and two source-review handoff tests failed because the new fallback was too broad. The fallback now excludes established confirmations, failed source operations and prerequisites requiring staff review. All six targeted boundary tests passed after correction, with both clarification tests repeated after the final policy check. The full suite was not repeated after this boundary correction. Ruff and request-size checks passed. Existing histories were preserved; backend rebuilt/restarted.

# Natural-language scheduling validation (16 September 2026)

- Added rejection/excluded-time filtering tests and end-to-end rule tests for negative-only clarification, including a model proposal to search without positive availability.
- Full Docker regression run found one request-size regression. After compacting context/prompts, the affected provider, clinical-review, recall-booking and adaptation suites all passed; the full suite was not rerun after that prompt refinement.
- Six live Claude interpretations passed: rejected time, competing commitment, rejection of all options, work conflict, positive time bound and corrected preference.
- An isolated multi-turn live journey passed: reject 10 am, clarify, request after 3 pm, offer a real mock-source afternoon slot, accept naturally, verify one source booking receipt and completed acknowledgement. Initial attempt paused on an invalid model evidence ID; the gateway rejected it, and the rerun passed after clearer evidence-copying instructions. This is a measured example, not a guarantee against future model errors.
- Ruff checks/formatting passed. Backend rebuilt and restarted; readiness returned HTTP 200. No existing case data was reset. Organiser live inference remains unverified; its request-size checks use a simulated transport.

# forget-lah agent runtime validation

## Routine confirmation incorrectly classified as symptoms — 15 September 2026

- **243 automated tests passed, zero skips**, including PostgreSQL checks; two existing dependency deprecation warnings remain.
- Added whole-message recognition for “yes I attend, What should I bring?” and excluded symptom reporting for that bounded routine confirmation/preparation grammar. The gateway independently rejects attendance/preparation phrases as symptom evidence, including the observed erroneous quote “yes I attend”. Messages with additional symptoms do not match the full routine grammar and retain the clinical path.
- Live Claude run `a3c676db-ddf9-4112-9fa1-068e0a66cf79` completed the exact reply at step 13, with a source confirmation for 18 September, 10 am SGT and the approved spectacles instruction. No handoff was created. Temporary test access was retired; the earlier false-positive review remains historical evidence.
- Focused tests cover routine completion, a deliberately incorrect administrative symptom quote, genuine clinical escalation and callback ownership/resolution. Backend build, Ruff lint/format and diff checks passed. API/worker were recreated and are running; no frontend changes or migration were required.

## Clinical symptom callback lifecycle — 15 September 2026

- **241 tests passed, zero skips**, including PostgreSQL checks. Coverage includes symptom acknowledgement, separate attendance intention, no routine source write, quote/reply binding rejection, acceptance without completion, required resolution text, owner-only resolution and no further model steps for staff acceptance/resolution.
- Live Anthropic run `5564029b-4186-4f23-800a-ac3bf8d8801a` handled Alex's exact eye-swelling/pain message via `REPORT_SYMPTOMS`. It produced a RED `PATIENT_REPORTED_SYMPTOMS` review and the callback acknowledgement. Authenticated staff API acceptance left it open; a clearly synthetic contact/review outcome resolved it with no extra model calls. Temporary validation access was retired. No real patient contact was made.
- Three additional budget-accounted live inference checks used negated current symptoms, completely resolved historical pain, and a routine bring question; all delegated routine review rather than emitting `REPORT_SYMPTOMS`. These are limited examples, not clinical validation or proof of diagnostic accuracy.
- Ruff lint/format, TypeScript/Vite and backend/web builds passed. API/worker/web were recreated; API is healthy and localhost returns HTTP 200. Schema and [clinical review guide](CLINICAL_REVIEW.md) were updated. No new migration was needed. No browser-layout inspection was performed. Two existing dependency deprecation warnings remain.

## Natural reminder acceptance and parking questions — 15 September 2026

- Added typed, gateway-bound `INTERPRET_ATTENDANCE` for natural replies to existing appointment reminders. Unsupported topic metadata follows the interpretation across roles so Preparation does not investigate parking or escalate merely because it cannot answer. A clarification names the saved appointment date/time; a later reply resumes normally. Parking text is a fixed limitation template, while live Claude performs the classification.
- Live run `2f420ba2-c1d8-4572-88d5-06bb7fa60f16` processed “Yes fine, How about the parking lot availability during that time?” and completed at 14 steps with a source receipt, exact clinic notes and the parking limitation sentence. No handoff. The 21 September, 10 am appointment was retained.
- Live run `d0896091-d43d-42c8-bd97-3ed21d301255` processed “Yes fine? how about the parking lots during that day?”, asked whether the patient was confirming the specific 21 September appointment, then completed after “yes” at 18 steps, without handoff. Temporary validation access was retired. An earlier live failure that escalated during Preparation remains historical evidence; the cross-role topic propagation fixed it.
- The full regression run after the runtime fix had 237 passing tests and one failing new test assertion: the offline model can prepare before interpreting attendance. The assertion was corrected to check propagation after interpretation, and all four focused tests passed (both conversation paths plus wrong reply/source binding rejection). No tests were skipped in the full run. Ruff lint/format, source schema export, backend/web builds and diff checks passed. API/worker were recreated and API is healthy. Two existing dependency deprecation warnings remain.

## Unsupported side questions during slot selection — 15 September 2026

- **234 tests passed, zero skips**, including PostgreSQL checks. Added mixed selection/weather, conditional weather (no booking), and unrelated non-clinical question coverage. The saved selection interpretation drives a fixed limitation reply without an unnecessary handoff. Existing clinical callback and source-write protections remain passing.
- A budget-accounted live Anthropic inference replay of Alex's saved decision-14 context from run `8281e905-39da-40da-b919-afe89bead79c` selected option 1 and classified `unsupported_question=WEATHER` for “18th should be fine, how will be the weather over there on that day?”. Strict response validation passed. This was inference only: no new appointment mutation or rewrite of the historical case. Message delivery/lifecycle were verified by automated tests, not a new live end-to-end run.
- Ruff lint/format, backend/web image builds and diff checks passed; API/worker were recreated, API is healthy and the app returns HTTP 200. Schema export and patient simulator guide were updated. No schema migration, weather integration or extra per-reply model call was added. Two existing dependency deprecation warnings remain.

## Preparation notes after confirmation — 15 September 2026

- Slot offers omit general clinic notes; the acknowledgement retains exact approved instructions after source-confirmed booking, rescheduling or attendance confirmation. The conversation label is now “Available slots”. Prerequisite checks and saved preparation evidence remain in place.
- **231 tests passed, zero skips**, including PostgreSQL checks. Existing recall/rescheduling lifecycle tests now verify that the note is absent from the offer and present in the final acknowledgement. Ruff lint/format and backend/web builds passed.
- Local API, worker and web were recreated; the API is healthy and the web URL returns HTTP 200. No new paid Claude run or browser-layout inspection was needed for this message-rendering change. Existing historical messages are preserved; start a fresh simulator test to see new wording. Two existing dependency deprecation warnings remain.

## Claude-interpreted option choices — 15 September 2026

- **231 automated tests passed, zero skips.** Coverage includes a scripted model selecting from free-form wording, null interpretation producing a clarification without a write/repeated offer, and gateway rejection of wrong offer IDs, wrong reply IDs and invalid offered option numbers. The live selection path no longer invokes the phrase-matching helper; that helper belongs only to the offline MockModel fixture.
- Live Claude run `ff2104ee-cbd5-4fc7-a4bd-ab776d92a11b` processed “option 1 is fine” via model-origin `INTERPRET_SELECTION`, proposed option 1 against the actual saved offer/reply, then recorded the source update and acknowledgement. It completed at step 22 with one offer and no handoff. The synthetic appointment moved from 16 to 17 September, 10 am SGT. Previous reviews are preserved; temporary test access was retired.
- The patient prompt no longer suggests a fixed reply. Selection context includes the displayed Singapore-time labels. Provider request-size tests cover ten offered options and long notes; model output remains schema-validated and policy-gated. Model interpretation is not treated as proof of real identity or real-channel consent.
- Backend/web builds, TypeScript/Vite and Ruff checks passed. Validation used authenticated APIs and the running worker; no new browser-layout verification was performed. Two existing third-party deprecation warnings remain.

## Natural option selection and shorter patient messages — 15 September 2026

- **225 automated tests passed, zero skips.** Added coverage for the exact “option 1 ok for me” reply in both recall booking and rescheduling, plus clear variants and rejection of negations, conditions, questions, multiple choices and out-of-range option numbers. Existing offer binding, source availability and callback tests remain passing. Ruff lint/format, backend Docker build and diff checks passed; frontend code was unchanged in this increment.
- Live Claude run `309d8b56-758a-4041-b5b2-3711d5b8b7c0` displayed the shorter slot prompt without the generic test-information disclaimer or “reply exactly” wording. The exact reply “option 1 ok for me” moved the synthetic appointment from 17 September to 16 September, 10 am SGT, and completed at step 22 with an acknowledgement, one options message and no handoff.
- Validation used the authenticated API and running Claude worker/source. Temporary test access was retired. Earlier repeated-offer reviews and their old wording remain intact; use the latest review or start a fresh simulator test. No new browser-layout verification was performed.

## Available slots and existing-appointment rescheduling — 15 September 2026

- **211 automated tests passed, zero skips**, including fourteen PostgreSQL checks. Ruff lint/format, TypeScript/Vite, backend/web builds and diff checks passed. Two existing third-party deprecation warnings remain.
- Live Claude run `8bdb0efa-3deb-4cce-b757-3f0784311496` processed the exact reply “I dont think I can make it, what are all the available slots?”. It displayed 17 September, 10 am SGT at step 12 while preserving the existing 16 September appointment. “Book option 1” then moved the synthetic appointment through the clinic API, displayed both dates and approved notes, and completed at step 23 without handoff or pause.
- Regression coverage includes listing without mutation, source-owned rescheduling, idempotent replay, rejection of unauthorised source calls, stale-slot alternatives plus staff fallback, and two concurrent patients competing for the same slot. PostgreSQL verifies one succeeds while the other fails without changing its original appointment.
- This uses the existing source tables and confirmation receipts; no migration or reservation/hold subsystem was added. Source-owned old slots are released only when an exact prior receipt/revision proves ownership; imported appointments do not invent a releasable slot.
- Local services were rebuilt/recreated. Validation used authenticated APIs, the actual worker and Claude; temporary test access was retired. No new browser-layout or organiser-endpoint verification was performed. Earlier reviews and failed attempts remain in history.

## Attendance retained with an owned callback — 15 September 2026

- **208 automated tests passed, zero skips**, including thirteen PostgreSQL checks. Updated mixed-question coverage verifies AMBER callback creation across three specialties, approved-note boundaries, acceptance without completion, rejection of resolution before acceptance/by a different owner/without an outcome, staff resolution and journey status. Acceptance/resolution add no model steps or duplicate patient messages.
- Ruff lint/format checks, TypeScript/Vite, backend/web builds and diff checks passed. Local services were recreated successfully. Two existing third-party deprecation warnings remain. No new browser-layout verification was performed.
- Live Claude run `f0e40724-a0dd-46ac-b804-bea8c4779107` used the exact mixed confirmation/blood-test reply and reached step 12, then paused at the configured **DAILY_MODEL_BUDGET_EXHAUSTED** limit before acknowledgement. Consequently the new callback lifecycle is verified by automated integration tests, not a completed live-Claude run. The limit was not changed and the failed live attempt was not converted to simulation. Temporary test access was retired; history remains intact.
- New behavior supersedes the earlier mixed-question auto-completion below. Routine confirmation remains automatic; supported blood-test questions create a callback task. Named acceptance keeps that task open until the owner records patient contact and resolution. No real phone call is placed.

## Attendance confirmation plus blood-test question — 15 September 2026

- **208 automated tests passed, zero skips**, including thirteen PostgreSQL checks. Ruff lint/format, TypeScript/Vite and backend/web Docker builds passed. Two existing third-party deprecation warnings remain.
- Live Claude review `52f069d6-62fb-4a07-9d0c-b8db57e309d8` completed in **13 steps with no handoff or pause** using the exact reply “I confirm my attendance, do i have any blood test on the day?”. It recorded the existing 16 September, 10 am SGT attendance confirmation, read approved notes/prerequisites, displayed an acknowledgement and verified completion.
- The confirmation write is a persisted `EXPLICIT_SIMULATED_CONFIRMATION` rule with zero model attempts after Engagement obtains source evidence. The normal gateway and source checks still apply. This avoids model confusion between disabled real-world messaging and enabled simulator permission. Failed source writes retain bounded retry/escalation behavior.
- Regression coverage includes the exact mixed reply in all three specialties, approved versus unapproved blood-test notes, and conditional/contradictory replies that must never authorize a write. The acknowledgement does not claim a blood-test requirement absent from approved notes; attendance completion is separate from any question needing clinic clarification.
- Earlier failed reviews remain in history. Verification used authenticated APIs and the running worker/source; temporary test access was retired. No new browser-layout or organiser-endpoint verification was performed.

## Recall booking simulator — 15 September 2026

- **201 automated tests passed, zero skips**, including thirteen PostgreSQL checks. Coverage includes two competing patients claiming one slot, idempotent receipt replay, wrong-key rejection, stale slots/notes, selection without an offer, duplicate waiting, bounded provider requests and evidence-preserving recovery. Ruff lint and formatting passed; two existing third-party deprecation warnings remain.

- Implemented a source-owned synthetic recall booking endpoint, explicit saved-offer selection, exact approved-note display, updated preparation checks and receipt-backed completion. The source migration `sim0003` preserves earlier confirmations and stores booking provenance. Existing appointment rescheduling remains unsupported.
- Live direct-Claude Mr Lim review `f0d47931-6e41-49e5-9726-ca11f057d180` displayed 16 and 17 September slots after “Can I come this Wednesday? Do I have any blood test on same day?”. It displayed the existing approved note and explicitly did not infer blood-test requirements absent from that note.
- “Book option 1” booked **16 September 2026, 10 am SGT** in the mock clinic. The receipt, updated preparation evidence and acknowledgement were saved. Final state is **completed**, no handoff, at **23 recorded steps**. A preflight request-size pause was recovered through the authenticated retry API while preserving the receipt and messages; the earlier failed step remains visible. No source data or history was erased.
- Live testing also found an inappropriate repeat WAIT after a patient reply. Model choices now exclude that wait, and the gateway independently denies it. The option-display tool persists its own waiting checkpoint.
- Role/phase-specific prompts and a three-slot model preview keep the ten-slot/long-note regression within the existing 8,000-byte request cap for both provider protocols. Full tool results remain in history and all returned slots remain in the patient offer. The organiser protocol is tested with simulated HTTP responses, not a live organiser endpoint.
- Verification uses authenticated HTTP APIs, the running worker, live Claude and the source API. Temporary test accounts/sessions were retired. TypeScript/Vite and Docker builds passed. No new browser-layout verification or remote CI run is claimed.

## Repeated source reads and role-budget recovery — 14 September 2026

- **193 automated tests passed, zero skips**, including twelve PostgreSQL checks. Ruff lint/format and the backend Docker build passed. Two existing third-party deprecation warnings remain. No frontend code changed.
- A regression model deliberately repeats an already-successful context read: the response schema no longer offers that read and the gateway independently rejects it with `READ_EVIDENCE_ALREADY_AVAILABLE`, without executing another source call. Successful reads remain scoped to the current event; specialist evidence remains scoped to its delegation.
- Recovery tests preserve the original reply, receipt, specialist reports and earlier step records. An explicit retry of a Coordinator role-budget pause with completion evidence ready finishes in two more steps; the receipt is not duplicated and the overall 24-step limit is unchanged.
- Live Claude recovery passed for Alex review `5c574c50-7340-48d9-8319-eb98d696de9f`: previously paused at 15 steps, then acknowledgement at step 16 and successful completion at step 17. The original confirmation evidence was reused. No data reset or limit increase was performed.
- A fresh live Claude review `3cedc0a5-8fdb-42cd-8bb4-db286215ee95` then passed with the reply “I confirm my attendance”: **14 total steps / 12 model attempts**, no errors, no handoff, one saved reminder and acknowledgement. The Coordinator performed one initial rule read and one read for the new reply, with no repeated reads inside either event. Verification used authenticated HTTP APIs and the running worker/source services. Temporary test access was retired; both reviews remain visible in history. No new browser-layout or organiser-endpoint verification was performed for this backend change.

## Patient confirmation simulator — 14 September 2026

- **191 automated tests passed, zero skips**, including twelve PostgreSQL checks, using the Compose test image. Two existing third-party deprecation warnings remain. Ruff lint/format passed for 74 Python files; TypeScript/Vite and Docker builds passed.
- **Live direct Claude + browser check passed:** Alex review `f852a893-6fe0-4c68-8a07-9bcd6146e55c`, case `2fb36ad6-7298-4670-ad12-1fb7466a9b11`, completed in **13 steps / 11 model attempts**, with no errors and no handoff. Reply: “Yes, I confirm the attendance, What should I bring?” The gateway returned GREEN with `SOURCE_RECEIPT_AND_SIMULATED_DELIVERY_VERIFIED`. Reported usage: 24,017 input and 996 output tokens for this successful review.
- The browser showed the outgoing reminder, entered reply, acknowledgement with the exact approved spectacles note, and completed state. The separate clinic simulator displayed the confirmation while the appointment stayed scheduled. Case Journey showed both outgoing messages and the evidence-backed completion. The final journey captions distinguish simulated completion from staff-owned handoff completion.
- Added persisted outgoing reminders and acknowledgements, a separate source-owned confirmation receipt, and gateway-checked simulated completion. Both specialists contribute evidence. The source stays scheduled; no real attendance, booking or patient delivery is claimed.
- Tests cover the three specialties; plain and preparation-question confirmations; alternate confirmation wording; negative/conditional/ambiguous replies; prerequisite and changed-source blocks; wrong identity/key/version; forged completion; retries without duplicates; late receipts after pause; fresh-review history; and concurrent PostgreSQL confirmation requests.
- Live testing exposed an oversized native Claude request and an unsupported schema array bound. Prompt duplication was reduced; both provider request envelopes are checked against the existing 8,000-byte default. Native schema conversion maps `minItems > 1` to 1 because [Claude only supports 0 or 1](https://platform.claude.com/docs/en/build-with-claude/structured-outputs); local decision validation still requires exactly two evidence IDs and the gateway verifies their provenance. No budget or step limit was increased.
- Application migration `0004` and source migration `sim0002` applied successfully. Builds and Ruff lint/format passed. Earlier reviews retain their recorded outcomes; a fresh simulator review uses the new capability.
- These checks cover synthetic local data. They do not verify real channels, clinical triage, production patient authentication, the organiser's live endpoint or remote GitHub Actions. Changes remain local and uncommitted.

## Unsupported clinical escalation correction — 14 September 2026

- **167 automated tests passed, zero skips**, including eleven PostgreSQL checks, using the Compose test image. New cases cover routine confirmation and confirmation/preparation replies across dental, myopia and antenatal; model response schemas exclude the clinical reason for all three agents; a model that ignores the constraint is denied by the gateway. The staff clinical-flag rule still produces RED without a model call and retains RED after named acceptance.
- Journey coverage verifies that a correction is a separate audit event, preserves the original proposal/verdict and original handoff classification, shows the current classification, and belongs only to its selected review.
- Ruff lint/format (68 Python files), TypeScript/Vite and Docker builds passed. The local app was rebuilt and restarted without resetting cases or changing source records.
- Alex's existing synthetic confirmation was corrected from RED/`CLINICAL_REVIEW_REQUIRED` to AMBER/`CAPABILITY_UNAVAILABLE` in a scoped transaction after checking the saved reply, instructions, prerequisites, disabled write/contact capabilities, case version, current run and absence of staff clinical flags. The handoff remains unaccepted. The original model decision and policy remain unchanged; the journey includes an explicit maintenance correction.
- One paid, budgeted **direct Anthropic replay** of the saved final Coordinator context returned `ESCALATE / CAPABILITY_UNAVAILABLE` (2,201 reported input tokens, 65 output tokens). This checked a single model response; no action was executed and it was not inserted into the original case history. It does not establish general model accuracy or clinical triage quality.
- Two existing third-party test-client deprecation warnings remain. No real patient contact, attendance/booking write, automatic clinical triage, organiser endpoint or remote GitHub Actions verification was added. Changes remain local and uncommitted.

## Dynamic clinic simulator — 13 September 2026

- **156 automated tests passed, zero skips**, including eleven PostgreSQL checks, using the Compose test image. New tests cover isolated source migrations/seed preservation, edited evidence through the existing typed adapter, note approval filtering, timezone conversion, available-slot filtering, duplicate/stale requests, invalid inputs, authenticated editing, detection/deduplication and reset with custom episodes. Competing PostgreSQL editors produce one success and one conflict; migration metadata matches the simulator models.
- Ruff lint/format passed (68 Python files). TypeScript/Vite and Docker builds passed. Bootstrap created the isolated source database and `sim0001` schema; the application schema remains `0003` and existing history was preserved.
- Authenticated browser testing saved a slot and a cancelled patient episode/note through the combined page, reloaded them after restarting the mock service, and verified the approved note and availability through the real HTTP source adapter. The cancelled test episode did not create an application case or trigger paid inference. Temporary test records and the disposable local test login were removed after verification.
- Live database checks confirmed the application user cannot connect to the source database, and the simulator role cannot read application case tables. PostgreSQL, API and source service health checks passed; worker/web are running; bootstrap exited successfully.
- Model tests use test doubles. No real patient messages or appointment writes were tested or enabled. Two existing third-party test-client deprecation warnings remain. These changes are local and uncommitted; remote GitHub Actions is not verified.

## Automatic review startup and initial source read — 13 September 2026

- **146 automated tests passed, zero skips**, including ten PostgreSQL checks, using `./scripts/dev.ps1 test`. New coverage verifies automatic creation without browser requests, atomic foundation completion/run registration, concurrent starters, ready-case catch-up, no restarts of existing reviews, service identity isolation/revocation, blocked service login/sessions, missing configuration and rule-tool lease recovery.
- Existing workflow, provider, gateway, source-failure, pause/retry and shared-budget tests pass. Budget tests now race at an actual model step, after the rule-selected initial read. Model/provider tests use test doubles; they do not consume paid inference.
- Ruff lint/format passed (59 Python files); TypeScript/Vite production build passed. The local Compose app rebuilt and started successfully, with automatic startup enabled and the clinic service identity provisioned. No schema migration or data reset was needed.
- Two previously unreviewed local cases automatically reached waiting after deployment; the existing completed review was preserved. Local catch-up uses the configured provider and its existing budget. The served frontend contains the automatic-start/rule-read explanations and neither start button. Browser navigation reached the sign-in page; the protected dashboard was not visually inspected in this verification session.
- The two existing third-party test-client deprecation warnings remain. Remote GitHub Actions has not been verified for these uncommitted changes.

## Deterministic initial demo wait — 12 September 2026

- **137 automated tests passed, zero skips**, including the nine PostgreSQL checks, using `./scripts/dev.ps1 test`. Eight added cases cover all three provider modes with test doubles, exhausted model budgets, reply resumption, failed/stale source evidence, capability checks and authority revocation.
- Initial wait is stored as an application-rule step with zero attempts. The standard test flow uses two model-adapter decisions (Coordinator read and delegation), then the worker records the wait. Resumed mixed replies still use both specialists and reach a staff handoff.
- Ruff lint/format and TypeScript/Vite build passed. Docker rebuilt and restarted the app successfully. The served frontend contains the new rule explanation and zero-call label. No paid inference was needed for validation; provider-mode tests use a recording test double, not live Claude.
- Existing historical reviews were preserved. This change does not enable patient outreach, alter the manual start control or add a full event journal. The two existing third-party deprecation warnings remain; remote GitHub Actions has not been verified.

## Optional demo reset — 12 September 2026

- **129 automated tests passed, zero skips**, including nine real PostgreSQL checks. Fourteen added checks cover reset defaults, confirmation, flag/session/clinic/Origin/CSRF enforcement, preserved credentials/budget/other-clinic data, source failure, rollback, stale requests, unexpected records, active review rejection, late worker results and competing PostgreSQL resets.
- Ruff lint/format and the TypeScript/Vite Docker build passed. The application rebuilt successfully; the private local flag is enabled while the committed default remains off. No migration was introduced.
- Browser verification covered the visible **Reset demo data** button, the disabled action before confirmation, enabling it by typing `RESET`, and Cancel returning to the unchanged dashboard. Actual deletion/recreation was exercised by automated API/database tests in isolated test data; the current laptop's demo was not reset again during the UI check.
- No Claude calls were required. The two existing third-party test-client deprecation warnings remain. Remote GitHub Actions has not been verified for these uncommitted changes.

See [DEMO_RESET.md](DEMO_RESET.md) for the enable/disable flag and demonstration steps.

## Case Journey page — 12 September 2026

- **115 automated tests passed, zero skips**, including eight real PostgreSQL checks, using `./scripts/dev.ps1 test` after the final backend changes.
- Four new journey tests cover new/legacy detection evidence, chronological staff/decision/handoff records, model-context/proposal/policy/result separation, previous reviews, blocked tools, clinic isolation and unauthenticated access. Repeated reads do not create steps or consume model calls.
- Ruff lint and formatting passed (53 Python files). TypeScript/Vite production build passed in Docker. The Compose app rebuilt and started successfully with existing local cases preserved; no new migration was needed.
- Browser checks passed for dashboard navigation, loading an existing completed dental review, separate handoff creation and acceptance, individual and bulk message expansion, filtering, earlier simulation labels while the app is in direct-Claude mode, refresh and direct case-route reload. Desktop screenshots were inspected; expanded input/output panels had no page-level horizontal overflow at the tested default viewport. No separate mobile browser check was performed.
- This page reads persisted application evidence. No paid Claude calls were made for these checks. Historical missing source payloads, exact prompts and individual HTTP retry responses remain explicitly unavailable; activities within a decision show logical order rather than individual network timestamps.
- The two existing third-party test-client deprecation warnings remain. These results describe the local working tree; they do not establish remote GitHub Actions success.

See [CASE_JOURNEY.md](CASE_JOURNEY.md) to use the page.

## Live direct Claude verification — 11 September 2026

**111 automated tests passed with zero skips**, including eight PostgreSQL cases. Ruff lint/format, TypeScript/Vite and Docker web build passed. The fresh live dental review completed 13 model decisions with no retries or rejected steps, collected both specialists' evidence and required named staff acceptance. See [LIVE_CLAUDE_VALIDATION.md](LIVE_CLAUDE_VALIDATION.md) for the run ID, usage, reproduction steps, earlier failures and limits.

The entries below are historical snapshots taken earlier in development. Statements about no live calls or older test counts apply to those snapshots only.


## Direct Claude addition — 11 September 2026

- Docker suite: **102 tests passed, zero skipped**, including eight real PostgreSQL checks. This includes forward migration from populated `0002`, unchanged existing run mode/usage counter, the new `anthropic` mode, atomic daily budgets and pacing for both live providers.
- Direct Messages API wire/response tests cover separate credentials, workspace header, typed proposals, limits, timeouts, redacted HTTP failures, refusal/truncation and unexpected content. These tests use HTTP test doubles, not paid inference.
- The one-call connection check is tested for request binding, budget reservation and no fallback/retry on denied access.
- Ruff lint and formatting passed (50 Python files). TypeScript/Vite and Docker frontend builds passed. The local Compose application rebuilt successfully and the database is at `0003`; three synthetic cases and four completed reviews are present.
- The installed connection-check command returned `SIMULATION_SELECTED` in the current mock configuration, as expected. No paid provider connection was attempted. Live Claude behavior and organiser compatibility still require configured private credentials and the journey/evaluation checks in [CLAUDE_SETUP.md](CLAUDE_SETUP.md).
- Earlier recorded browser demonstrations below concern the existing M2a simulation; they do not establish direct-Claude model accuracy. The two existing third-party deprecation warnings remain.

Latest recorded local verification: **11 September 2026**, M2a v0.2.0. These results describe the local working tree, not a pushed commit, remote CI run or production deployment.

| Check | Recorded result |
| --- | --- |
| Backend suite in Docker | **74 passed, 0 skipped**, with PostgreSQL 17 available; model HTTP responses simulated, no organiser calls |
| Real PostgreSQL checks | Five passed: foundation job claiming, agent-run claiming, populated M1 → M2a migration/schema alignment, concurrent daily-call reservations and shared pacing |
| Workflow tests | Dental, myopia and antenatal runs reach a durable wait, delegate specialists and require named staff acceptance before automation completion |
| Reliability and policy | Stale leases/results, crash recovery of saved tool proposals, permission revocation before/after reads, idempotency/body binding, pause/retry, source outages, budgets and invalid-model responses covered |
| Gateway adapter | JSON wire format, request/response limits, malformed envelopes, status errors, no redirects, safe errors and token metadata verified with HTTP test doubles |
| Python quality | Ruff lint and formatting checks passed |
| Frontend | TypeScript check and Vite production build passed; final Docker web build passed |
| Schema export | Exported JSON Schema matches the runtime decision contract |
| Local upgrade | Migration `0002` applied; original three cases and six foundation audit events preserved; existing credentials preserved |
| Browser — dental | Both specialists returned source evidence; alternative-date finding visible; handoff remained unowned until staff accepted; automation then completed |
| Browser — myopia | Synthetic spectacles note and prerequisite read visible; unverified attendance intent returned; named handoff accepted and automation completed |
| Browser — antenatal | Explicit staff concern generated rule-origin RED escalation; named acceptance completed automation while retaining RED and an open staff task |
| Browser — recovery/layout | Waiting checkpoint survived worker restart and page reload; session persisted; narrow-screen horizontal overflow corrected and checked |
| Docker startup | Database, API and mock clinic healthy; worker/web running; bootstrap exited 0; localhost-only web binding |
| Secrets | Existing private configuration preserved, default mock mode retained, no team key added; generated files remain ignored |

Open **http://localhost:8080** and follow [AGENT_RUNTIME.md](AGENT_RUNTIME.md). The tested local cases now contain completed demonstration runs; select **Start another demo run** to repeat a flow. Earlier runs remain in the database; the screen displays the latest run.

Reproduce the full backend suite with `./scripts/dev.ps1 test`. Local Python-only tests explicitly skip the five PostgreSQL checks when TEST_DATABASE_URL is absent; this is not equivalent to the complete Docker result. The default Windows pytest temporary folder on this machine had an access restriction; local debugging used a fresh project-cache temporary directory. The team's Docker test route avoids that host-folder issue.

**Not verified:** live organiser Claude access, real patient identity/contact, clinical detection or advice, language quality, booking writes, external providers, GitHub Actions or cloud deployment. The private team API URL/key are still required for live inference verification. This release makes no production-readiness or clinical-safety claim.

These 74 engineering checks are separate from the planned **60 hackathon evaluation scenarios**. Simulation proves application control flow and recovery, not model accuracy, inclusion outcomes or staff time savings. Real-model evaluation remains pending.

Two third-party test-client deprecation warnings (Starlette/httpx and an AnyIO alias) were present without failing tests. No dependency upgrades were introduced to suppress them.
# Adaptive follow-up validation — 16 September 2026

- Full container suite: 253 tests passed with PostgreSQL enabled; no skips. Two existing dependency deprecation warnings remain. A subsequent 43-test adaptation/booking run passed against the updated source, including the organiser request-size check.
- Ruff lint and formatting pass; web TypeScript/Vite build passes.
- Live Claude against isolated synthetic databases: accompaniment constraint after 3 pm filtered out a morning slot, offered the afternoon slot, then accepted a natural reply and completed with one source receipt (run `4e012a09-25e6-4be6-8a2b-948860989988`, 23 steps). Incomplete-scan report produced preparation callback with no confirmation write (run `f03c9996-a6f8-4e41-901c-41eacd7125c4`, 8 steps). These are bounded examples, not a clinical accuracy benchmark.
- Local bootstrap applied migration `0005`; API readiness returns 200. Authenticated reads verified the plan/preferences fields for all three existing cases and the served web bundle contains the new controls. Containers updated without resetting case history. No browser visual-layout certification or organiser live endpoint verification is claimed.
- Windows/Ubuntu scripts and the shared Compose file are unchanged by this increment. Remote CI will run only after a push.
