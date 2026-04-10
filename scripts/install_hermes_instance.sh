#!/usr/bin/env bash
# ── Install Hermes Agent instance ──────────────────────────────────────────
# Follows the same pattern as install_zylos_instance.sh:
#   1. Clone repo (or update)
#   2. Generate docker-compose.instance.yml (pre-built image)
#   3. Allocate ports, set up nginx proxy
#   4. Docker compose up
#   5. Output machine-readable metadata
set -euo pipefail

INSTANCE_ID="${1:-}"
PRODUCT="${2:-}"
REPO_URL="${3:-}"
RUNTIME_ROOT="${4:-/home/wwwroot/openclaw-hire/runtime}"

if [[ -z "$INSTANCE_ID" || -z "$PRODUCT" || -z "$REPO_URL" ]]; then
  echo "Usage: install_hermes_instance.sh <instance_id> <product> <repo_url> [runtime_root]" >&2
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
PROJECT="hermes_${INSTANCE_ID}"

NGINX_VHOST_CONF="/usr/local/nginx/conf/vhost/www.ucai.net.conf"
HERMES_PROXY_DIR="/usr/local/nginx/conf/vhost/hermes-instances"

# ── Nginx proxy ────────────────────────────────────────────────────────────

ensure_hermes_proxy_include() {
  mkdir -p "$HERMES_PROXY_DIR"
  if [[ -f "$NGINX_VHOST_CONF" ]] && ! grep -q "hermes-instances/\*.conf" "$NGINX_VHOST_CONF"; then
    sed -i '/# HXA-Connect/i\    include /usr/local/nginx/conf/vhost/hermes-instances/*.conf;' "$NGINX_VHOST_CONF"
  fi
}

write_hermes_proxy_route() {
  local id="$1"
  local port="$2"
  local conf="$HERMES_PROXY_DIR/${id}.conf"
  cat > "$conf" <<EOF
location = /connect/hermes/${id} {
    return 301 /connect/hermes/${id}/;
}
location ^~ /connect/hermes/${id}/ {
    proxy_pass http://127.0.0.1:${port}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 300s;
}
EOF
  nginx -t >/dev/null 2>&1 && nginx -s reload >/dev/null 2>&1 || true
}

# ── Port allocation ────────────────────────────────────────────────────────

port_in_use() {
  local p="$1"
  ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "(^|:)$p$"
}

find_free_port() {
  local p="$1"
  while port_in_use "$p"; do
    p=$((p + 1))
  done
  echo "$p"
}

# ── Clone / update repo ───────────────────────────────────────────────────

mkdir -p "$WORKDIR"

if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch --all --prune
  git -C "$REPO_DIR" reset --hard origin/HEAD || git -C "$REPO_DIR" pull --ff-only
else
  rm -rf "$REPO_DIR"
  git clone --depth 1 "$REPO_URL" "$REPO_DIR"
fi

# ── Allocate ports ─────────────────────────────────────────────────────────
# Use 36000+ range to avoid collision with Zylos (34000-35000)

HASH=$(echo -n "$INSTANCE_ID" | cksum | awk '{print $1}')
GATEWAY_PORT=$(find_free_port $((36000 + HASH % 1000)))
HTTP_PORT=$(find_free_port $((37000 + HASH % 1000)))

# ── Prepare data directory ─────────────────────────────────────────────────

HERMES_DATA_DIR="$WORKDIR/hermes-data"
mkdir -p "$HERMES_DATA_DIR"

# Docker volume host path (for Docker-in-Docker scenarios)
if [[ -n "${HOST_RUNTIME_ROOT:-}" ]]; then
  HOST_WORKDIR="$HOST_RUNTIME_ROOT/$INSTANCE_ID"
  HOST_DATA_DIR="$HOST_WORKDIR/hermes-data"
else
  HOST_DATA_DIR="$HERMES_DATA_DIR"
fi

# ── Generate docker-compose.instance.yml ───────────────────────────────────

PATCHED_COMPOSE="$WORKDIR/docker-compose.instance.yml"

# Use pre-built image if available, otherwise build from source
if docker image inspect hermes-agent:latest >/dev/null 2>&1; then
  HERMES_IMAGE_SECTION="    image: hermes-agent:latest"
