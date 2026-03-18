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

NGINX_VHOST_CONF="/usr/local/nginx/conf/vhost/www.ucai.net.conf"
ZYLOS_PROXY_DIR="/usr/local/nginx/conf/vhost/zylos-instances"

ensure_zylos_proxy_include() {
  mkdir -p "$ZYLOS_PROXY_DIR"
  if [[ -f "$NGINX_VHOST_CONF" ]] && ! grep -q "zylos-instances/\*.conf" "$NGINX_VHOST_CONF"; then
    # Insert include before generic /connect location so specific zylos routes are available.
    sed -i '/# HXA-Connect/i\    include /usr/local/nginx/conf/vhost/zylos-instances/*.conf;' "$NGINX_VHOST_CONF"
  fi
}

write_zylos_proxy_route() {
  local id="$1"
  local port="$2"
  local conf="$ZYLOS_PROXY_DIR/${id}.conf"
  cat > "$conf" <<EOF
location = /connect/zylos/${id} {
    return 301 /connect/zylos/${id}/;
}
location ^~ /connect/zylos/${id}/ {
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

patch_zylos_web_console_basepath() {
  local app_js="$1/.claude/skills/web-console/public/app.js"
  # web-console assets may appear a bit later after first boot; wait briefly.
  for _ in $(seq 1 30); do
    [[ -f "$app_js" ]] && break
    sleep 2
  done
  [[ -f "$app_js" ]] || return 0
  APP_JS="$app_js" python3 - <<'PY'
from pathlib import Path
import os, re
p = Path(os.environ['APP_JS'])
text = p.read_text()

# 1) Robustly patch detectBasePath()
new_detect = '''  detectBasePath() {
    const path = window.location.pathname;

    // /console -> /console
    if (path.startsWith('/console')) {
      return '/console';
    }

    // /connect/zylos/<instance_id>/... -> /connect/zylos/<instance_id>
    const m = path.match(/^\/(connect\/zylos\/[^/]+)/);
    if (m) {
      return `/${m[1]}`;
    }

    return '';
  }
'''
text = re.sub(r"\n\s*detectBasePath\(\) \{[\s\S]*?\n\s*\}\n", "\n" + new_detect, text, count=1)

# 2) Robustly patch auth-guard basePath computation
text = re.sub(
    r"const basePath = window\.location\.pathname\.startsWith\('/console'\) \? '/console' : '';",
    "const m = window.location.pathname.match(/^\\/(connect\\/zylos\\/[^/]+)/);\n  const basePath = window.location.pathname.startsWith('/console') ? '/console' : (m ? `/${m[1]}` : '');",
    text,
    count=1,
)

p.write_text(text)
print('patched', p)
PY
}

patch_zylos_c4_health_gate() {
  local receive_js="$1/.claude/skills/comm-bridge/scripts/c4-receive.js"
  local dispatcher_js="$1/.claude/skills/comm-bridge/scripts/c4-dispatcher.js"

  if [[ -f "$receive_js" ]]; then
    RECEIVE_JS="$receive_js" python3 - <<'PY'
from pathlib import Path
import os
p = Path(os.environ['RECEIVE_JS'])
text = p.read_text()
old = "if (status.health !== 'ok') {"
new = "if (status.health !== 'ok' && status.state !== 'idle' && status.state !== 'busy') {"
if old in text:
    text = text.replace(old, new, 1)
    p.write_text(text)
    print('patched', p)
else:
    print('skip', p)
PY
  fi

  if [[ -f "$dispatcher_js" ]]; then
    DISPATCHER_JS="$dispatcher_js" python3 - <<'PY'
from pathlib import Path
import os
p = Path(os.environ['DISPATCHER_JS'])
text = p.read_text()
old = "if (agentState.health !== 'ok' && !bypass) {"
new = "if (agentState.health !== 'ok' && (agentState.state === 'offline' || agentState.state === 'stopped') && !bypass) {"
if old in text:
    text = text.replace(old, new, 1)
    p.write_text(text)
    print('patched', p)
else:
    print('skip', p)
PY
  fi
}

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
WEB_CONSOLE_PORT=""
HTTP_PORT=""

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

if [[ "$PRODUCT" == "zylos" ]]; then
  HASH=$(echo -n "$INSTANCE_ID" | cksum | awk '{print $1}')
  WEB_CONSOLE_PORT=$(find_free_port $((34000 + HASH % 1000)))
  HTTP_PORT=$(find_free_port $((35000 + HASH % 1000)))

  AGENT_NAME_BASE="${AGENT_NAME_BASE:-Michael_Wu}"
  AGENT_NAME_BASE="${AGENT_NAME_BASE// /_}"
  AGENT_NAME_SUFFIX="$(tr -dc 'a-z0-9' </dev/urandom | head -c 4 || true)"
  if [[ -z "$AGENT_NAME_SUFFIX" ]]; then
    AGENT_NAME_SUFFIX="$(date +%s | tail -c 5)"
  fi
  HXA_CONNECT_AGENT_NAME_DEFAULT="${AGENT_NAME_BASE}_${AGENT_NAME_SUFFIX}"

  INSTANCE_DATA_DIR="$WORKDIR/zylos-data"
  INSTANCE_CLAUDE_DIR="$WORKDIR/claude-config"
  mkdir -p "$INSTANCE_DATA_DIR" "$INSTANCE_CLAUDE_DIR"
  # zylos container runs as non-root; ensure mounted dirs are writable to avoid init/pm2 failures
  chown -R 1001:1001 "$INSTANCE_DATA_DIR" "$INSTANCE_CLAUDE_DIR" >/dev/null 2>&1 || true
  chmod -R u+rwX,g+rwX,o-rwx "$INSTANCE_DATA_DIR" "$INSTANCE_CLAUDE_DIR" >/dev/null 2>&1 || true

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

# Ensure default auth + model are injected for every new zylos instance
if "ANTHROPIC_BASE_URL:" not in text:
    anchor = "      CLAUDE_BYPASS_PERMISSIONS: ${CLAUDE_BYPASS_PERMISSIONS:-true}"
    insert = anchor + "\n      ANTHROPIC_BASE_URL: \"http://172.17.0.1:18080\"\n      ANTHROPIC_AUTH_TOKEN: \"${ANTHROPIC_AUTH_TOKEN:-}\"\n      OPENAI_API_KEY: \"${OPENAI_API_KEY:-${CODEX_API_KEY:-}}\"\n      CODEX_API_KEY: \"${CODEX_API_KEY:-${OPENAI_API_KEY:-}}\"\n      ANTHROPIC_MODEL: \"claude-sonnet-4-5\""
    text = text.replace(anchor, insert)

out.write_text(text)
PY

  # Also write per-instance env file as a hard fallback for compose var resolution
  cat > "$WORKDIR/.env" <<EOF
ANTHROPIC_BASE_URL=http://172.17.0.1:18080
ANTHROPIC_AUTH_TOKEN=${ANTHROPIC_AUTH_TOKEN:-}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-sk-ant-proxy-via-sub2api}
CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN:-}
OPENAI_API_KEY=${OPENAI_API_KEY:-${CODEX_API_KEY:-}}
CODEX_API_KEY=${CODEX_API_KEY:-${OPENAI_API_KEY:-}}
ANTHROPIC_MODEL=claude-sonnet-4-5
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_ENABLE_GROUPS=${TELEGRAM_ENABLE_GROUPS:-true}
TELEGRAM_ENABLE_DMS=${TELEGRAM_ENABLE_DMS:-true}
WEB_CONSOLE_PORT=$WEB_CONSOLE_PORT
HTTP_PORT=$HTTP_PORT
HXA_CONNECT_URL=${HXA_CONNECT_URL:-${HUB_URL:-}}
HXA_CONNECT_ORG_ID=${HXA_CONNECT_ORG_ID:-${ORG_ID:-}}
HXA_CONNECT_ORG_TICKET=${HXA_CONNECT_ORG_TICKET:-${ORG_TOKEN:-}}
HXA_CONNECT_AGENT_NAME=${HXA_CONNECT_AGENT_NAME:-$HXA_CONNECT_AGENT_NAME_DEFAULT}
EOF
  chmod 600 "$WORKDIR/.env" >/dev/null 2>&1 || true

  COMPOSE_FILE="$PATCHED_COMPOSE"
  export WEB_CONSOLE_PORT HTTP_PORT INSTANCE_DATA_DIR INSTANCE_CLAUDE_DIR

  # Public reverse proxy path: https://www.ucai.net/connect/zylos/<instance_id>/
  ensure_zylos_proxy_include
  write_zylos_proxy_route "$INSTANCE_ID" "$WEB_CONSOLE_PORT"
