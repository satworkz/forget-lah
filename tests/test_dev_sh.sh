#!/usr/bin/env bash
# Exercise the launcher without a Docker socket or the developer's configuration.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/project with spaces/scripts" "$scratch/bin"
cp "$repo/scripts/dev.sh" "$scratch/project with spaces/scripts/dev.sh"
export EXPECTED_ROOT="$scratch/project with spaces" COMMAND_LOG="$scratch/commands"
cat > "$scratch/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -eu
[[ "$PWD" == "$EXPECTED_ROOT" ]]
printf '%s\n' "$*" >> "$COMMAND_LOG"
if [[ "${FAIL_DOCKER:-0}" != 0 ]]; then exit 27; fi
if [[ "$1" == info ]]; then echo linux; fi
EOF
printf '#!/usr/bin/env bash\necho "git fixture"\n' > "$scratch/bin/git"
chmod +x "$scratch/bin/docker" "$scratch/bin/git"
export PATH="$scratch/bin:$PATH"
script="$EXPECTED_ROOT/scripts/dev.sh"
cd /tmp
bash -n "$script"
bash "$script" doctor >/dev/null
if bash "$script" start > /dev/null 2>&1; then echo 'Missing configuration accepted'; exit 1; fi
bash "$script" setup >/dev/null
[[ "$(stat -c %a "$EXPECTED_ROOT/.env")" == 600 ]]
[[ "$(grep -Ec '^[A-Z_]+=[a-f0-9]{64}$' "$EXPECTED_ROOT/.env")" == 6 ]]
cp "$EXPECTED_ROOT/.env" "$scratch/before"
bash "$script" setup >/dev/null
cmp "$EXPECTED_ROOT/.env" "$scratch/before"
# Imported CRLF configuration, including an extra provider setting, is preserved.
printf 'POSTGRES_OWNER_PASSWORD=existing\r\nANTHROPIC_API_KEY=fixture-only\r\n' > "$EXPECTED_ROOT/.env"
bash "$script" setup >/dev/null
grep -q 'POSTGRES_OWNER_PASSWORD=existing' "$EXPECTED_ROOT/.env"
grep -q 'ANTHROPIC_API_KEY=fixture-only' "$EXPECTED_ROOT/.env"
[[ "$(grep -c '^MOCK_CLINIC_FOLLOWUP_KEY=' "$EXPECTED_ROOT/.env")" == 1 ]]
for action in build start up deploy status logs test model-check down; do
    bash "$script" "$action" >/dev/null
done
grep -Fxq 'compose up -d --no-build' "$COMMAND_LOG"
[[ "$(grep -Fxc 'compose up --build -d' "$COMMAND_LOG")" == 2 ]]
grep -Fxq 'compose --profile test run --rm tests' "$COMMAND_LOG"
grep -Fxq 'compose down' "$COMMAND_LOG"
if grep -q -- '--volumes' "$COMMAND_LOG"; then exit 1; fi
if FAIL_DOCKER=1 bash "$script" deploy >/dev/null 2>&1; then exit 1; else [[ $? == 27 ]]; fi
if bash "$script" invalid >/dev/null 2>&1; then exit 1; else [[ $? == 2 ]]; fi
echo 'Linux launcher checks passed: setup, preservation, permissions, paths, commands, failures.'
