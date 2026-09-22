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
