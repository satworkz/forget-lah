# Demo response performance

The worker runs two agent execution slots for different cases, with separate loops for message delivery, translation and source detection. These are execution slots for the existing Coordinator, Engagement and Preparation roles, not additional logical agents. A slow network call in one loop no longer holds up all other work.

PostgreSQL remains the durable queue. Existing row locks, per-run leases, stale-result rejection, idempotency, source booking checks and shared model budgets remain authoritative. One case still processes its steps in order. An unexpected loop failure stops the supervised process so the container can restart; unfinished work remains recoverable through leases. This is concurrency within one worker container, not independent host high availability.

Ready agent steps continue immediately. Empty queues wait 250 ms. Source detection runs every two seconds. Provider request pacing and error retry delays remain separate and unchanged. WhatsApp sandbox send pacing also remains unchanged.

Mandatory specialist source reads pass through the existing policy gateway without asking Claude to choose an already-required read. They remain visible as rule-origin steps with zero model attempts. Claude still interprets patient language, decides delegation and actions, and interprets the returned evidence. Failed reads return to the existing recovery path.

The staff case screen shows a short current activity while a review is queued or running. It does not show technical traces.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| AGENT_PARALLELISM | 2 | Concurrent execution slots for separate cases; maximum 4 |
| AGENT_STEP_DELAY_SECONDS | 0 | Artificial delay between ready steps |
| WORKER_IDLE_SECONDS | 0.25 | Empty-queue polling interval |
| SOURCE_POLL_INTERVAL_SECONDS | 2 | Source detection interval |
| AGENT_REQUIRED_READS_ENABLED | true | Skip model calls that only select mandatory reads |
| AGENT_MIN_INTERVAL_SECONDS | 2 | Existing shared model request pacing; also used by existing retry paths |

For diagnosis, set AGENT_PARALLELISM=1 and AGENT_REQUIRED_READS_ENABLED=false to disable those optimizations. Separate delivery and translation loops remain active. No database migration or data reset is required.

## Validation and limits

A controlled slot-offer regression compares optimization disabled and enabled: 11 to 8 model calls, identical patient response and offered slot, no booking write and no handoff. A blocked-call test verifies another case and delivery can progress. PostgreSQL concurrency tests verify separate cases can run simultaneously without reclaiming their active leases. A live Claude test also passed for a Tamil evening preference against a synthetic missed-appointment source: only the matching evening slot was offered, with no handoff or booking write. This checks interpretation and composition, not physical WhatsApp delivery. The full regression suite remains the release gate.

Model latency and shared provider limits still affect response time; these changes do not guarantee a particular number of seconds. Real-device timing should be measured separately from the deterministic comparison.

## 23 September dispatch and retry correction

23 September correction: a source-reviewed, policy-allowed options offer is dispatched as a rule step, saving the model call that merely selected `send_simulated_options`. The shared `AGENT_REQUIRED_READS_ENABLED` switch also controls this optimization. Readiness does not override the policy gateway or source constraints.

The Anthropic transport-error retry cooldown is now two seconds instead of thirty, with the existing two-attempt cap and shared request budget retained. Provider rate-limit/server-error delays still honor the existing handling. Diagnostics record only the exception class and elapsed time, without request contents or credentials. Saved live steps showed approximately 59 seconds in each twice-attempted scheduling assessment; they did not retain the first attempt's error, so its exact cause cannot be established retrospectively. Live end-to-end latency has not been benchmarked after this change.

The controlled offline slot-offer comparison now uses 7 model calls with optimizations enabled versus 11 disabled (previously 8 versus 11). This is one additional saved call, not a measured proportional reduction in WhatsApp response time.

## Future reactive design

PostgreSQL LISTEN/NOTIFY can wake workers after a durable job is committed, with periodic polling retained for missed notifications, retries and expired leases. Notifications would be wake-up hints; stored jobs remain the source of truth. This is planned, not implemented. A separate managed message queue can be evaluated later if volume warrants the additional infrastructure.
