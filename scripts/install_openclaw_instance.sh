#!/usr/bin/env bash
set -euo pipefail
# OpenClaw-specific installer
# Covers: model config, Telegram, openclaw-hxa-connect plugin, org registration

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

# ── Nginx reverse proxy for OpenClaw gateway ─────────────────────────────────
NGINX_VHOST_CONF="/usr/local/nginx/conf/vhost/www.ucai.net.conf"
OPENCLAW_PROXY_DIR="/usr/local/nginx/conf/vhost/openclaw-instances"

ensure_openclaw_proxy_include() {
  mkdir -p "$OPENCLAW_PROXY_DIR"
  if [[ -f "$NGINX_VHOST_CONF" ]] && ! grep -q "openclaw-instances/\*.conf" "$NGINX_VHOST_CONF"; then
    sed -i '/# HXA-Connect/i\    include /usr/local/nginx/conf/vhost/openclaw-instances/*.conf;' "$NGINX_VHOST_CONF"
  fi
}

write_openclaw_proxy_route() {
  local id="$1"
  local port="$2"
  local conf="$OPENCLAW_PROXY_DIR/${id}.conf"
  cat > "$conf" <<EOF
location = /connect/openclaw/${id} {
    return 301 /connect/openclaw/${id}/;
}
location ^~ /connect/openclaw/${id}/ {
    proxy_pass http://127.0.0.1:${port}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;
    proxy_buffering off;
}
EOF
}

# ── Org / auth constants ──────────────────────────────────────────────────────
_HXA_HUB_URL="https://www.ucai.net/connect"
_HXA_ORG_ID="${HXA_CONNECT_ORG_ID:-123cd566-c2ea-409f-8f7e-4fa9f5296dd1}"
_HXA_ORG_SECRET="${HXA_CONNECT_ORG_SECRET:-${ORG_SECRET:-}}"
# ANTHROPIC_AUTH_TOKEN  = Bearer token for sub2api gateway (what openclaw sends as apiKey to 172.17.0.1:18080)
# ANTHROPIC_BASE_URL    = URL of sub2api gateway inside Docker network
# ANTHROPIC_API_KEY     = NOT USED — real sk-ant-api* key is not required when routing through sub2api
_ANTHROPIC_BASE="http://172.17.0.1:18080"  # Always use Docker-accessible address, never localhost
_ANTHROPIC_TOKEN="${ANTHROPIC_AUTH_TOKEN:-}"
_DEFAULT_MODEL="${OPENCLAW_MODEL:-claude-sonnet-4-5}"
_TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_ENABLED="false"
[[ -n "$_TG_TOKEN" ]] && TG_ENABLED="true"

mkdir -p "$WORKDIR"

# ── Clone / update repo ───────────────────────────────────────────────────────
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

# ── Per-instance config / workspace dirs ─────────────────────────────────────
CONFIG_DIR="$WORKDIR/openclaw-config"
WORKSPACE_DIR="$WORKDIR/openclaw-workspace"
EXTENSIONS_DIR="$CONFIG_DIR/extensions"
mkdir -p "$CONFIG_DIR" "$WORKSPACE_DIR" "$EXTENSIONS_DIR"
mkdir -p "$CONFIG_DIR/identity" "$CONFIG_DIR/agents/main/agent" "$CONFIG_DIR/agents/main/sessions"

# ── Port allocation ───────────────────────────────────────────────────────────
HASH=$(echo -n "$INSTANCE_ID" | cksum | awk '{print $1}')
OPENCLAW_GATEWAY_PORT=$((37000 + HASH % 1000))
OPENCLAW_BRIDGE_PORT=$((38000 + HASH % 1000))

port_in_use() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "(^|:)$1$"; }
while port_in_use "$OPENCLAW_GATEWAY_PORT"; do OPENCLAW_GATEWAY_PORT=$((OPENCLAW_GATEWAY_PORT+1)); done
while port_in_use "$OPENCLAW_BRIDGE_PORT"; do OPENCLAW_BRIDGE_PORT=$((OPENCLAW_BRIDGE_PORT+1)); done

