# Singapore AWS demo

## Deployment scope

The team authorised an organiser-account Lightsail deployment in `ap-southeast-1` on 18 September 2026. The existing direct Anthropic provider remains selected until the organiser URL/key are supplied and tested. Anthropic and Twilio charges are separate from the organiser's shared hosting/model allowance.

- Instance: `forget-lah-demo`, Ubuntu 24.04, `small_3_0` (2 GB RAM, 2 vCPU, 60 GB disk).
- AWS's bundle API reported USD 12/month. Lightsail charges hourly up to the plan maximum; stopping an instance does not eliminate its storage/plan charges. Delete unneeded resources after the event, after preserving anything required.
- Static IP resource: `forget-lah-demo-ip`.
- Demo hostname: `forget-lah.52-220-111-31.sslip.io`. The third-party DNS service maps the embedded IP to the server; Caddy obtains a certificate for this hostname. It is a demo dependency, not a domain owned by the team.
- Ports 80 and 443 are public. SSH is restricted to the deployment connection's public IPv4 address. Database, source API and application API ports are not published.
- Fresh synthetic database and a separate randomly generated staff password. Local test history is not copied or reset.
- `APP_ENV=demo` enables the authenticated synthetic clinic editor. The team has explicitly enabled `DEMO_RESET_ENABLED=true` for AWS testing. Reset requires staff sign-in, CSRF validation, typing `RESET`, and the current case generation; it refuses active work. It clears synthetic follow-up history and patient preferences, preserves staff accounts and model usage, and rebuilds from the current clinic simulator records. This is not a production clinical deployment.
- One server is a single point of failure. Durable Docker volumes survive container replacement; they are not an off-server backup.

## Files and credentials

`compose.yaml` is still the local Windows/Ubuntu configuration. Add `deploy/compose.cloud.yaml` only for the cloud deployment. It overrides the public origin and web ports, mounts `deploy/Caddyfile.cloud`, and persists TLS certificates in Docker volumes.

`deploy/install-host.sh` installs Docker using its official Ubuntu repository. It uses POSIX shell syntax because Lightsail wraps user-data scripts. No secrets go in user data. Host logs rotate; application request-body logging stays disabled.

Private deployment material is saved locally under the ignored `.cache/aws/` directory:

- `cloud.env`: cloud-only database/staff credentials and the selected backend model key.
- `state.json`: account, region, resource names and IP.
- `forget-lah-demo.pem`: SSH private key.
- `known_hosts`: server SSH key pinned on first connection to the AWS-reported IP.

Do not commit or share these files. AWS session credentials remain in the local named AWS profile; they are not uploaded to the server. The cloud environment also holds backend-only Twilio test-phone configuration for the explicitly enabled channel.

The remote release directory is `/home/ubuntu/forget-lah`, accessible only to its owner. Its `.env` is mode 600. Read `DEMO_STAFF_EMAIL` and `DEMO_STAFF_PASSWORD` from local `cloud.env` for the cloud login; these differ from local development credentials.

## Build and update

Build on the development computer so the 2 GB server does not have to run the frontend and Python builds:

```text
docker compose build api web
docker tag forget-lah-web:latest forget-lah-web:cloud
docker save -o .cache/aws/images.tar forget-lah-local:0.2.0 forget-lah-web:cloud
docker compose --env-file .cache/aws/cloud.env -f compose.yaml -f deploy/compose.cloud.yaml config --quiet
```

Transfer the image archive, Compose files, cloud Caddyfile and database init script over SSH to the release directory. Transfer private configuration separately with mode 600, preserving established database passwords on updates. Avoid displaying `docker compose config` without `--quiet`, because expanded output contains credentials.

On the host:

```sh
cd /home/ubuntu/forget-lah
sudo docker load -i images.tar
sudo docker compose -f compose.yaml -f deploy/compose.cloud.yaml up -d --no-build
sudo docker compose -f compose.yaml -f deploy/compose.cloud.yaml ps -a
```

Bootstrap runs forward migrations and seeds missing synthetic fixtures. Do not run `down --volumes`. Verify `/health/ready`, authenticated case access, secure cookies, origin/CSRF rejection and worker progress after updates. A failed model call must not fall back to mock mode.

## Provider switch and next channel milestone

