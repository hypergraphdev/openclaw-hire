#!/usr/bin/env bash
set -euo pipefail

INSTANCE_ID="${1:-}"
PRODUCT="${2:-}"
REPO_URL="${3:-}"
RUNTIME_ROOT="${4:-/home/wwwroot/openclaw-hire/runtime}"

if [[ -z "$INSTANCE_ID" || -z "$PRODUCT" || -z "$REPO_URL" ]]; then
  echo "Usage: install_instance.sh <instance_id> <product> <repo_url> [runtime_root]" >&2
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

# For zylos, patch to instance-specific runtime paths + unique container name/ports.
# This avoids multi-instance conflicts (container_name/ports/volumes).
if [[ "$PRODUCT" == "zylos" ]]; then
  HASH=$(echo -n "$INSTANCE_ID" | cksum | awk '{print $1}')
  WEB_CONSOLE_PORT=$((34000 + HASH % 1000))
  HTTP_PORT=$((35000 + HASH % 1000))

  INSTANCE_DATA_DIR="$WORKDIR/zylos-data"
  INSTANCE_CLAUDE_DIR="$WORKDIR/claude-config"
  mkdir -p "$INSTANCE_DATA_DIR" "$INSTANCE_CLAUDE_DIR"

  PATCHED_COMPOSE="$WORKDIR/docker-compose.instance.yml"
  SRC_COMPOSE="$COMPOSE_FILE" PATCHED_PATH="$PATCHED_COMPOSE" INSTANCE_ID="$INSTANCE_ID" \
  WEB_CONSOLE_PORT="$WEB_CONSOLE_PORT" HTTP_PORT="$HTTP_PORT" \
  INSTANCE_DATA_DIR="$INSTANCE_DATA_DIR" INSTANCE_CLAUDE_DIR="$INSTANCE_CLAUDE_DIR" \
  python3 - <<'PY'
import os
from pathlib import Path

src = Path(os.environ['SRC_COMPOSE'])
out = Path(os.environ['PATCHED_PATH'])
text = src.read_text()
text = text.replace("container_name: zylos", f"container_name: zylos_{os.environ['INSTANCE_ID']}")
text = text.replace("${WEB_CONSOLE_PORT:-3456}:3456", f"${{WEB_CONSOLE_PORT:-{os.environ['WEB_CONSOLE_PORT']}}}:3456")
text = text.replace("${HTTP_PORT:-8080}:8080", f"${{HTTP_PORT:-{os.environ['HTTP_PORT']}}}:8080")
text = text.replace("- zylos-data:/home/zylos/zylos", f"- {os.environ['INSTANCE_DATA_DIR']}:/home/zylos/zylos")
text = text.replace("- claude-config:/home/zylos/.claude", f"- {os.environ['INSTANCE_CLAUDE_DIR']}:/home/zylos/.claude")
out.write_text(text)
PY

  COMPOSE_FILE="$PATCHED_COMPOSE"
  export WEB_CONSOLE_PORT HTTP_PORT INSTANCE_DATA_DIR INSTANCE_CLAUDE_DIR
fi

# First attempt
if ! "${COMPOSE[@]}" -f "$COMPOSE_FILE" -p "$PROJECT" up -d --build; then
  # legacy cleanup path for old upstream hardcoded zylos container name
  if [[ "$PRODUCT" == "zylos" ]] && docker ps -a --format '{{.Names}}' | grep -qx 'zylos'; then
    echo "WARN: retry after removing conflicting legacy 'zylos' container" >&2
    docker rm -f zylos >/dev/null 2>&1 || true
    "${COMPOSE[@]}" -f "$COMPOSE_FILE" -p "$PROJECT" up -d --build
  else
    exit 22
  fi
fi

# machine-readable output for caller
printf 'COMPOSE_PROJECT=%s\n' "$PROJECT"
printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE"
printf 'RUNTIME_DIR=%s\n' "$WORKDIR"
printf 'REPO_DIR=%s\n' "$REPO_DIR"