# ── Gateway token ─────────────────────────────────────────────────────────────
OPENCLAW_GATEWAY_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)

# ── Agent name ────────────────────────────────────────────────────────────────
AGENT_NAME_BASE="${AGENT_NAME_BASE:-Michael_Wu}"
AGENT_NAME_BASE="${AGENT_NAME_BASE// /_}"
AGENT_NAME_SUFFIX="$(tr -dc 'a-z0-9' </dev/urandom | head -c 4 || date +%s | tail -c 4)"
HXA_AGENT_NAME="${HXA_CONNECT_AGENT_NAME:-${AGENT_NAME_BASE}_${AGENT_NAME_SUFFIX}}"

# ── Pre-write openclaw.json (non-interactive config bootstrap) ────────────────
OPENCLAW_JSON="$CONFIG_DIR/openclaw.json"
cat > "$OPENCLAW_JSON" <<OCJSON
{
  "models": {
    "mode": "merge",
    "providers": {
      "anthropic": {
        "baseUrl": "$_ANTHROPIC_BASE",
        "apiKey": "$_ANTHROPIC_TOKEN",
        "api": "anthropic-messages",
        "models": [
          {
            "id": "claude-sonnet-4-5",
            "name": "Claude Sonnet 4.5 (via sub2api)",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 200000,
            "maxTokens": 16000
          }
        ]
      }
    }
  },
  "channels": {
    "telegram": {
      "enabled": ${TG_ENABLED},
      "botToken": "$_TG_TOKEN",
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "groups": {
        "*": { "requireMention": false }
      }
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5",
      "compaction": { "mode": "safeguard" }
    }
  },
  "gateway": {
    "mode": "local",
    "bind": "lan",
    "auth": { "token": "$OPENCLAW_GATEWAY_TOKEN" },
    "trustedProxies": ["loopback", "uniquelocal"]
  }
}
OCJSON
# Notes:
# - models.providers.anthropic.apiKey = ANTHROPIC_AUTH_TOKEN (sub2api bearer, NOT real sk-ant-api* key)
# - models.providers.anthropic.api = "anthropic-messages" (required by custom provider schema)
# - channels.telegram uses botToken (not token), requires allowFrom:[*] when dmPolicy=open
# - "enabled", "default" are NOT valid top-level openclaw.json keys
chmod 600 "$OPENCLAW_JSON"

# Fix ownership so container's node user (uid 1000) can read/write config.
# Must run before compose up. Tolerates image not yet pulled (skips if it fails).
_OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}"
docker run --rm \
  -v "$CONFIG_DIR:/home/node/.openclaw" \
  --user root \
  --entrypoint sh \
  "$_OPENCLAW_IMAGE" \
  -c 'chown -R 1000:1000 /home/node/.openclaw && echo owner_ok' 2>/dev/null || true

# ── .env for compose ──────────────────────────────────────────────────────────
cat > "$WORKDIR/.env" <<EOF
OPENCLAW_IMAGE=${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}
OPENCLAW_CONFIG_DIR=$CONFIG_DIR
OPENCLAW_WORKSPACE_DIR=$WORKSPACE_DIR
OPENCLAW_GATEWAY_PORT=$OPENCLAW_GATEWAY_PORT
OPENCLAW_BRIDGE_PORT=$OPENCLAW_BRIDGE_PORT
OPENCLAW_GATEWAY_BIND=lan
OPENCLAW_GATEWAY_TOKEN=$OPENCLAW_GATEWAY_TOKEN

ANTHROPIC_BASE_URL=$_ANTHROPIC_BASE
ANTHROPIC_AUTH_TOKEN=$_ANTHROPIC_TOKEN
# ANTHROPIC_API_KEY intentionally omitted — apiKey in openclaw.json = ANTHROPIC_AUTH_TOKEN (sub2api Bearer)

TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_ENABLE_GROUPS=${TELEGRAM_ENABLE_GROUPS:-true}
TELEGRAM_ENABLE_DMS=${TELEGRAM_ENABLE_DMS:-true}

HXA_CONNECT_URL=$_HXA_HUB_URL
HXA_CONNECT_ORG_ID=$_HXA_ORG_ID
HXA_CONNECT_ORG_SECRET=${_HXA_ORG_SECRET}
HXA_CONNECT_AGENT_NAME=$HXA_AGENT_NAME
EOF
chmod 600 "$WORKDIR/.env" >/dev/null 2>&1 || true

# ── Reverse proxy route (same pattern as Zylos) ──────────────────────────────
ensure_openclaw_proxy_include
write_openclaw_proxy_route "$INSTANCE_ID" "$OPENCLAW_GATEWAY_PORT"
# Reload nginx to pick up the new route
nginx -t >/dev/null 2>&1 && nginx -s reload >/dev/null 2>&1 || true

# ── Clone openclaw-hxa-connect plugin into extensions ─────────────────────────
PLUGIN_DIR="$EXTENSIONS_DIR/hxa-connect"
if [[ -d "$PLUGIN_DIR/.git" ]]; then
  git -C "$PLUGIN_DIR" fetch --all --prune
  git -C "$PLUGIN_DIR" reset --hard origin/HEAD || git -C "$PLUGIN_DIR" pull --ff-only
else
  rm -rf "$PLUGIN_DIR"
  git clone --depth 1 https://github.com/coco-xyz/openclaw-hxa-connect.git "$PLUGIN_DIR"
fi
# npm install inside plugin dir (on host node if available, otherwise do it via container later)
if command -v npm >/dev/null 2>&1; then
  npm --prefix "$PLUGIN_DIR" install --silent 2>/dev/null || true
fi

# ── Start compose ─────────────────────────────────────────────────────────────
# Values already computed above; just unset host-inherited vars then re-set with our values.
# (Do NOT rely on previously exported vars after unset — reassign explicitly.)
_GW_PORT="$OPENCLAW_GATEWAY_PORT"
_BR_PORT="$OPENCLAW_BRIDGE_PORT"
_GW_TOKEN="$OPENCLAW_GATEWAY_TOKEN"
unset OPENCLAW_GATEWAY_PORT OPENCLAW_BRIDGE_PORT OPENCLAW_GATEWAY_TOKEN OPENCLAW_GATEWAY_BIND
unset WEB_CONSOLE_PORT HTTP_PORT
OPENCLAW_GATEWAY_PORT="$_GW_PORT"
OPENCLAW_BRIDGE_PORT="$_BR_PORT"
OPENCLAW_GATEWAY_TOKEN="$_GW_TOKEN"
export OPENCLAW_GATEWAY_PORT OPENCLAW_BRIDGE_PORT OPENCLAW_GATEWAY_TOKEN

COMPOSE_ARGS=(-f "$COMPOSE_FILE" -p "$PROJECT" --env-file "$WORKDIR/.env")
compose_log="$(mktemp)"
if ! "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d >"$compose_log" 2>&1; then
  cat "$compose_log" >&2 || true
  rm -f "$compose_log"
  exit 22
fi
rm -f "$compose_log"

# ── Wait for gateway to start ─────────────────────────────────────────────────
CONTAINER_GATEWAY="${PROJECT}-openclaw-gateway-1"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/healthz" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 3
done
if [[ "$ok" -ne 1 ]]; then
  echo "WARN: OpenClaw gateway not reachable on port $OPENCLAW_GATEWAY_PORT after 90s" >&2
  docker logs --tail 30 "$CONTAINER_GATEWAY" >&2 || true
fi

CONTAINER_CLI="${PROJECT}-openclaw-cli-1"