fi

# Purge host-inherited port vars that would shadow --env-file values for docker compose
unset OPENCLAW_GATEWAY_PORT OPENCLAW_BRIDGE_PORT OPENCLAW_GATEWAY_TOKEN OPENCLAW_GATEWAY_BIND
# Re-export per-instance values computed above (zylos uses WEB_CONSOLE_PORT/HTTP_PORT)
export WEB_CONSOLE_PORT HTTP_PORT

COMPOSE_ARGS=(-f "$COMPOSE_FILE" -p "$PROJECT")
if [[ "$PRODUCT" == "zylos" ]]; then
  COMPOSE_ARGS+=(--env-file "$WORKDIR/.env")
fi

# First attempt (with zylos bind-conflict auto-heal)
compose_log="$(mktemp)"
if ! "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build >"$compose_log" 2>&1; then
  if [[ "$PRODUCT" == "zylos" ]] && grep -qi 'failed to bind host port' "$compose_log"; then
    echo "WARN: bind port conflict detected, auto-allocating new ports" >&2
    for _ in $(seq 1 8); do
      WEB_CONSOLE_PORT=$((WEB_CONSOLE_PORT + 1))
      HTTP_PORT=$((HTTP_PORT + 1))
      sed -i "s/^WEB_CONSOLE_PORT=.*/WEB_CONSOLE_PORT=${WEB_CONSOLE_PORT}/" "$WORKDIR/.env"
      sed -i "s/^HTTP_PORT=.*/HTTP_PORT=${HTTP_PORT}/" "$WORKDIR/.env"
      write_zylos_proxy_route "$INSTANCE_ID" "$WEB_CONSOLE_PORT"
      if "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build >"$compose_log" 2>&1; then
        break
      fi
      if ! grep -qi 'failed to bind host port' "$compose_log"; then
        break
      fi
    done
  elif [[ "$PRODUCT" == "zylos" ]] && docker ps -a --format '{{.Names}}' | grep -qx 'zylos'; then
    # legacy cleanup path for old upstream hardcoded zylos container name
    echo "WARN: retry after removing conflicting legacy 'zylos' container" >&2
    docker rm -f zylos >/dev/null 2>&1 || true
    "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build >"$compose_log" 2>&1
  else
    cat "$compose_log" >&2 || true
    rm -f "$compose_log" >/dev/null 2>&1 || true
    exit 22
  fi
