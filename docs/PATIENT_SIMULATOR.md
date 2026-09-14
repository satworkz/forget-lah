# Test attendance confirmation and acknowledgement

The patient simulator displays a reminder, accepts your fictional reply, records confirmation in the mock clinic system and displays an acknowledgement. Nothing is sent to a real phone.

## Start and test Alex

1. Start Docker Desktop, then run `./scripts/dev.ps1 up` from the project folder. Setup generates the private follow-up key; bootstrap upgrades both databases without clearing history.
2. Open **http://localhost:8080**, sign in and press **Ctrl+F5** after an upgrade.
3. Open **Clinic simulator** and select **Alex (demo)**. Use an **appointment**, status **scheduled**, with a future date and prerequisite **NOT_APPLICABLE**. Enter a fictional note such as “Bring your existing spectacles” and mark it approved. Save changes.
4. Return to Alex's review and click **Start fresh simulator test**. This creates a new review using current records and preserves earlier reviews. New cases still start automatically.
5. Wait for **Patient conversation simulator** to display the clinic reminder.
6. Enter **I confirm my attendance** and select **Submit demo reply**. The **Use attendance confirmation** button fills in this text; it does not submit it.
7. Expect **Follow-up complete**, a displayed acknowledgement, and no staff handoff. In another fresh test, try **I confirm my attendance, what should I bring?**
8. Open **View full case journey** to inspect the source receipt, preparation evidence, outgoing message and final completion decision.
9. In **Clinic simulator**, reload saved data and select Alex. A confirmation label should appear. The appointment remains **scheduled**: this records an intention to attend, not actual attendance.

If a review is queued/running, let it finish or pause it before starting another test. A fresh test uses the configured model and existing call/step limits. Reset is not needed.

## Other useful tests

| Test | Expected result |
| --- | --- |
| Scheduled dental or antenatal appointment; same confirmation | Same receipt, acknowledgement and completed flow |
| Recall without an appointment, missed appointment or cancelled visit | Staff handoff; no invented booking or confirmation |
| “Can I come next Friday?” | Staff handoff: rescheduling is not implemented |
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
3. Engagement proposes `record_simulated_confirmation`. The gateway checks the synthetic clinic/run, saved reply, permitted role and source evidence. Python supplies the patient, episode, reply operation ID and expected source revision; Claude cannot choose these values.
4. The mock clinic API checks a separate follow-up key, patient/episode binding, future scheduled appointment, revision and prerequisite. It stores an idempotent receipt in `sim_confirmation`. The human editor key does not authorize this endpoint.
5. After both specialists return, Coordinator proposes `send_simulated_acknowledgement`. The worker rechecks the source and copies approved notes into a persisted `simulated_message`. Delivery means **displayed in the simulator**.
6. Coordinator proposes `COMPLETE_SIMULATED_CONFIRMATION`. The gateway verifies the source receipt, displayed acknowledgement and both specialist reports. The outcome is `SIMULATED_ATTENDANCE_CONFIRMED`.

Transient simulated-tool failures allow bounded timed retries with the same reply operation ID. Receipts and messages are not duplicated. A late source receipt after a staff pause remains visible without completing the case. The 24-step limit remains; exhausting a budget pauses the review.

## Configuration and persistence

- `PATIENT_SIMULATOR_ENABLED` defaults to true in local Compose. False disables the capability for new reviews and blocks simulated writes; previous history remains readable.
- `MOCK_CLINIC_FOLLOWUP_KEY` is generated privately by `setup`/`up`. Keep it out of Git. The worker does not receive the clinic editor key.
- Application migration **0004** adds outgoing messages; source migration **sim0002** adds confirmation receipts. Earlier migrations are unchanged.
- Demo reset clears application messages with case history. Source receipts remain in the external mock system; a new reply has a new operation ID. Editing a source revision makes old receipts historical.
- Earlier reviews keep their saved capability mode. **Start fresh simulator test** uses the latest configuration and preserves previous reviews.

Real channels can later use adapters behind the same gateway. This increment adds no booking engine, real patient messaging or medical advice.
