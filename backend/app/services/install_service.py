from __future__ import annotations

import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..database import get_connection

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")

_HUB_URL = "https://www.ucai.net/connect"
_ORG_ID = "123cd566-c2ea-409f-8f7e-4fa9f5296dd1"
_ORG_SECRET = os.getenv("HXA_CONNECT_ORG_SECRET") or os.getenv("ORG_SECRET") or ""
_AGENT_PREFIX = os.getenv("HXA_CONNECT_AGENT_PREFIX", "hire")
_PLUGIN_MAP = {
    "zylos": "hxa-connect",
    "openclaw": "openclaw-hxa-connect",
}
COMPOSE_CANDIDATES = [
    "docker-compose.yml",
    "compose.yml",
    "docker/docker-compose.yml",
    "docker/compose.yml",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_gateway_env_var(key: str) -> str:
    """Best-effort read of env vars from openclaw gateway user service file."""
    try:
        svc = Path('/root/.config/systemd/user/openclaw-gateway.service')
        if not svc.exists():
            return ''
        text = svc.read_text()
        m = re.search(rf'^Environment={re.escape(key)}=(.*)$', text, flags=re.M)
        return (m.group(1).strip() if m else '')
    except Exception:
        return ''


def _normalize_anthropic_api_key(current: str, token: str) -> str:
    current = (current or "").strip()
    token = (token or "").strip()
    if current.startswith("sk-ant-"):
        return current
    if token.startswith("sk-ant-"):
        return token
    return "sk-ant-proxy-via-sub2api"


def _ensure_auth_env() -> None:
    """Ensure installer subprocess inherits usable provider credentials.

    Only ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL are propagated.
    ANTHROPIC_API_KEY is intentionally NOT set here — the openclaw-hxa-connect
    and openclaw installers use ANTHROPIC_AUTH_TOKEN as the sub2api bearer token
    (passed as 'apiKey' in openclaw.json). They are different concepts.
    """
    token = os.getenv('ANTHROPIC_AUTH_TOKEN', '').strip() or _read_gateway_env_var('ANTHROPIC_AUTH_TOKEN')
    if token and not os.getenv('ANTHROPIC_AUTH_TOKEN'):
        os.environ['ANTHROPIC_AUTH_TOKEN'] = token
    # Explicitly do NOT set ANTHROPIC_API_KEY from ANTHROPIC_AUTH_TOKEN here.


def _set_instance_state(instance_id: str, state: str, status: str | None = None) -> None:
    with get_connection() as conn:
        if status is None:
            conn.execute(
                "UPDATE instances SET install_state = ?, updated_at = ? WHERE id = ?",
                (state, _utc_now(), instance_id),
            )
        else:
            conn.execute(
                "UPDATE instances SET install_state = ?, status = ?, updated_at = ? WHERE id = ?",
                (state, status, _utc_now(), instance_id),
            )
        conn.commit()


def _add_install_event(instance_id: str, state: str, message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO install_events (instance_id, state, message, created_at) VALUES (?, ?, ?, ?)",
            (instance_id, state, message, _utc_now()),
        )
        conn.commit()


_SAFE_ENV = {k: v for k, v in os.environ.items() if k not in (
    # Purge host openclaw/zylos port vars that would shadow --env-file values
    "OPENCLAW_GATEWAY_PORT", "OPENCLAW_BRIDGE_PORT",
    "OPENCLAW_GATEWAY_TOKEN", "OPENCLAW_GATEWAY_BIND",
    "WEB_CONSOLE_PORT", "HTTP_PORT",
)}


def _run(cmd: list[str], cwd: Path | None = None, clean_env: bool = False) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=_SAFE_ENV if clean_env else None,
        )
        out = (proc.stdout or "").strip()
        return proc.returncode, out
    except FileNotFoundError as exc:
        return 127, str(exc)


def _env_file_for(runtime_dir: str | None) -> list[str]:
    """Return --env-file arg list if a .env exists in the runtime dir."""
    if not runtime_dir:
        return []
    env_path = Path(runtime_dir) / ".env"
    return ["--env-file", str(env_path)] if env_path.exists() else []


def _compose_up(compose_file: Path, project: str, workdir: Path, runtime_dir: str | None = None) -> tuple[int, str]:
    env_args = _env_file_for(runtime_dir or str(workdir))
    rc, out = _run(["docker", "compose", "-f", str(compose_file), "-p", project] + env_args + ["up", "-d", "--build"], cwd=workdir, clean_env=True)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", str(compose_file), "-p", project] + env_args + ["up", "-d", "--build"], cwd=workdir, clean_env=True)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose failed:\n{out}\n\ndocker-compose failed:\n{out2}"