fi
rm -f "$compose_log" >/dev/null 2>&1 || true

if [[ "$PRODUCT" == "zylos" ]]; then
  # zylos can show container=Up while app ports are still dead; verify runtime endpoints are reachable.
  ok=0
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:${WEB_CONSOLE_PORT}" >/dev/null 2>&1 \
      || curl -fsS --max-time 2 "http://127.0.0.1:${HTTP_PORT}" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 2
  done

  if [[ "$ok" -ne 1 ]]; then
    echo "WARN: zylos ports not ready; attempting one self-heal restart" >&2
    "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" down >/dev/null 2>&1 || true
    "${COMPOSE[@]}" "${COMPOSE_ARGS[@]}" up -d --build

    for _ in $(seq 1 30); do
      if curl -fsS --max-time 2 "http://127.0.0.1:${WEB_CONSOLE_PORT}" >/dev/null 2>&1 \
        || curl -fsS --max-time 2 "http://127.0.0.1:${HTTP_PORT}" >/dev/null 2>&1; then
        ok=1
        break
      fi
      sleep 2
    done
  fi

  if [[ "$ok" -ne 1 ]]; then
    echo "ERROR: zylos container is up but app endpoints are unreachable (web:${WEB_CONSOLE_PORT}, http:${HTTP_PORT})" >&2
    docker logs --tail 120 "zylos_${INSTANCE_ID}" >&2 || true
    exit 23
  fi

  # Patch web console base-path handling so /connect/zylos/<id>/ keeps API/WS prefix.
  patch_zylos_web_console_basepath "$INSTANCE_DATA_DIR"
  # Also patch repo template to survive future self-heal restarts/re-inits.
  if [[ -f "$REPO_DIR/skills/web-console/public/app.js" ]]; then
    APP_JS="$REPO_DIR/skills/web-console/public/app.js" python3 - <<'PY'
from pathlib import Path
import os, re
p = Path(os.environ['APP_JS'])
text = p.read_text()
text = re.sub(r"\n\s*detectBasePath\(\) \{[\s\S]*?\n\s*\}\n", '''
  detectBasePath() {
    const path = window.location.pathname;
    if (path.startsWith('/console')) return '/console';
    const m = path.match(/^\/(connect\/zylos\/[^/]+)/);
    return m ? `/${m[1]}` : '';
  }
''', text, count=1)
text = re.sub(r"const basePath = window\.location\.pathname\.startsWith\('/console'\) \? '/console' : '';",
              "const m = window.location.pathname.match(/^\\/(connect\\/zylos\\/[^/]+)/);\n  const basePath = window.location.pathname.startsWith('/console') ? '/console' : (m ? `/${m[1]}` : '');",
              text, count=1)