To switch later, save the organiser's URL/key privately, validate the adapter with a bounded synthetic model check, then select `AGENT_MODEL_MODE=organiser` and recreate the runtime containers. Do not assume the organiser protocol matches the direct Anthropic API.

The staff workspace, restricted WhatsApp channel and multilingual stage are implemented in the next release with migration `0008`. Configure the Sandbox webhook and complete the real Alex reply round trip before claiming end-to-end delivery. See [team cloud testing](TEAM_CLOUD_TESTING.md).

References: [Lightsail billing](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-frequently-asked-questions-faq-billing-and-account-management.html), [Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/), [demo DNS and TLS](https://sslip.io/).

## Verified deployment results

On 18 September 2026: container builds, Ruff checks and the full Linux container test suite (including PostgreSQL tests) passed. Native Windows test collection was blocked by its application-control policy on the psycopg binary; Linux was the validation environment.

Public HTTPS returned 200, HTTP redirected to HTTPS, readiness returned 200, anonymous case access returned 401, and authenticated case and clinic-editor reads returned 200. The session cookie was Secure; incorrect Origin and missing CSRF token each returned 403. Bootstrap exited successfully and all long-running services were running, with the three healthchecked services healthy. Approximately 255 MiB of aggregate container memory was observed at idle; this is not a load test.

A budgeted direct Anthropic check returned MODEL_CONNECTION_VERIFIED. After automatic reviews were enabled, Mr Lim, Alex and Priya each reached Waiting with Engagement active after three steps. No real patient or WhatsApp case message was sent. The cloud login is also saved separately in the ignored local `.cache/aws/cloud-login.txt` file.

The initial Lightsail user-data wrapper ran the original installer through `/bin/sh` and rejected its Bash-only option. The committed installer was corrected to POSIX shell and rerun successfully over SSH. The original cloud-init error remains historical in the host log; Docker, migrations and health checks were verified after recovery.


### Decision-repair update

The cloud release now includes migration `0007` for decision-validation evidence. A logical database backup was saved on the host at `backups/before-0007.dump` before applying the forward migration; this is a local recovery copy, not an off-server backup. Priya's original paused case resumed successfully and reached `NO_AVAILABLE_SLOTS` with a patient-facing explanation and an AMBER staff task. No history was reset. The release passed 291 tests including PostgreSQL checks.


## 22 September: current appointment-change build deployed

Deployed commit `8d9f7d0` (staff appointment changes with review) to the existing Singapore demo. Built locally and transferred the verified API/worker/source image and production web image. All three runtime services were checked against the exact local image identity. Existing cloud environment and credentials were retained; no local database or local case recovery was copied to AWS.

With application services stopped, both cloud databases were backed up on the host and copied to ignored private local deployment storage. Applied application migrations `0010` to `0015` and source migration `sim0003` to `sim0004`, without fixture seeding or data reset. Checksums of all 25 pre-existing tables matched immediately after migration; eight new tables bring the total to 33. Previous runtime images and Compose configuration were retained for recovery.

Public HTTPS readiness, authenticated case access, secure session cookies, anonymous access rejection, missing-CSRF rejection, the appointment-change read endpoint and the new frontend controls passed. After restart, existing cases, runs, steps, events, messages, handoffs, phone bindings, delivery records, model usage and source appointment tables remained unchanged. Verification created login sessions; runtime channel-routing metadata also updated. No patient action, live model call, case replay or test notification was initiated.

The deployed build includes the instruction-review action and the correction that waits for a patient reply after a staff change. [GAP-STAFF-CHANGE-001](STAFF_APPOINTMENT_CHANGE_GAPS.md), starting/resuming outstanding patient checks from the appointment panel, remains explicitly deferred and unimplemented. Prior validation for this exact code includes the full 570-pass/14-skip regression baseline and the final timer/recovery-related 157-pass/1-skip run; deployment rebuilt the images and performed the cloud checks above.


## 23 September: security build deployed

Deployed the verified local runtime and web images to the existing AWS demo, including migration `0016`, Security & Audit, per-clinic roles, Bridge intake controls, staff-visible names and the partial-import review fix. Source migration remains `sim0004`. All 48 backend source files matched the working local runtime before transfer; deployed API/worker source and the public frontend bundle matched afterward.

Both databases were backed up and their dump listings validated. All pre-existing values across 33 tables matched before migration, after migration and after API/web/source restart, before worker resumption. The existing `.env` checksum was unchanged. No seeding, reset, test patient action, case replay or secret rotation was performed. Existing worker behavior resumed after verification.

Release backups, previous images and Compose files remain on the host under the `20260923-security` release/backup names. Both database dumps and preservation manifests were copied to private local `.cache/aws/release-20260923-security/`. PostgreSQL has no published host port. HTTPS readiness, anonymous rejection, secure login, audit access, appointment-change read, CSRF rejection and security-event runtime grants passed. Eight configured credential values were checked against the last 500 log lines per service; no matches were found.

Final focused tests against the release source and current test fixtures: **50 passed, 1 expected skip**, including PostgreSQL and partial-import behavior. Earlier release evidence includes the 624-pass/14-skip broad security baseline and subsequent focused fixes; that broad suite was not rerun for this deployment. An initial run used older fixtures and failed four historical-schema seeding tests; using the current fixtures resolved those failures.

Release provenance: the current checkout lacked some security files, so deployment used the working local image, not a rebuild from that checkout. The copied runtime source, migrations, image archive and SHA-256 manifest are retained privately with this release. Reconcile the checkout with this source snapshot before any future rebuild; the deployed image is the authoritative artifact for this release.

## 23 September: option-selection routing fix deployed

Deployed runtime image `sha256:a9ae19c2a402ab80775799d74a8b8b8bfcae4613c0681fbc421bbeb6f0fa27ca` to API and worker locally and on AWS. The checkout was compared with the saved security-release source; it now matches that baseline apart from this focused fix (earlier byte differences were line endings). Existing frontend and synthetic source containers remain. No migration, seeding, reset or configuration change.

A CHANGE / SEARCH_SLOTS interpretation no longer hides an existing offer from Engagement or overrides a validated selection/receipt with search instructions. Offline regressions reproduce the original Priya message sequence, uncertain selection and requests for other options. Complete regression: **638 passed, 14 expected skips**, including PostgreSQL checks. Ruff, formatting and production frontend build passed. Both API/worker instances match the exact built image; local/public readiness and authenticated cloud access/CSRF checks passed.

Before restart, both databases were backed up per environment and dump listings validated. All values across 34 tables matched before/after API replacement, before worker resumption. Cloud `.env` checksum was unchanged. Cloud recovery artifacts remain under `backups/20260923-selection` and `releases/20260923-selection`, with database dumps/manifests copied to local private `.cache/aws/release-20260923-selection/`. Local backups are in `.cache/selection-local-20260923/`. The previous local running image ID was unavailable for tagging, so the retained security release archive was loaded and tagged as the local rollback baseline before stopping services.

Bounded AWS validation used the already-staged, unconnected Priya synthetic case. The three patient messages were submitted once each. A transient model connection failure recovered through the built-in retry without another patient submission. Run `ff4d8fce-0900-4d89-b101-4e42bbebd80c` completed at step 33: scan MET (11), model INTERPRET_SELECTION / option 1 (25), permitted source receipt (26), acknowledgement (32), completion (33). One offer, one successful rescheduling receipt. Independent source read verified 25 September 10:00 → 30 September 10:00 SGT, episode version 2. No phone delivery.

The completed rehearsal and original failed trace remain. Fresh recording review `7e1567c3-76d2-4657-9d72-ad824b572e36` waits at one English reminder for the new 30 September appointment. Chen and Calvin's full case views match their pre-deployment snapshots; their translated opening reminders remain ready. See [current recording handoff](video/RECORDING_HANDOFF_2026-09-23.md). No MP4 was produced in this repair.


## 23 September: staff English translations deployed

API, worker and web now display original patient messages beside a separate cached English translation in the staff clinical handoff and Case journey. New replies queue display-only translation after active agent work finishes; historical messages use a scoped translation/retry action. Delivered clinic messages expose their English source alongside translated wording. Migration `0017` adds nullable translation metadata; source remains `sim0004`.

Validation: full regression **645 passed, 14 expected skips**, including PostgreSQL; final focused translation/action tests **10 passed**, including a PostgreSQL API test. Ruff lint/format, production web build, isolated rendered UI and live AWS UI checks passed. The final focused checks cover the small changes made after the full suite. A live historical-message request initially exposed an overlong audit event label; the label was shortened and its PostgreSQL regression passed before the corrected API/worker release was verified.

Both databases were backed up before each rollout, with validated dumps retained on AWS and copied to private local release storage. Existing values across 34 tables were preserved through migration/restart. The corrected restart added five access-denial security audit rows from browser polling; every original audit row was independently verified unchanged. Cloud `.env` checksum was unchanged. No source container replacement, global reset, appointment change, phone rebinding or scene replay was used to validate translation.

Authenticated API and rendered AWS staff view verified the saved Ahmad reply in Malay alongside: “Yes, I confirm the appointment, but I am experiencing swelling and pain.” The original event, run, handoff, appointment records and channel ledger remained unchanged by this translation-only check. This consumed one bounded translation call and sent no patient message. Deployed backend source matches the local source. Runtime/web rollback images and recovery artifacts remain under `20260923-stafftranslation` and `20260923-stafftranslation-auditfix` release/backup paths.

At the user's subsequent request to repeat the recording, a fresh Ahmad review was started using existing synthetic controls, preserving prior review history and other patients. This recording preparation is separate from deployment validation. Local runtime containers were not restarted or migrated in this task.

The user then sent the new WhatsApp reply during recording preparation. The new run escalated RED and automatically saved the English translation beside the unchanged Malay original, without a manual translation request. Staff ownership remained unaccepted and the task open at verification.

## 23 September: doctor notes and instruction-answer quote correction

Deployed API, worker and web images from release `20260923-quotefix`. Staff patient details now expose approved doctor notes from the bound source. Scan-answer quotes use existing typography-only restoration, retaining strict source evidence validation.

Backups and rollback image tags are under `20260923-quotefix`; no migration or global reset. Both source and application backups were validated, and all 34 existing table hashes matched after the read-only saved-decision replay. Runtime readiness passed and the AWS doctor-notes panel and endpoint were verified for all nine cases. The original Priya run remains paused, with the same saved reply and case version; no fresh patient message was sent.

**23 September confirmed-intent correction:** API/worker updated from `20260923-confirmfix`; backups and rollback image tags use that identifier. The rule preserves an already accepted confirmation and delegates Preparation before another model interpretation. Full regression: 657 passed, 14 expected skips. Readiness and saved Priya/channel state verified. No source reset, migration, phone rebinding or patient message. Both database dumps validated; 34-table deployment checksums matched.

**23 September scan-answer date constraints:** API/worker deployed from `20260923-scandate`; backup/rollback tags use that identifier. Full suite 664 passed / 14 expected skips; source-scoped date filtering and booking checks covered offline. Both database dumps validated; all 34 table hashes matched. Readiness and live record preservation verified. Invalid Priya recording run `ba0ceef0-e787-4783-952e-b93a2bfbc1a8` was then paused through the staff control; no patient message, source write or global reset. Live model rehearsal was not performed.
# 23 September WhatsApp continuity and latency correction

Release `20260923-channel-fix` deployed API/worker to the existing AWS demo. WhatsApp now preserves source-bound doctor-check resolutions between replies. Policy-approved options dispatch saves one model call; Anthropic transport retry cooldown is two seconds with the existing attempt cap. See REPLY_RECOVERY.md and PERFORMANCE.md for evidence and limitations.

Validation: 673 passed, 14 expected skips; final focused selection/performance/provider checks passed, including a negative control that reproduces the selection failure without the channel fix. Ruff, formatting and web build passed. Both databases backed up and validated; all 34 table snapshots matched, schema heads remain `0017`/`sim0004`, environment checksum unchanged, readiness passed. Priya's full conversation, source episodes/slots, phone bindings and channel ledger matched predeployment state. No live inference, conversation reset, source appointment write or outgoing message was performed. Current damaged waiting conversation remains unchanged; recording requires a separately requested fresh start. Live latency is not yet benchmarked.
# 23 September conversation continuation deployment

Release `20260923-continuity` deployed API/worker. Practical-plan conflicts now wait for compatible plans before confirmation; social-only continuations do not repeat appointment work; cancellation remains a staff request, including while a prerequisite question is open. Translation explicitly includes quoted clinic instructions, and raw staff-check notes are withheld from confirmation text. See REPLY_RECOVERY.md for scope and limitations.

User-directed validation: only the 14 new focused tests were run, all passed; Ruff/format and the web build passed. The user is independently running the full regression suite; its result is not asserted here. Both database backups validated, all 34 table snapshots matched, schema heads unchanged (`0017`, `sim0004`), environment checksum passed. Public readiness and authenticated preservation checks passed for all nine case histories, source records/slots, bindings and channel state. No live inference, patient message, reset or conversation replay occurred during this fix/deployment.
# 23 September translation and plan continuation correction

Release `20260923-translation-plan` deployed API/worker after seven new focused tests passed. Grossly incomplete translations are withheld and receive at most one budgeted retry; pending plan replies route directly to Preparation and can resume source-bound attendance consent for the unchanged appointment time. Ruff/format and frontend build passed; full regression was not rerun per user instruction. Both backups validated, all 34 table hashes matched, revisions and environment unchanged, readiness passed. All nine case histories, source records, phone bindings and channel state matched predeployment snapshots. No live model replay or message was sent. Alex's failed recording remains paused and unchanged. See REPLY_RECOVERY.md for limitations.

**23 September: required translation sections deployed (`20260923-translation-sections`).** Nine new offline tests, Ruff/format and web/runtime builds passed. Both database backups validated; all 34 table hashes, authenticated readiness, all nine case histories, source data and phone/channel state preserved. No paid inference, automatic retry or outgoing message was performed. Full regression remains with the user; live translation success is not yet verified. See REPLY_RECOVERY.md.


## 25 September: organiser gateway deployed

API and worker now use the supplied organiser gateway/model for agents, Bridge intake and translations. Application/source heads remain `0017`/`sim0004`. Both databases were backed up; 34-table pre-existing values matched before provider switching. Seven waiting/paused runs received the new provider with security audit records and all other fields unchanged. The live AWS synthetic check returned MODEL_CONNECTION_VERIFIED in 3120 ms. Focused tests: 156 passed/1 skipped, plus 33 Docker/PostgreSQL tests passed. See [organiser integration, limitations and recovery](ORGANISER_GATEWAY.md). This supersedes earlier notes that organiser verification is pending.


## 25 September: business and technical failure handoff deployed

Release `20260925-failure-handoff` uses `forget-lah-failure:20260925` for API and worker; the frontend remains unchanged. Exact runtime source hashes matched the checkout after deployment. Organiser configuration and all environment values are unchanged. No migration, reset, fixture seed or appointment replay was performed.

Both PostgreSQL databases were backed up and the archives validated. All pre-existing values across 34 tables matched before and after API restart, before the worker resumed. Application/source versions remain `0017`/`sim0004`. Previous images and configuration are retained in the release backup directory for rollback.

The existing policy-denied Omar review was recovered into one unowned AMBER staff handoff and one static Malay acknowledgement without another model call. Its appointment time, version, available options and original decision evidence are unchanged; Bridge follow-up status is now `needs_staff`. At verification, acknowledgement delivery remained queued: the enrolled phone's last inbound message was approximately 36.3 hours old, outside the application's 23-hour outbound reply gate. No provider receipt exists yet. A queued message is not a delivered message, and the gate was not bypassed.

Public HTTPS/readiness, protected access, secure login, authenticated audit/appointment reads and CSRF rejection passed. API/worker source manifests and organiser settings matched; PostgreSQL has no public port binding. Scans of recent API/worker/web/source/database logs found no matches for the nine configured credential values checked.

Validation: Ruff and formatting passed; Docker runtime and frontend builds passed. The full regression run recorded 713 passed, 14 skipped and 12 failures in older expectations for pause/retry/no-message behavior. Those assertions were updated while retaining source-write and evidence protections. The affected-suite rerun recorded 126 passed with four remaining old slot-message assumptions; those were corrected and all six unclear-reply cases passed. The final acceptance run covering every previously failing case, all new failure tests and PostgreSQL migration/concurrency tests passed **51/51**. The complete broad suite was not repeated after these targeted fixes. Two test-client dependency deprecation warnings remain. No paid model or source-action replay was used for this repair.

See [failure behavior, exact changed files and limitations](FAILURE_HANDLING.md). Staff navigation: open the case, locate **Staff owner needed**, and choose **Accept handoff as me**. Accepting ownership does not itself resolve the patient's request.