else
  echo "WARN: hermes-agent:latest not found locally, will build from source (slow)" >&2
  HERMES_IMAGE_SECTION="    build:\n      context: ./repo\n      dockerfile: Dockerfile"
fi

cat > "$PATCHED_COMPOSE" <<COMPOSEOF
services:
  hermes:
$(echo -e "$HERMES_IMAGE_SECTION")
    container_name: hermes_${INSTANCE_ID}
    restart: unless-stopped
    env_file: .env
    stdin_open: true
    tty: true
    command: ["gateway"]
    environment:
      HERMES_HOME: /opt/data
    ports:
      - "${GATEWAY_PORT}:8443"
      - "${HTTP_PORT}:8080"
    volumes:
      - ${HOST_DATA_DIR}:/opt/data
    healthcheck:
      test: ["CMD", "python3", "-c", "print('ok')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 300s
    deploy:
      resources:
        limits:
          memory: 8g
          cpus: "4.0"
        reservations:
          memory: 512m
COMPOSEOF

# ── Write .env ─────────────────────────────────────────────────────────────

# Read user-level API settings from DB (priority over admin global settings)
_USER_OPENAI_KEY=""
_USER_OPENAI_BASE=""
_USER_MODEL=""
if command -v python3 >/dev/null 2>&1; then
  _OWNER_ID="$(cd "$(dirname "$0")/../backend" 2>/dev/null && python3 -c "
from app.database import get_connection
conn = get_connection()
cur = conn.cursor(dictionary=True)
cur.execute('SELECT owner_id FROM instances WHERE id = %s', ('$INSTANCE_ID',))
r = cur.fetchone()
print(r['owner_id'] if r else '')
cur.close(); conn.close()
" 2>/dev/null || true)"
  if [[ -n "$_OWNER_ID" ]]; then
    eval "$(cd "$(dirname "$0")/../backend" 2>/dev/null && python3 -c "
from app.database import get_user_setting
uid = '$_OWNER_ID'
k = get_user_setting(uid, 'openai_api_key', '')
b = get_user_setting(uid, 'openai_base_url', '')
m = get_user_setting(uid, 'default_model', '')
print(f'_USER_OPENAI_KEY={k}')
print(f'_USER_OPENAI_BASE={b}')
print(f'_USER_MODEL={m}')
" 2>/dev/null || true)"
  fi
fi

# Resolve final values: user settings > env vars > empty
_FINAL_API_KEY="${_USER_OPENAI_KEY:-${OPENAI_API_KEY:-${OPENROUTER_API_KEY:-}}}"
_FINAL_BASE_URL="${_USER_OPENAI_BASE:-${OPENAI_BASE_URL:-}}"
_FINAL_MODEL="${_USER_MODEL:-deepseek-chat}"

cat > "$WORKDIR/.env" <<ENVEOF
# Hermes Agent Configuration
HERMES_HOME=/opt/data
# LLM Provider
OPENROUTER_API_KEY=${_FINAL_API_KEY}
OPENAI_API_KEY=${_FINAL_API_KEY}
OPENAI_BASE_URL=${_FINAL_BASE_URL}
# Gateway
GATEWAY_ALLOW_ALL_USERS=true
# Fallback providers
GOOGLE_API_KEY=${GOOGLE_API_KEY:-}
# Messaging platforms
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_ALLOWED_USERS=${TELEGRAM_ALLOWED_USERS:-}
SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN:-}
# Terminal backend
TERMINAL_ENV=${TERMINAL_ENV:-local}
TERMINAL_TIMEOUT=${TERMINAL_TIMEOUT:-120}
# Ports
GATEWAY_PORT=${GATEWAY_PORT}
HTTP_PORT=${HTTP_PORT}
ENVEOF
chmod 600 "$WORKDIR/.env" >/dev/null 2>&1 || true

# ── Nginx proxy ────────────────────────────────────────────────────────────

ensure_hermes_proxy_include
write_hermes_proxy_route "$INSTANCE_ID" "$GATEWAY_PORT"

# ── Compose up ─────────────────────────────────────────────────────────────

# Unset host env vars that could shadow --env-file
unset OPENCLAW_GATEWAY_PORT OPENCLAW_BRIDGE_PORT OPENCLAW_GATEWAY_TOKEN OPENCLAW_GATEWAY_BIND 2>/dev/null || true