p.write_text(text)
print('patched', p)
PY
  fi
  # Relax false-negative health gate for comm-bridge when agent is actually idle/busy.
  patch_zylos_c4_health_gate "$INSTANCE_DATA_DIR"

  # Optional auto-bootstrap for hxa-connect (when org vars are provided)
  HXA_URL_VAL="$(grep '^HXA_CONNECT_URL=' "$WORKDIR/.env" | cut -d= -f2- || true)"
  HXA_ORG_VAL="$(grep '^HXA_CONNECT_ORG_ID=' "$WORKDIR/.env" | cut -d= -f2- || true)"
  HXA_TICKET_VAL="$(grep '^HXA_CONNECT_ORG_TICKET=' "$WORKDIR/.env" | cut -d= -f2- || true)"
  HXA_AGENT_VAL="$(grep '^HXA_CONNECT_AGENT_NAME=' "$WORKDIR/.env" | cut -d= -f2- || true)"
  if [[ -n "$HXA_URL_VAL" && -n "$HXA_ORG_VAL" && -n "$HXA_TICKET_VAL" && -n "$HXA_AGENT_VAL" ]]; then
    docker exec "zylos_${INSTANCE_ID}" sh -lc '/home/zylos/.npm-global/bin/zylos add hxa-connect --yes >/tmp/hxa_add_auto.log 2>&1 || true' || true
    docker exec "zylos_${INSTANCE_ID}" sh -lc "HUB='$HXA_URL_VAL' ORG='$HXA_ORG_VAL' TICKET='$HXA_TICKET_VAL' AGENT='$HXA_AGENT_VAL' node - <<'JS'
const fs=require('fs'); const path=require('path');
(async()=>{
  const { HxaConnectClient } = await import('/home/zylos/zylos/.claude/skills/hxa-connect/node_modules/@coco-xyz/hxa-connect-sdk/dist/index.js');
  const hub = process.env.HUB; const org = process.env.ORG; const ticket = process.env.TICKET; const name = process.env.AGENT;
  const reg = await HxaConnectClient.register(hub, org, { org_secret: ticket }, name);
  const token = reg.token || reg.agent_token; const agentId = reg.agent_id || reg.id;
  const cfg={default_hub_url:hub,orgs:{default:{org_id:org,agent_id:agentId,agent_token:token,agent_name:name,hub_url:null,access:{dmPolicy:'open',groupPolicy:'open',threadMode:'mention'}}}};
  const cfgPath='/home/zylos/zylos/components/hxa-connect/config.json';
  fs.mkdirSync(path.dirname(cfgPath),{recursive:true}); fs.writeFileSync(cfgPath, JSON.stringify(cfg,null,2)+'\\n');
})();
JS" || true
    docker exec "zylos_${INSTANCE_ID}" sh -lc 'pm2 restart zylos-hxa-connect >/dev/null 2>&1 || true' || true
  fi

  # Optional auto-bootstrap for telegram (when bot token is provided)
  TG_TOKEN_VAL="$(grep '^TELEGRAM_BOT_TOKEN=' "$WORKDIR/.env" | cut -d= -f2- || true)"
  if [[ -n "$TG_TOKEN_VAL" ]]; then
    docker exec "zylos_${INSTANCE_ID}" sh -lc '/home/zylos/.npm-global/bin/zylos add telegram --yes >/tmp/tg_add_auto.log 2>&1 || true' || true
    docker exec "zylos_${INSTANCE_ID}" sh -lc "TG='$TG_TOKEN_VAL'; ENVF=/home/zylos/zylos/.env; touch \"\$ENVF\"; sed -i '/^TELEGRAM_BOT_TOKEN=/d;/^TELEGRAM_ENABLE_GROUPS=/d;/^TELEGRAM_ENABLE_DMS=/d' \"\$ENVF\"; printf '%s\\n' \"TELEGRAM_BOT_TOKEN=\$TG\" 'TELEGRAM_ENABLE_GROUPS=true' 'TELEGRAM_ENABLE_DMS=true' >> \"\$ENVF\"" || true
    docker exec "zylos_${INSTANCE_ID}" sh -lc '[ -f /home/zylos/zylos/.claude/skills/telegram/hooks/post-install.js ] && node /home/zylos/zylos/.claude/skills/telegram/hooks/post-install.js || true' || true
    docker exec "zylos_${INSTANCE_ID}" sh -lc 'pm2 restart zylos-telegram >/dev/null 2>&1 || pm2 start /home/zylos/zylos/.claude/skills/telegram/ecosystem.config.cjs >/dev/null 2>&1 || true' || true
  fi
fi

# machine-readable output for caller
printf 'COMPOSE_PROJECT=%s\n' "$PROJECT"
printf 'COMPOSE_FILE=%s\n' "$COMPOSE_FILE"
printf 'RUNTIME_DIR=%s\n' "$WORKDIR"
printf 'REPO_DIR=%s\n' "$REPO_DIR"
printf 'WEB_CONSOLE_PORT=%s\n' "$WEB_CONSOLE_PORT"
printf 'HTTP_PORT=%s\n' "$HTTP_PORT"
if [[ "$PRODUCT" == "zylos" ]]; then
  printf 'WEB_CONSOLE_URL=%s\n' "https://www.ucai.net/connect/zylos/${INSTANCE_ID}/"
fi
