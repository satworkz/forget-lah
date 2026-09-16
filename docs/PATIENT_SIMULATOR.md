# Test attendance confirmation and acknowledgement

The patient simulator displays a reminder, accepts your fictional reply, records confirmation in the mock clinic system and displays an acknowledgement. Nothing is sent to a real phone.

## Ask for slots for an existing appointment

After slots are offered, try a clear selection with an independent weather question, such as “18th should be fine, how will be the weather over there on that day?” when the 18th uniquely matches an offered slot. The acknowledgement should confirm the source-recorded change and add “Sorry, I can’t check the weather forecast here.” A conditional reply such as “Only if it is sunny” must ask for clarification without booking. Unsupported non-clinical side questions receive a generic limitation sentence; no forecast is invented. Existing messages are preserved, so use a fresh simulator test.

**You can answer in your own words.** Live Claude interprets the selection against the displayed options; no exact command is required. For example, “option 1 is fine” or “the first appointment suits me” should select a clear matching option. Uncertainty produces a clarification question. See `INTERPRET_SELECTION` in the journey for Claude's proposed option and the gateway's checks. Offline mock-mode tests use scripted interpretation, not live AI.

1. Keep a future **scheduled** appointment in the clinic simulator, set prerequisite to **NOT_APPLICABLE**, and add an available slot for that specialty at a different time.
2. Open the patient's review and choose **Start fresh simulator test**.
3. After the reminder, reply **I dont think I can make it, what are all the available slots?** The **Ask for available slots** helper fills this text for you.
4. Read the available options in the conversation. The existing appointment is unchanged at this point.
5. Reply **option 1 ok for me**, **Option 1 works for me**, or **Book option 1** (using the desired option number). This explicit choice authorizes the simulator to move the appointment. Expect an acknowledgement showing the previous and new times, followed by completion.

The source API checks availability again when the patient selects. If the slot or episode changed, no booking change is made by that request: the app shows current alternatives and creates a staff task to finish the change. If no slots are available, it says so and asks staff for help. Temporary holds, waitlists and automatic retry/reservation workflows are deferred. Only appointments the source considers eligible can be rescheduled; clinical prerequisites still require staff review.

## Test Mr Lim's overdue recall

1. In **Clinic simulator**, keep Mr Lim as a **recall**, status **due**, with no future booking. Set prerequisite to **NOT_APPLICABLE** and save any fictional, approved doctor note you want to test.
2. Add a future **dental** slot for Wednesday (and optionally other dates).
3. Open Mr Lim's review and choose **Start fresh simulator test**. Earlier reviews remain in the journey history.
4. After the reminder, reply: **Can I come this Wednesday? Do I have any blood test on same day?**
5. Expect available slots with full dates/times in Singapore time. General clinic notes are withheld until confirmation; prerequisite checks still run before booking. All returned options are displayed so the patient can choose.
6. Reply **Book option 1**, or the number of your chosen option in the latest offer. The helper button fills option 1; review it before submitting. A date question or generic attendance confirmation does not authorize a new booking.
7. Expect a booking acknowledgement containing the exact approved clinic notes and **Follow-up complete**, without staff handoff. Reload Clinic simulator: the recall becomes a scheduled appointment and the selected slot is unavailable. This is a synthetic booking only.

The source rechecks the episode, slot version, date, specialty and prerequisite before booking. A changed/taken slot or changed notes blocks completion and currently requires staff review; automatic alternative-slot recovery and existing appointment rescheduling are not included. If approved notes do not answer a test question, the message explicitly asks the patient to clarify with the clinic. Completion means booking and acknowledgement, not resolution of every clinical question.

Technically, Coordinator's `send_simulated_options` validates both specialist reports and current source evidence, saves an options message and waits. A supported explicit selection is bound to this run's latest offer. Engagement's `record_simulated_confirmation` dispatches to the mock source's `/book-recall` endpoint for a recall selection, `/reschedule` for an existing appointment's selected alternative, or `/confirm-attendance` for attendance confirmation. Source migration **sim0003** preserves slot and prior episode versions on receipts. The source changes the appointment and claims its slot in one transaction; forget-lah never writes source tables directly.

