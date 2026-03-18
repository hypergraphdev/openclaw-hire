#!/usr/bin/env bash
set -euo pipefail

INSTANCE_ID="${1:-}"
PRODUCT="${2:-}"
REPO_URL="${3:-}"
RUNTIME_ROOT="${4:-/home/wwwroot/openclaw-hire/runtime}"

if [[ -z "$INSTANCE_ID" || -z "$PRODUCT" || -z "$REPO_URL" ]]; then
  echo "Usage: install_openclaw_instance.sh <instance_id> <product> <repo_url> [runtime_root]" >&2
  exit 2
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: neither 'docker compose' nor 'docker-compose' is available" >&2
  exit 20
fi

WORKDIR="$RUNTIME_ROOT/$INSTANCE_ID"
REPO_DIR="$WORKDIR/repo"
PROJECT="hire_${INSTANCE_ID//-/}"
PROJECT="${PROJECT:0:24}"

mkdir -p "$WORKDIR"

if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch --all --prune
  git -C "$REPO_DIR" reset --hard origin/HEAD || git -C "$REPO_DIR" pull --ff-only
else
  rm -rf "$REPO_DIR"
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
fi

COMPOSE_FILE=""
for c in docker-compose.yml compose.yml docker/docker-compose.yml docker/compose.yml; do
  if [[ -f "$REPO_DIR/$c" ]]; then
    COMPOSE_FILE="$REPO_DIR/$c"
    break
  fi
done

if [[ -z "$COMPOSE_FILE" ]]; then
  echo "ERROR: no compose file found" >&2
  exit 21
fi

CONFIG_DIR="$WORKDIR/openclaw-config"
WORKSPACE_DIR="$WORKDIR/openclaw-workspace"
mkdir -p "$CONFIG_DIR" "$WORKSPACE_DIR"

HASH=$(echo -n "$INSTANCE_ID" | cksum | awk '{print $1}')
OPENCLAW_GATEWAY_PORT=$((37000 + HASH % 1000))
OPENCLAW_BRIDGE_PORT=$((38000 + HASH % 1000))

cat > "$WORKDIR/.env" <<EOF
OPENCLAW_IMAGE=${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}
OPENCLAW_CONFIG_DIR=$CONFIG_DIR
OPENCLAW_WORKSPACE_DIR=$WORKSPACE_DIR
OPENCLAW_CONFIG_MOUNT_MODE=rw
OPENCLAW_WORKSPACE_MOUNT_MODE=rw
OPENCLAW_GATEWAY_PORT=$OPENCLAW_GATEWAY_PORT
OPENCLAW_BRIDGE_PORT=$OPENCLAW_BRIDGE_PORT

ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-http://172.17.0.1:18080}
ANTHROPIC_AUTH_TOKEN=${ANTHROPIC_AUTH_TOKEN:-}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-${ANTHROPIC_AUTH_TOKEN:-}}
OPENAI_API_KEY=${OPENAI_API_KEY:-${CODEX_API_KEY:-}}
CODEX_API_KEY=${CODEX_API_KEY:-${OPENAI_API_KEY:-}}
EOF
chmod 600 "$WORKDIR/.env" >/dev/null 2>&1 || true

COMPOSE_ARGS=(-f "$COMPOSE_FILE" -p "$PROJECT" --env-file "$WORKDIR/.env")
compose_log="$(mktemp)"
if ! "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build >"$compose_log" 2>&1; then
  cat "$compose_log" >&2 || true
  rm -f "$compose_log" >/dev/null 2>&1 || true
  exit 22
fi
rm -f "$compose_log" >/dev/null 2>&1 || true

printf 'COMPOSE_PROJECT=%s\n' "$PROJECT"
printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE"
printf 'RUNTIME_DIR=%s\n' "$WORKDIR"
printf 'REPO_DIR=%s\n' "$REPO_DIR"
printf 'WEB_CONSOLE_PORT=%s\n' "$OPENCLAW_GATEWAY_PORT"
printf 'HTTP_PORT=%s\n' "$OPENCLAW_BRIDGE_PORT"
