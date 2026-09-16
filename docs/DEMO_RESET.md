# Start a fresh demonstration

The optional **Reset demo data** button clears the local demo clinic's history and recreates currently eligible cases from the saved [clinic simulator](CLINIC_SIMULATOR.md) records. It preserves simulator schedules, slots and notes. It is intended for rehearsals and presentations.

## Enable the button once

1. Open your project's private `.env` file in VS Code.
2. Add or change this line:

   ```dotenv
   DEMO_RESET_ENABLED=true
   ```

3. Save the file, then run `./scripts/dev.ps1 up` in the project terminal.
4. Reload **http://localhost:8080** and sign in. **Reset demo data** appears below the dashboard heading.

The default is `false`. To hide the button and disable its API, set it back to `false` and run `up` again. Each teammate controls the flag in their own `.env`; do not commit that file.

## Reset before a demo

1. If a review is queued or processing, open its agent panel and select **Pause agent**. You can reset completed, paused, waiting or escalated reviews.
2. Select **Reset demo data**.
3. Read the confirmation and type **RESET**.
4. Select **Clear history and recreate cases**. **Cancel** closes the confirmation without changing data.
5. The dashboard refreshes with fresh cases for currently eligible source episodes. Open a journey to see **Case Identified**, including its source snapshot. The worker adds **Foundation Case Ready** shortly afterward. Cancelled/completed episodes and dates outside detection rules do not create new cases.
6. Select **Open agent review** to watch the newly recreated case start automatically. The reset request itself makes no Claude calls, but the worker subsequently uses the configured provider for agent decisions. An enabled live provider consumes the existing shared call budget.

## What changes

| Cleared and recreated | Preserved |
| --- | --- |
| Demo patients and follow-up cases | Staff accounts, passwords and clinic memberships |
| Agent reviews, decisions, delegation and demo replies | Signed-in sessions |
| Handoffs, case audit events and foundation jobs | API keys, model configuration and actual model usage accounting |
| Case identifiers and initial source snapshots | Records belonging to other clinics |

Old case links stop working because new cases receive new identifiers. Reset is permanent for this demo history; the confirmation is not a backup. It does not replenish provider credits or reset the app's daily model allowance.

## If reset does not complete

- **Queued or processing review:** pause active reviews and try again. A waiting review can resume on a timer; if that happens during reset, pause it first.
- **Cases changed:** someone may already have reset the demo. Refresh the dashboard, close the old confirmation, and reopen it before confirming again.
- **Database busy:** a worker or API transaction is finishing. Retry shortly; the conflicting reset does not delete records.
- **Fresh source unavailable or invalid:** check that the mock clinic container is healthy. Existing records are retained.
- **Unexpected records:** the guard refused to clear data whose identity does not match the complete synthetic source snapshot. Ask a developer to inspect it.

## For developers

`GET /api/system` reports `demo_reset_enabled` and the current demo case IDs only to authenticated, authorised staff. `POST /api/demo/reset` requires the server-side flag, a local/test environment, current demo-clinic membership, a valid Origin and CSRF token, `confirmation: "RESET"`, and `expected_case_ids` matching the current dataset. A stale or repeated request cannot erase the newly recreated generation.

The API fetches and validates the complete simulator snapshot before deletion, including the three built-in identities and any generated SIM episodes. Current case/patient identities must match that snapshot. In PostgreSQL it briefly takes non-waiting exclusive table locks, rechecks authority and rejects queued/running reviews. Deletion and eligible-case recreation commit in one transaction. The detector helper saves each eligible candidate snapshot and queues foundation work. The source database, accounts and model budgets are outside the reset set. A late response for a deleted, previously paused run cannot recreate it.

This is a local synthetic-demo capability, not a production patient-record deletion feature. It adds no database migration and does not add the complete event-history system discussed for future product work.