# ── Fix ownership post-start (workspace mounted separately, may be root-owned) ──
# OpenClaw writes AGENTS.md etc on first run; node user (uid 1000) must own them
docker exec --user root "$CONTAINER_GATEWAY" sh -c 'chown -R node:node /home/node/.openclaw' 2>/dev/null || true

# ── npm install plugin inside container (in case host npm wasn't available) ──
docker exec "$CONTAINER_CLI" sh -lc '[ -d /home/node/.openclaw/extensions/hxa-connect ] && cd /home/node/.openclaw/extensions/hxa-connect && npm install --silent 2>/dev/null || true' 2>/dev/null || true

# ── Telegram channel ──────────────────────────────────────────────────────────
TG_TOKEN_VAL="${TELEGRAM_BOT_TOKEN:-}"
if [[ -n "$TG_TOKEN_VAL" ]]; then
  docker exec "$CONTAINER_CLI" sh -lc \
    "node dist/index.js channels add --channel telegram --token '$TG_TOKEN_VAL' --yes 2>/dev/null || true" || true
fi

# ── Register with HXA org and inject plugin config ───────────────────────────
if [[ -n "$_HXA_ORG_SECRET" ]]; then
  docker exec "$CONTAINER_CLI" node -e "
(async () => {
  const sdk = await import('/home/node/.openclaw/extensions/hxa-connect/node_modules/@coco-xyz/hxa-connect-sdk/dist/index.js').catch(() => null);
  if (!sdk) { console.log('SDK not found, skipping org registration'); return; }
  const { HxaConnectClient } = sdk;
  const hub = '$_HXA_HUB_URL';
  const orgId = '$_HXA_ORG_ID';
  const secret = '$_HXA_ORG_SECRET';
  const agentName = '$HXA_AGENT_NAME';
  try {
    // Register as member role (user-created instances should not be org admins)
    const reg = await HxaConnectClient.register(hub, orgId, { org_secret: secret }, agentName, { role: 'member' });
    // API returns: { token, id, bot_id, name, ... }
    const token = reg.token || reg.agent_token || reg.bot_token;
    const agentId = reg.id || reg.bot_id || reg.agent_id;
    if (!token) { console.error('HXA registration: no token in response', JSON.stringify(reg)); return; }
    const fs = require('fs');
    const configPath = '/home/node/.openclaw/openclaw.json';
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(configPath, 'utf8')); } catch {}
    if (!cfg.channels) cfg.channels = {};
    cfg.channels['hxa-connect'] = {
      enabled: true, hubUrl: hub, agentToken: token, agentName: agentName, orgId: orgId,
      access: { dmPolicy: 'open', groupPolicy: 'open', threads: {} }
    };
    if (!cfg.plugins) cfg.plugins = {};
    if (!cfg.plugins.entries) cfg.plugins.entries = {};
    cfg.plugins.entries['hxa-connect'] = { enabled: true };
    fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2) + '\n');
    console.log('HXA org registration ok, agent:', agentName);
  } catch (e) { console.error('HXA registration error:', e.message); }
})();
" 2>/dev/null || true

  # Restart gateway to apply new config
  "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" restart openclaw-gateway 2>/dev/null || true
fi

# ── Output ────────────────────────────────────────────────────────────────────
printf 'COMPOSE_PROJECT=%s\n' "$PROJECT"
printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE"
printf 'RUNTIME_DIR=%s\n' "$WORKDIR"
printf 'REPO_DIR=%s\n' "$REPO_DIR"
printf 'WEB_CONSOLE_PORT=%s\n' "$OPENCLAW_GATEWAY_PORT"
printf 'HTTP_PORT=%s\n' "$OPENCLAW_BRIDGE_PORT"
printf 'WEB_CONSOLE_URL=%s\n' "https://www.ucai.net/connect/openclaw/${INSTANCE_ID}/"
printf 'HXA_AGENT_NAME=%s\n' "$HXA_AGENT_NAME"
