# Clinic simulator — team testing guide

This is a small, fictional **external clinic system** for testing forget-lah. It combines appointment schedules, available slots and patient notes. It is outside the patient-follow-up product scope; use synthetic data only.

## 1. Open it

1. Start Docker Desktop.
2. In your project terminal, run `./scripts/dev.ps1 up`.
3. Open http://localhost:8080 and sign in with your existing local staff login.
4. Click **Clinic simulator** in the sidebar, or open http://localhost:8080/#/clinic-simulator.

Startup adds missing simulator secrets to your private `.env`, creates a separate database/user, applies its migration, and inserts the three initial patients once. Existing credentials, application history and simulator edits are preserved. Do not share `.env`.

## 2. Add appointment availability

1. Under **Add available slot**, choose Dental, Myopia or Antenatal.
2. Enter a fictional doctor/resource label, start time and end time.
3. Leave **Available for testing** checked and click **Add slot**.
4. Use **Edit** beside a saved slot to change it or make it unavailable.

All dates on this page use **Singapore time (UTC+8)**. The backend stores UTC. Slot end must be later than start. A doctor cannot have two records with exactly the same start time. This small simulator does not implement capacity, calendar conflict resolution, duration matching or a booking engine.

The next `read_followup_context` tool call includes up to 10 future available slots for that specialty, ordered by time. Past, unavailable and other-specialty slots are excluded. `more_available_slots` indicates if results were capped. This is availability evidence, not a reservation. Appointment writes are still disabled in forget-lah.

## 3. Edit schedules and doctor notes

1. Choose Alex, Mr Lim or Priya in **Open a saved episode**.
2. Adjust the status/date or use **Upcoming**, **Missed**, or **Overdue recall** as a quick example.
3. Enter a short fictional note, such as “Bring your current spectacles.”
4. Check **Mark this text approved for the synthetic demonstration** if Preparation should receive it.
5. Select whether a prerequisite needs clinic staff review.
6. Click **Save episode changes**.

Unapproved notes remain in the simulator but are excluded from `get_approved_instructions`. The approval checkbox is a test fixture, not medical approval. Preparation retrieves the saved text/version through the existing adapter; it does not send it to a patient in this release.

Changes appear on the **next source-tool read**. Editing a source row does not wake a waiting review, restart a completed review or change the original case trigger. Previous observations retain the evidence used at the time.

## 4. Start a fresh scenario without deleting history

1. Set up any slots first.
2. Click **New episode**, or select a saved one and choose **Copy into a new test episode**.
3. Enter a fictional alias, specialty, schedule and notes.
4. Click **Save new test episode**.
5. Return to forget-lah, wait about 10 seconds and click **Refresh cases**.
6. Open that patient's **View full case journey**.

Each new episode has a new `SIM-...` reference and separate synthetic patient ID, even when you reuse an alias. This starts a fresh journey while preserving old cases. The local limits are 200 episodes and 500 slots.

| Scenario | Source settings | Expected detection |
|---|---|---|
| Upcoming visit | Appointment, Scheduled, within the next seven days | New Upcoming case |
| Missed appointment | Appointment, Missed (no-show), past date | New Missed case |
| Overdue check-up | Recall, Due, past date, future booking unchecked | New Overdue recall case |
| Recall already arranged | Recall, Due, future booking checked | No new overdue recall case |
| Far-future visit | Scheduled, more than seven days ahead | No case until it enters the window |
| Cancelled/completed | Cancelled or Completed | No new case |
| Preparation evidence | Approved note + prerequisite status | Available when Preparation reads its tools |

New eligible episodes queue reviews automatically. With a live Claude provider configured, this can consume model credits. Saving slots or viewing the simulator makes no model call.

## 5. Reload, reset and troubleshoot

- **Reload saved data** refreshes the lists and discards unsaved form edits. Conflicting saves are rejected instead of overwriting another teammate's edits.
- **Reset demo data** on the forget-lah dashboard clears application history and recreates currently eligible cases from the saved simulator records. It preserves simulator schedules, slots and notes, logins and usage accounting. Pause queued/processing reviews first. The existing `DEMO_RESET_ENABLED` flag still controls the button.
- Container restarts preserve edits. Dates are seeded once and no longer move forward each day. Use the quick examples or a new episode when old dates leave the reminder window.
- If a case is absent, check status/date/future-booking and whether that episode already has a case. A new episode gives you a new run.
- If a note/slot is absent from a trace, inspect the next actual tool result. Old results are snapshots. Adding slots does not make the current agent book or send a message.
- If the simulator is unavailable, run `./scripts/dev.ps1 status` and inspect `docker compose logs --tail 50 bootstrap mock-clinic`. Do not share credentials or complete patient payloads in logs.

## 6. Technical boundary

```text
Simulator page → authenticated API proxy → mock clinic API → forget_lah_mock database
                                               ↑
                        detector / agent source adapters
                                      ↓
                     forget_lah database (cases and evidence)
```

The existing PostgreSQL container hosts two separate databases. The source uses its own `forget_lah_mock` login and `sim_patient`, `sim_episode`, `sim_slot` tables. Application runtime users have no connect grant to the simulator database. The source role has no permission to read application tables. No database or mock-service port is published.

Bootstrap provisions the database using its owner connection and applies independent migration `sim0001`. The application's migration remains `0003`; no case/history migration is needed. Future source schema changes require forward migrations.

The UI shares the React build and login but has its own page. Editing requires an active demo-clinic member, same-origin requests, CSRF and an internal editor key held only by the API proxy/mock service. The worker receives a separate key for the narrow synthetic attendance-confirmation endpoint; it cannot use the human editor API. Revision checks reject stale edits; source versions change with the episode or relevant availability.

Existing read APIs remain `GET /internal/candidates` and `GET /internal/followup-context/{episode}`. Context adds optional `available_slots` and `more_available_slots`; older fixture payloads remain valid. `/internal/admin/*` is not in the agents' tool allowlist.

## 7. Still outside this change

The [patient simulator](PATIENT_SIMULATOR.md) can display a reminder, record confirmation for a future scheduled synthetic appointment and display an acknowledgement with approved notes. Reload saved data to see the confirmation label. This records intention to attend; the appointment remains scheduled. Real patient messaging, booking/rescheduling, patient identity and clinical detection remain separate work. Unsupported requests need an AMBER handoff; RED requires the explicit staff clinical flag. This simulator provides no medical advice or clinical triage.
