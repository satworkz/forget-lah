#!/usr/bin/env bash
# Ubuntu/Linux companion to dev.ps1; uses the same Compose services and volumes.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"

usage() {
    echo 'Usage: bash scripts/dev.sh {doctor|setup|build|start|up|deploy|down|logs|test|status|model-check}'
}

secret() {
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
}

setup() {
    umask 077
    if [[ -L .env ]]; then
        echo 'Refusing to modify a symlinked .env.' >&2
        exit 1
    fi
    if [[ ! -e .env ]]; then
        # Never replace an existing configuration, including a concurrent setup.
        (
            set -o noclobber
            {
                printf 'POSTGRES_OWNER_PASSWORD=%s\n' "$(secret)"
                printf 'POSTGRES_APP_PASSWORD=%s\n' "$(secret)"
                printf 'DEMO_STAFF_EMAIL=staff@forget-lah.example\n'
                printf 'DEMO_STAFF_PASSWORD=%s\nWEB_PORT=8080\n' "$(secret)"
            } > .env
        )
    fi
    [[ -f .env ]] || { echo '.env must be a regular file.' >&2; exit 1; }
    chmod 600 .env
    local name
    for name in POSTGRES_MOCK_PASSWORD MOCK_CLINIC_ADMIN_KEY MOCK_CLINIC_FOLLOWUP_KEY; do
        if ! grep -q "^${name}=" .env; then
            printf '\n%s=%s\n' "$name" "$(secret)" >> .env
        fi
    done
    echo 'Local .env ready. Existing values preserved. Open it privately for the demo login.'
}

require_env() {
    [[ -f .env ]] || { echo 'Run bash scripts/dev.sh setup first.' >&2; exit 1; }
}

action="${1:-doctor}"
[[ $# -le 1 ]] || { usage >&2; exit 2; }
case "$action" in
    setup) setup; exit 0 ;;
    help|-h|--help) usage; exit 0 ;;
    doctor|build|start|up|deploy|down|logs|test|status|model-check) ;;
    *) usage >&2; exit 2 ;;
esac
command -v docker >/dev/null || { echo 'Install Docker Engine and the Docker Compose plugin first.' >&2; exit 1; }
case "$action" in
    doctor)
        git --version
        docker version
        docker compose version
        [[ "$(docker info --format '{{.OSType}}')" == linux ]] || {
            echo 'A running Linux Docker engine is required.' >&2; exit 1;
        }
        echo 'Prerequisites passed. Next: bash scripts/dev.sh setup'
        ;;
    build) require_env; setup; docker compose build ;;
    start) require_env; setup; docker compose up -d --no-build ;;
    up|deploy)
        require_env
        setup
        docker compose up --build -d
        echo 'Containers started. Check: bash scripts/dev.sh status'
        echo 'Open http://localhost:8080 (or your WEB_PORT). Login details are in your private .env.'
        ;;
    down) require_env; docker compose down; echo 'Stopped services. Database volume preserved.' ;;
    logs) require_env; docker compose logs --tail 100 api worker bootstrap ;;
    status) require_env; docker compose ps -a ;;
    test)
        require_env
        setup
        docker compose --profile test build tests
        docker compose --profile test run --rm tests
        ;;
    model-check) require_env; docker compose run --rm --no-deps worker python -m forget_lah.runtime.check_model ;;
esac