## Start and test Alex

For an existing appointment reminder, you can also reply naturally. “Yes fine, How about the parking lot availability during that time?” should confirm attendance and acknowledge that parking availability cannot be checked. “Yes fine? how about the parking lots during that day?” should ask whether you are confirming attendance for the specific date/time, with no source confirmation yet. Reply “yes” to that clarification to continue. This confirms attendance for an existing booking; it does not book another slot. Inspect `INTERPRET_ATTENDANCE` and the saved source receipt in the journey.

1. Start Docker Desktop, then run `./scripts/dev.ps1 up` from the project folder. Setup generates the private follow-up key; bootstrap upgrades both databases without clearing history.
2. Open **http://localhost:8080**, sign in and press **Ctrl+F5** after an upgrade.
3. Open **Clinic simulator** and select **Alex (demo)**. Use an **appointment**, status **scheduled**, with a future date and prerequisite **NOT_APPLICABLE**. Enter a fictional note such as “Bring your existing spectacles” and mark it approved. Save changes.
4. Return to Alex's review and click **Start fresh simulator test**. This creates a new review using current records and preserves earlier reviews. New cases still start automatically.
5. Wait for **Patient conversation simulator** to display the clinic reminder.
6. Enter **I confirm my attendance** and select **Submit demo reply**. The **Use attendance confirmation** button fills in this text; it does not submit it.
7. Expect **Follow-up complete**, a displayed acknowledgement, and no staff handoff. In another fresh test, try **I confirm my attendance, what should I bring?**
   You can also test **I confirm my attendance, do i have any blood test on the day?** The attendance confirmation is recorded separately. The acknowledgement shows approved notes and explains that the clinic must clarify any blood-test information not covered by those notes. It does not guess test requirements.
8. Open **View full case journey** to inspect the source receipt, preparation evidence, outgoing message and final completion decision.
9. In **Clinic simulator**, reload saved data and select Alex. A confirmation label should appear. The appointment remains **scheduled**: this records an intention to attend, not actual attendance.

If a review is queued/running, let it finish or pause it before starting another test. A fresh test uses the configured model and existing call/step limits. Reset is not needed.

## Other useful tests

| Test | Expected result |
| --- | --- |
| Scheduled dental or antenatal appointment; same confirmation | Same receipt, acknowledgement and completed flow |
| Due recall, available slots, date request then explicit option selection | Offer, synthetic booking, acknowledgement and completion |
| Recall with only attendance confirmation and no selected slot | Staff review; no invented booking |
| Missed/cancelled visit or changing an existing appointment | Staff handoff: rescheduling is not implemented |
| Negative, conflicting or unclear reply | No confirmation write; staff review |
| Prerequisite `STAFF_REVIEW_REQUIRED` | Staff review; no automatic confirmation/acknowledgement |
| Explicit staff clinical-concern button | Existing RED rule path |
| Approved note | Exact text appears in the acknowledgement |
| Note not approved | It is not copied into the acknowledgement |
| Source changes between read and write | Version conflict; no false completion |

Confirmation permission uses a conservative set of explicit phrases, including the two examples above and “Yes, I confirm the attendance, what should I bring?” Capitalization and repeated spaces do not matter. Language interpretation alone does not authorize a write. Use the supplied text for a reliable happy path; unsupported phrasing goes to staff. Patient identity, real-channel consent and clinical text/voice triage remain unimplemented.

## Technical flow