COMPOSE_ARGS=(-f "$PATCHED_COMPOSE" -p "$PROJECT" --env-file "$WORKDIR/.env")

compose_log="$(mktemp)"
if ! "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build >"$compose_log" 2>&1; then
  # Port conflict auto-heal
  if grep -qi 'failed to bind host port' "$compose_log"; then
    echo "WARN: bind port conflict detected, auto-allocating new ports" >&2
    for _ in $(seq 1 8); do
      GATEWAY_PORT=$((GATEWAY_PORT + 1))
      HTTP_PORT=$((HTTP_PORT + 1))
      sed -i "s/^GATEWAY_PORT=.*/GATEWAY_PORT=${GATEWAY_PORT}/" "$WORKDIR/.env"
      sed -i "s/^HTTP_PORT=.*/HTTP_PORT=${HTTP_PORT}/" "$WORKDIR/.env"
      # Regenerate compose with new ports
      sed -i "s/\"[0-9]*:8443\"/\"${GATEWAY_PORT}:8443\"/" "$PATCHED_COMPOSE"
      sed -i "s/\"[0-9]*:8080\"/\"${HTTP_PORT}:8080\"/" "$PATCHED_COMPOSE"
      write_hermes_proxy_route "$INSTANCE_ID" "$GATEWAY_PORT"
      if "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build >"$compose_log" 2>&1; then
        break
      fi
      if ! grep -qi 'failed to bind host port' "$compose_log"; then
        break
      fi
    done
  else
    cat "$compose_log" >&2 || true
    rm -f "$compose_log" >/dev/null 2>&1 || true
    exit 22
  fi
fi
rm -f "$compose_log" >/dev/null 2>&1 || true

# Apply resource limits
for _cid in $(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null); do
  docker update --memory 8g --cpus 4.0 --pids-limit 512 "$_cid" >/dev/null 2>&1 || true
done

# ── Health check ───────────────────────────────────────────────────────────

ok=0
for _ in $(seq 1 30); do
  if docker ps --filter "name=hermes_${INSTANCE_ID}" --format '{{.Status}}' 2>/dev/null | grep -qi 'up\|healthy'; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$ok" -ne 1 ]]; then
  echo "WARN: hermes container not ready yet, may need more time" >&2
fi

# ── Patch config.yaml with user's LLM settings ───────────────────────────────

if [[ -n "$_FINAL_API_KEY" || -n "$_FINAL_BASE_URL" || -n "$_FINAL_MODEL" ]]; then
  # Wait for entrypoint to create config.yaml
  for _ in $(seq 1 15); do
    [[ -f "$HERMES_DATA_DIR/config.yaml" ]] && break
    sleep 2
  done
  if [[ -f "$HERMES_DATA_DIR/config.yaml" ]]; then
    # Provider: use "auto" — Hermes auto-detects from base_url
    # Known providers: openrouter, gemini, anthropic, deepseek, kimi-coding, minimax, etc.
    _PROVIDER="auto"
    docker exec "hermes_${INSTANCE_ID}" python3 -c "
import yaml
from pathlib import Path
p = Path('/opt/data/config.yaml')
cfg = yaml.safe_load(p.read_text())
cfg.setdefault('model', {})
cfg['model']['default'] = '${_FINAL_MODEL}'
cfg['model']['provider'] = '${_PROVIDER}'
if '${_FINAL_BASE_URL}':
    cfg['model']['base_url'] = '${_FINAL_BASE_URL}'
p.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))
" 2>/dev/null || true
    # Restart to pick up new config
    docker restart "hermes_${INSTANCE_ID}" >/dev/null 2>&1 || true
  fi
fi

# ── Output machine-readable metadata ───────────────────────────────────────

printf 'COMPOSE_PROJECT=%s\n' "$PROJECT"
printf 'COMPOSE_FILE=%s\n' "$PATCHED_COMPOSE"
printf 'RUNTIME_DIR=%s\n' "$WORKDIR"
printf 'REPO_DIR=%s\n' "$REPO_DIR"
printf 'WEB_CONSOLE_PORT=%s\n' "$GATEWAY_PORT"
printf 'HTTP_PORT=%s\n' "$HTTP_PORT"
printf 'WEB_CONSOLE_URL=%s\n' "https://www.ucai.net/connect/hermes/${INSTANCE_ID}/"
