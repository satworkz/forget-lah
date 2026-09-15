# Ubuntu team quick start

Use a terminal in your own clone of the repository. Install Git and Docker Engine with the Docker Compose plugin; Docker must be running and usable by your account. The script does not install packages or change user permissions. Python and Node run inside containers, so local installations are not required.

## First run

```bash
bash scripts/dev.sh doctor
bash scripts/dev.sh setup
bash scripts/dev.sh deploy
bash scripts/dev.sh status
```

`setup` creates a private `.env` with fresh random credentials. Open it locally in your editor for `DEMO_STAFF_EMAIL` and `DEMO_STAFF_PASSWORD`. Never commit or share it. Re-running setup preserves existing values and adds missing simulator secrets. Do not copy another teammate's database passwords into an existing installation.

`deploy` builds and starts the local containers using the existing Compose file. Bootstrap creates/migrates the databases and seeds demo data. Wait for the API/database to be healthy, then open **http://localhost:8080**. If you changed `WEB_PORT` in `.env`, use that port instead. Start with the [patient simulator guide](PATIENT_SIMULATOR.md).

Default model mode is the offline simulator. For live Claude, follow [Claude setup](CLAUDE_SETUP.md), enter credentials privately in your own `.env`, and run `deploy` again. `model-check` makes a billable model call when a live provider is configured.

## Everyday commands

| Command | Purpose |
|---|---|
| `bash scripts/dev.sh build` | Build images without starting containers |
| `bash scripts/dev.sh start` | Start/recreate containers from images already built |
| `bash scripts/dev.sh deploy` | Build and start/recreate after pulling new code |
| `bash scripts/dev.sh up` | Same as deploy |
| `bash scripts/dev.sh status` | Show all service states, including bootstrap |
| `bash scripts/dev.sh logs` | Show recent API, worker and bootstrap logs |
| `bash scripts/dev.sh test` | Build/run automated tests, including PostgreSQL checks |
| `bash scripts/dev.sh down` | Stop containers; preserve database volume |

After `git pull`, run `bash scripts/dev.sh deploy` and refresh the browser. An exited bootstrap container with exit code **0** is normal; it is a one-time setup job. If it exits with another code, check logs.

If Docker reports permission denied, resolve Docker access using your installation's administrator guidance and rerun `doctor`. Do not run the setup script with sudo to work around Docker permissions. If port 8080 is occupied, set another `WEB_PORT` in `.env` and run deploy again.

The same commands work in a terminal opened elsewhere when you use the script's full path. `bash scripts/dev.sh ...` avoids needing to change executable permissions. Git already enforces Linux line endings for `.sh` files.

This deploys to containers on the configured Docker engine. It does not provision AWS or publish the app. The shared Compose configuration binds the web port to local loopback. On a remote Ubuntu development machine, use an SSH tunnel to access it; public hosting requires separate deployment work.

Windows teammates continue using `scripts/dev.ps1` unchanged. Both launchers use the same images, services, migrations and data model, but each teammate has their own local data and private configuration.