1. The worker reads the source and displays a persisted simulated reminder before waiting. No model call is needed to choose this fixed wait.
2. Coordinator delegates to Engagement and Preparation. Both are required for confirmation completion.
3. After Engagement reads current source evidence, the worker selects `record_simulated_confirmation` as a rule when the explicit simulator confirmation is already authorized. It uses zero model attempts and still passes through the gateway. Python supplies the patient, episode, reply operation ID and expected source revision; Claude cannot choose these values. Failed attempts retain the bounded retry/escalation path.
4. The mock clinic API checks a separate follow-up key, patient/episode binding, future scheduled appointment, revision and prerequisite. It stores an idempotent receipt in `sim_confirmation`. The human editor key does not authorize this endpoint.
5. After both specialists return, Coordinator proposes `send_simulated_acknowledgement`. The worker rechecks the source and copies approved notes into a persisted `simulated_message`. Delivery means **displayed in the simulator**.
6. Coordinator proposes `COMPLETE_SIMULATED_CONFIRMATION`. The gateway verifies the source receipt, displayed acknowledgement and both specialist reports. The outcome is `SIMULATED_ATTENDANCE_CONFIRMED`.

Transient simulated-tool failures allow bounded timed retries with the same reply operation ID. Receipts and messages are not duplicated. A late source receipt after a staff pause remains visible without completing the case. The 24-step limit remains; exhausting a budget pauses the review.

Successful source reads are reused within the current event. The Coordinator can use a specialist's saved context; each specialist still gathers its own required evidence. Completed reads are removed from the model's choices and repeated requests are blocked by the gateway. A new reply or source-retry event can refresh the source; the confirmation and acknowledgement actions also check current source state before proceeding.

If an older review stopped with **role budget exhausted** after both specialists finished and confirmation evidence is ready, **Retry agent review** preserves the original reply, receipt and specialist reports. It opens a new Coordinator allowance for the remaining completion work; the 24-step review limit and daily model budget are unchanged. Other pause conditions still use the existing retry behavior. Earlier failed steps remain visible in history.

The same evidence-preserving recovery applies to **MODEL_REQUEST_TOO_LARGE** once acknowledgement or completion evidence is ready. Current prompts are bounded by role/phase; full source slot results stay in history while model planning uses a three-slot preview and count. Patient offers still display the complete returned page (up to ten slots).

## Configuration and persistence

- `PATIENT_SIMULATOR_ENABLED` defaults to true in local Compose. False disables the capability for new reviews and blocks simulated writes; previous history remains readable.
- `MOCK_CLINIC_FOLLOWUP_KEY` is generated privately by `setup`/`up`. Keep it out of Git. The worker does not receive the clinic editor key.
- Application migration **0004** adds outgoing messages; source migration **sim0002** adds confirmation receipts. Earlier migrations are unchanged.
- Demo reset clears application messages with case history. Source receipts remain in the external mock system; a new reply has a new operation ID. Editing a source revision makes old receipts historical.
- Earlier reviews keep their saved capability mode. **Start fresh simulator test** uses the latest configuration and preserves previous reviews.

Real channels can later use adapters behind the same gateway. This increment adds no booking engine, real patient messaging or medical advice.

## Attendance plus a clinic callback

For a fresh scheduled appointment, reply: `I confirm my attendance, do i have any blood test on the day?`

The simulator records attendance through the clinic API, reads approved preparation notes, and displays: “I've sent your blood-test question to the clinic team and requested a callback.” It also creates an AMBER `PATIENT_QUESTION_CALLBACK` task. Attendance remains confirmed; the question is awaiting a clinic response.

1. Click **Accept handoff as me** to take responsibility. The case stays open and does not call Claude again.
2. After contacting the patient, enter the contact outcome and click **Record contact and resolve callback**. Only the named owner can do this.
3. The case completes and the staff outcome remains in the full case journey. In testing, clearly label the contact as simulated; the application does not place a phone call.

Callback question, source evidence, confirmation receipt, acceptance and resolution are persisted. Acceptance alone never means the question was answered. Existing completed reviews retain their history; use **Start fresh simulator test** to exercise the new behavior.

Current scope: the supported explicit-confirmation/blood-test phrases create a callback conservatively, even when free-text approved notes mention a blood test. Notes are shown exactly but are not structured proof that the particular question is answered. General question understanding and automatic callback delivery remain future work.