def _compose_control(compose_file: str, project: str, workdir: str, action: str) -> tuple[int, str]:
    wd = Path(workdir)
    env_args = _env_file_for(workdir)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project] + env_args + [action], cwd=wd, clean_env=True)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", compose_file, "-p", project] + env_args + [action], cwd=wd, clean_env=True)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose {action} failed:\n{out}\n\ndocker-compose {action} failed:\n{out2}"


def compose_logs(compose_file: str, project: str, workdir: str, lines: int = 200) -> tuple[int, str]:
    wd = Path(workdir)
    env_args = _env_file_for(workdir)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project] + env_args + ["logs", "--tail", str(lines)], cwd=wd)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", compose_file, "-p", project] + env_args + ["logs", "--tail", str(lines)], cwd=wd)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose logs failed:\n{out}\n\ndocker-compose logs failed:\n{out2}"


def _find_compose_file(repo_dir: Path) -> Path | None:
    for rel in COMPOSE_CANDIDATES:
        p = repo_dir / rel
        if p.exists():
            return p
    return None


def _sync_runtime_status(instance_id: str, project: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT install_state FROM instances WHERE id = ?", (instance_id,)).fetchone()
    current_state = row["install_state"] if row else None

    rc, out = _run([
        "docker",
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--format",
        "{{.Status}}",
    ])
    if rc != 0:
        if current_state != "failed":
            _add_install_event(instance_id, "failed", f"Unable to query docker status: {out[:400]}")
        _set_instance_state(instance_id, "failed", status="failed")
        return

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        if current_state != "failed":
            _add_install_event(instance_id, "failed", "No containers found after compose up.")
        _set_instance_state(instance_id, "failed", status="failed")
        return

    if any("Up" in ln for ln in lines):
        if current_state != "running":
            _add_install_event(instance_id, "running", f"Install finished. Containers: {len(lines)}. Project: {project}")
        _set_instance_state(instance_id, "running", status="active")
        return

    if any("Restarting" in ln for ln in lines):
        if current_state != "starting":
            _add_install_event(instance_id, "starting", "Container is restarting, waiting for stabilization...")
        _set_instance_state(instance_id, "starting", status="installing")
        return

    if current_state != "failed":
        _add_install_event(instance_id, "failed", "Containers were created but not running: " + " | ".join(lines[:4]))
    _set_instance_state(instance_id, "failed", status="failed")


def _run_install(instance_id: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id, product, repo_url FROM instances WHERE id = ?", (instance_id,)).fetchone()
    if row is None:
        return

    product = row["product"]
    repo_url = row["repo_url"]

    try:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        _ensure_auth_env()

        _set_instance_state(instance_id, "pulling", status="installing")
        _add_install_event(instance_id, "pulling", f"Preparing source for {product}: {repo_url}")
        _set_instance_state(instance_id, "configuring")
        _add_install_event(instance_id, "configuring", "Running installer script and detecting compose file...")
        _set_instance_state(instance_id, "starting")

        script = Path("/home/wwwroot/openclaw-hire/scripts/install_instance.sh")
        rc, out = _run([str(script), instance_id, product, repo_url, str(RUNTIME_ROOT)], clean_env=True)
        if rc != 0:
            raise RuntimeError(out[:2000])

        # Parse machine-readable installer output
        meta: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()

        project = meta.get("COMPOSE_PROJECT")
        compose_file = meta.get("COMPOSE_FILE")
        runtime_dir = meta.get("RUNTIME_DIR")
        web_console_port = meta.get("WEB_CONSOLE_PORT") or None
        http_port = meta.get("HTTP_PORT") or None
        web_console_url = meta.get("WEB_CONSOLE_URL") or None
        if not project or not compose_file or not runtime_dir:
            raise RuntimeError(f"Installer output missing metadata: {out[:500]}")

        with get_connection() as conn:
            conn.execute(
                "UPDATE instances SET compose_project = ?, compose_file = ?, runtime_dir = ?, web_console_port = ?, web_console_url = ?, http_port = ?, updated_at = ? WHERE id = ?",
                (
                    project,
                    compose_file,
                    runtime_dir,
                    int(web_console_port) if web_console_port else None,
                    web_console_url,
                    int(http_port) if http_port else None,
                    _utc_now(),
                    instance_id,
                ),
            )
            conn.commit()

        _add_install_event(instance_id, "starting", f"Installer finished, verifying containers for project {project}...")
        _sync_runtime_status(instance_id, project)

    except Exception as exc:
        _add_install_event(instance_id, "failed", f"Install failed: {exc}")
        _set_instance_state(instance_id, "failed", status="failed")


def sync_instance_status(instance_id: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT compose_project FROM instances WHERE id = ?", (instance_id,)).fetchone()
    if row and row["compose_project"]:
        _sync_runtime_status(instance_id, row["compose_project"])


def trigger_install(instance_id: str) -> None:
    """Kick off real install in a background daemon thread."""
    threading.Thread(target=_run_install, args=(instance_id,), daemon=True).start()


def stop_instance(instance_id: str, compose_file: str, project: str, runtime_dir: str) -> tuple[bool, str]:
    rc, out = _compose_control(compose_file, project, runtime_dir, "stop")
    if rc == 0:
        _set_instance_state(instance_id, "idle", status="inactive")
        _add_install_event(instance_id, "idle", "Instance stopped.")
        return True, out
    _add_install_event(instance_id, "failed", f"Stop failed: {out[:1200]}")
    return False, out


def restart_instance(instance_id: str, compose_file: str, project: str, runtime_dir: str) -> tuple[bool, str]:
    rc, out = _compose_control(compose_file, project, runtime_dir, "restart")
    if rc == 0:
        _patch_zylos_web_console(runtime_dir)
        _patch_zylos_comm_bridge(runtime_dir)
        _restart_zylos_pm2_services(instance_id)
        _sync_runtime_status(instance_id, project)
        _add_install_event(instance_id, "running", "Instance restarted.")
        return True, out
    _add_install_event(instance_id, "failed", f"Restart failed: {out[:1200]}")
    return False, out


def uninstall_instance(instance_id: str, compose_file: str, project: str, runtime_dir: str) -> tuple[bool, str]:
    rc, out = _compose_control(compose_file, project, runtime_dir, "down")
    if rc == 0:
        _set_instance_state(instance_id, "idle", status="inactive")
        _add_install_event(instance_id, "idle", "Instance removed with docker compose down.")
        return True, out
    _add_install_event(instance_id, "failed", f"Uninstall failed: {out[:1200]}")
    return False, out


def _read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _write_env_file(path: Path, env: dict[str, str]) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")


def _safe_agent_name(instance_id: str) -> str:
    suffix = instance_id.replace("inst_", "")[:12]
    base = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in _AGENT_PREFIX).strip("_")
    if not base:
        base = "hire"
    return f"{base}_{suffix}"


def _telegram_token_in_use(instance_id: str, telegram_bot_token: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id FROM instances
            WHERE id <> ? AND telegram_bot_token = ?
              AND COALESCE(status, 'active') <> 'inactive'
              AND COALESCE(install_state, 'idle') <> 'failed'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (instance_id, telegram_bot_token),
        ).fetchone()
    return row["id"] if row else None


def _bootstrap_zylos_components(instance_id: str, runtime_dir: str) -> tuple[bool, str]:
    container = f"zylos_{instance_id}"
    cmd = """
set -e
if [ -x /home/zylos/.npm-global/bin/zylos ]; then
  /home/zylos/.npm-global/bin/zylos add hxa-connect --yes >/tmp/hxa_add.log 2>&1 || true
  /home/zylos/.npm-global/bin/zylos add telegram --yes >/tmp/tg_add.log 2>&1 || true
fi
if [ -d /home/zylos/zylos/.claude/skills/hxa-connect ]; then
  cd /home/zylos/zylos/.claude/skills/hxa-connect
  npm install --silent || true
  [ -f hooks/post-install.js ] && node hooks/post-install.js || true
  pm2 delete zylos-hxa-connect >/dev/null 2>&1 || true
  [ -f ecosystem.config.cjs ] && pm2 start ecosystem.config.cjs || true
fi
if [ -d /home/zylos/zylos/.claude/skills/telegram ]; then
  cd /home/zylos/zylos/.claude/skills/telegram
  npm install --silent || true
  [ -f hooks/post-install.js ] && node hooks/post-install.js || true
  pm2 delete zylos-telegram >/dev/null 2>&1 || true
  [ -f ecosystem.config.cjs ] && pm2 start ecosystem.config.cjs || true
fi
pm2 save >/dev/null 2>&1 || true
pm2 ls --no-color || true
"""
    rc, out = _run(["docker", "exec", container, "sh", "-lc", cmd], cwd=Path(runtime_dir))
    if rc != 0:
        return False, out
    return True, out


def _patch_zylos_web_console(runtime_dir: str) -> bool:
    """Best effort: keep web-console basePath compatible with /connect/zylos/<id>."""
    try:
        app_js = Path(runtime_dir) / "zylos-data" / ".claude" / "skills" / "web-console" / "public" / "app.js"
        if not app_js.exists():
            return False
        text = app_js.read_text()
        old_detect = """  detectBasePath() {\n    const path = window.location.pathname;\n    if (path.startsWith('/console')) {\n      return '/console';\n    }\n    return '';\n  }\n"""
        new_detect = """  detectBasePath() {\n    const path = window.location.pathname;\n    if (path.startsWith('/console')) {\n      return '/console';\n    }\n    const m = path.match(/^\\/(connect\\/zylos\\/[^/]+)/);\n    if (m) {\n      return `/${m[1]}`;\n    }\n    return '';\n  }\n"""
        text = text.replace(old_detect, new_detect)
        old_auth = "const basePath = window.location.pathname.startsWith('/console') ? '/console' : '';"
        new_auth = "const m = window.location.pathname.match(/^\\/(connect\\/zylos\\/[^/]+)/);\\n  const basePath = window.location.pathname.startsWith('/console') ? '/console' : (m ? `/${m[1]}` : '');"
        text = text.replace(old_auth, new_auth)
        app_js.write_text(text)
        return True
    except Exception:
        return False


def _patch_zylos_comm_bridge(runtime_dir: str) -> bool:
    """Best effort: avoid false health-down blocking send/dispatch."""
    try:
        base = Path(runtime_dir) / "zylos-data" / ".claude" / "skills" / "comm-bridge" / "scripts"
        receive_js = base / "c4-receive.js"
        dispatcher_js = base / "c4-dispatcher.js"
        changed = False

        if receive_js.exists():
            text = receive_js.read_text()
            old = "if (status.health !== 'ok') {"
            new = "if (status.health !== 'ok' && status.state !== 'idle' && status.state !== 'busy') {"
            if old in text:
                receive_js.write_text(text.replace(old, new, 1))
                changed = True

        if dispatcher_js.exists():
            text = dispatcher_js.read_text()
            old = "if (agentState.health !== 'ok' && !bypass) {"
            new = "if (agentState.health !== 'ok' && (agentState.state === 'offline' || agentState.state === 'stopped') && !bypass) {"
            if old in text:
                dispatcher_js.write_text(text.replace(old, new, 1))
                changed = True

        return changed
    except Exception:
        return False


def _restart_zylos_pm2_services(instance_id: str) -> None:
    container = f"zylos_{instance_id}"
    _run(["docker", "exec", container, "sh", "-lc", "pm2 restart web-console c4-dispatcher >/dev/null 2>&1 || true"])


def _sync_instance_runtime_env(runtime_dir: str, updates: dict[str, str]) -> bool:
    """Best effort: sync key envs into instance's own runtime .env (e.g., zylos-data/.env)."""
    try:
        zylos_env = Path(runtime_dir) / "zylos-data" / ".env"
        if not zylos_env.exists():
            return False
        env = _read_env_file(zylos_env)
        env.update(updates)
        _write_env_file(zylos_env, env)
        return True
    except Exception:
        return False


def _configure_openclaw_channels(
    instance_id: str,
    telegram_bot_token: str,
    agent_name: str,
    runtime_dir: str,
    _org_token_display: str,
) -> tuple[bool, str]:
    """Post-start channel bootstrap for OpenClaw: Telegram + openclaw-hxa-connect."""
    project_raw = f"hire_{instance_id.replace('-', '')}"
    project = project_raw[:24]
    cli_container = f"{project}-openclaw-cli-1"
    config_dir = Path(runtime_dir) / "openclaw-config"
    openclaw_json = config_dir / "openclaw.json"
    notes: list[str] = []

    # --- Telegram channel ---
    if telegram_bot_token:
        rc, out = _run([
            "docker", "exec", cli_container, "sh", "-lc",
            f"node dist/index.js channels add --channel telegram --token '{telegram_bot_token}' --yes 2>/dev/null || true"
        ])
        if rc == 0:
            notes.append("Telegram channel configured.")
        else:
            notes.append(f"Telegram config warning: {out[:200]}")

    # --- HXA plugin + org registration via SDK inside container ---
    if _ORG_SECRET:
        js = f"""
(async () => {{
  let sdk;
  try {{
    sdk = await import('/home/node/.openclaw/extensions/hxa-connect/node_modules/@coco-xyz/hxa-connect-sdk/dist/index.js');
  }} catch (e) {{
    // attempt fallback path
    try {{ sdk = await import('/home/node/.openclaw/extensions/hxa-connect/node_modules/@coco-xyz/hxa-connect-sdk/dist/index.cjs'); }} catch {{}}
  }}
  if (!sdk) {{ console.log('SDK not found'); return; }}
  const {{ HxaConnectClient }} = sdk;
  const hub = '{_HUB_URL}';
  const orgId = '{_ORG_ID}';
  const secret = '{_ORG_SECRET}';
  const agentName = '{agent_name}';
  try {{
    const reg = await HxaConnectClient.register(hub, orgId, {{ org_secret: secret }}, agentName);
    const token = reg.token || reg.agent_token;
    const agentId = reg.agent_id || reg.id;
    const fs = require('fs');
    const cfgPath = '/home/node/.openclaw/openclaw.json';
    let cfg = {{}};
    try {{ cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8')); }} catch {{}}
    if (!cfg.channels) cfg.channels = {{}};
    cfg.channels['hxa-connect'] = {{
      enabled: true, hubUrl: hub, agentToken: token, agentName: agentName, orgId: orgId,
      access: {{ dmPolicy: 'open', groupPolicy: 'open', threads: {{}} }}
    }};
    if (!cfg.plugins) cfg.plugins = {{}};
    if (!cfg.plugins.entries) cfg.plugins.entries = {{}};
    cfg.plugins.entries['hxa-connect'] = {{ enabled: true }};
    fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + '\\n');
    console.log('HXA registration ok agent=' + agentName);
  }} catch (e) {{ console.error('HXA error', e.message); }}
}})();
"""
        rc, out = _run(["docker", "exec", cli_container, "node", "-e", js])
        if "HXA registration ok" in out:
            # restart gateway to pick up new openclaw.json
            _run(["docker", "exec", cli_container, "sh", "-lc",
                  "node dist/index.js gateway restart 2>/dev/null || true"])
            notes.append("HXA org registration ok.")
        else:
            notes.append(f"HXA registration note: {out[:200]}")

    return True, " ".join(notes) if notes else "OpenClaw channels configured."


def configure_instance_telegram(
    instance_id: str,
    telegram_bot_token: str,
    product: str,
    runtime_dir: str,
    compose_file: str,
    project: str,
) -> tuple[bool, str, str, str, str]:
    """Configure Telegram + org integration after install using only user-provided bot token."""
    plugin = _PLUGIN_MAP.get(product, "hxa-connect")
    env_path = Path(runtime_dir) / ".env"

    if not _ORG_SECRET:
        return False, "Server missing ORG_SECRET/HXA_CONNECT_ORG_SECRET; cannot auto-join org.", "", plugin, ""

    duplicated_by = _telegram_token_in_use(instance_id, telegram_bot_token)
    if duplicated_by:
        return (
            False,
            f"Telegram bot token is already used by instance {duplicated_by}. Use a unique token per running instance.",
            "",
            plugin,
            "",
        )

    agent_name = _safe_agent_name(instance_id)
    org_token_display = f"server-managed:{_ORG_SECRET[-6:]}" if len(_ORG_SECRET) >= 6 else "server-managed"

    env = _read_env_file(env_path)
    # propagate auth envs into runtime zylos/.env so startup auth checks pass
    auth_token = env.get("ANTHROPIC_AUTH_TOKEN", "")
    anthropic_api_key = _normalize_anthropic_api_key(env.get("ANTHROPIC_API_KEY", ""), auth_token)
    claude_oauth = env.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    openai_api_key = env.get("OPENAI_API_KEY", "")
    codex_api_key = env.get("CODEX_API_KEY", "")

    updates = {
        "TELEGRAM_BOT_TOKEN": telegram_bot_token,
        "TELEGRAM_ENABLE_GROUPS": "true",
        "TELEGRAM_ENABLE_DMS": "true",
        "HUB_URL": _HUB_URL,
        "HXA_CONNECT_HUB_URL": _HUB_URL,
        "HXA_CONNECT_URL": _HUB_URL,
        "ORG_ID": _ORG_ID,
        "HXA_CONNECT_ORG_ID": _ORG_ID,
        # Note: post-install hook currently expects org_secret in this field.
        "ORG_TOKEN": _ORG_SECRET,
        "HXA_CONNECT_ORG_TICKET": _ORG_SECRET,
        "HXA_CONNECT_AGENT_NAME": agent_name,
        "HXA_PLUGIN": plugin,
        "PLUGIN_NAME": plugin,
        "ANTHROPIC_AUTH_TOKEN": auth_token,
        "ANTHROPIC_API_KEY": anthropic_api_key,
        "CLAUDE_CODE_OAUTH_TOKEN": claude_oauth,
        "OPENAI_API_KEY": openai_api_key,
        "CODEX_API_KEY": codex_api_key,
    }
    env.update(updates)
    _write_env_file(env_path, env)

    runtime_env_synced = _sync_instance_runtime_env(runtime_dir, updates)

    wd = Path(runtime_dir)
    env_file = str(env_path)

    # Bring down then up with updated env-file.
    # Use _compose_control/_compose_up which handle docker compose vs docker-compose fallback
    # AND clean host env vars that would shadow --env-file (clean_env=True is set inside both).
    _compose_control(compose_file, project, runtime_dir, "down")
    rc, out = _compose_up(Path(compose_file), project, wd, runtime_dir)

    if rc != 0:
        return False, f"Compose restart failed: {out[:500]}", org_token_display, plugin, agent_name

    web_console_patched = False
    comm_bridge_patched = False
    bootstrap_ok = True
    bootstrap_message = ""
    if product == "zylos":
        web_console_patched = _patch_zylos_web_console(runtime_dir)
        comm_bridge_patched = _patch_zylos_comm_bridge(runtime_dir)
        _restart_zylos_pm2_services(instance_id)
        bootstrap_ok, bootstrap_message = _bootstrap_zylos_components(instance_id, runtime_dir)
    elif product == "openclaw":
        bootstrap_ok, bootstrap_message = _configure_openclaw_channels(
            instance_id, telegram_bot_token, agent_name, runtime_dir, org_token_display
        )

    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO instance_configs (instance_id, telegram_bot_token, plugin_name, hub_url, org_id, org_token, agent_name, allow_group, allow_dm, configured_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
              telegram_bot_token=excluded.telegram_bot_token,
              plugin_name=excluded.plugin_name,
              hub_url=excluded.hub_url,
              org_id=excluded.org_id,
              org_token=excluded.org_token,
              agent_name=excluded.agent_name,
              allow_group=1,
              allow_dm=1,
              configured_at=excluded.configured_at,
              updated_at=excluded.updated_at
            """,
            (instance_id, telegram_bot_token, plugin, _HUB_URL, _ORG_ID, org_token_display, agent_name, now, now),
        )
        conn.execute(
            "UPDATE instances SET telegram_bot_token = ?, org_token = ?, agent_name = ?, updated_at = ? WHERE id = ?",
            (telegram_bot_token, org_token_display, agent_name, now, instance_id),
        )
        conn.commit()

    plugin_installed = (Path(runtime_dir) / "zylos-data" / "components" / plugin).exists() or (Path(runtime_dir) / "zylos-data" / ".claude" / "skills" / plugin).exists()

    notes: list[str] = ["配置完成：实例已自动注入组织参数并启用 Telegram。"]
    if runtime_env_synced:
        notes.append("实例内部 .env 已同步。")
    else:
        notes.append("实例内部 .env 未找到，已仅写入 runtime .env。")
    if plugin_installed:
        notes.append(f"插件 {plugin} 已检测到。")
    else:
        notes.append(f"插件 {plugin} 未检测到（需在实例内安装后才会真正入组织）。")
    if product == "zylos":
        notes.append("Web Console 路径补丁已应用。" if web_console_patched else "Web Console 路径补丁未应用。")
        notes.append("消息分发补丁已应用。" if comm_bridge_patched else "消息分发补丁未应用。")
        notes.append("zylos 组件自动启动成功。" if bootstrap_ok else f"zylos 组件自动启动部分失败：{bootstrap_message[:180]}")
    elif product == "openclaw":
        notes.append("OpenClaw Telegram+HXA 配置成功。" if bootstrap_ok else f"OpenClaw 配置部分失败：{bootstrap_message[:180]}")

    msg = " ".join(notes)
    _add_install_event(instance_id, "running", f"Telegram configured. {msg}")
    _sync_runtime_status(instance_id, project)
    return True, msg, org_token_display, plugin, agent_name
