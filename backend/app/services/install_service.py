from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..database import get_connection, get_setting, hxa_hub_url, runtime_root, site_base_url


def _runtime_root_path() -> Path:
    """Return runtime root as a Path, resolved from DB/env config."""
    return Path(runtime_root())


def _get_hub_url() -> str:
    """Read HXA hub URL from DB settings (fall back to default)."""
    return hxa_hub_url()


# Backward-compat alias for import
_HUB_URL = hxa_hub_url()


def _get_org_id() -> str:
    """Read HXA org ID from DB settings (fall back to env)."""
    from_db = get_setting("hxa_org_id", "")
    return from_db or os.getenv("HXA_CONNECT_ORG_ID", "")


def _get_org_secret() -> str:
    """Read HXA org secret from DB settings (fall back to env)."""
    from_db = get_setting("hxa_org_secret", "")
    return from_db or os.getenv("HXA_CONNECT_ORG_SECRET") or os.getenv("ORG_SECRET") or ""


# Backward-compat aliases (read at import time as fallback only)
_ORG_ID = ""
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

# Resource limits applied to every instance container after start
_CONTAINER_MEMORY = "8g"
_CONTAINER_CPUS = "4.0"
_CONTAINER_PIDS = "512"


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
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if status is None:
            cursor.execute(
                "UPDATE instances SET install_state = %s, updated_at = %s WHERE id = %s",
                (state, _utc_now(), instance_id),
            )
        else:
            cursor.execute(
                "UPDATE instances SET install_state = %s, status = %s, updated_at = %s WHERE id = %s",
                (state, status, _utc_now(), instance_id),
            )
        cursor.close()
    finally:
        conn.close()


def _add_install_event(instance_id: str, state: str, message: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO install_events (instance_id, state, message, created_at) VALUES (%s, %s, %s, %s)",
            (instance_id, state, message, _utc_now()),
        )
        cursor.close()
    finally:
        conn.close()


_PORT_SHADOW_KEYS = frozenset({
    "OPENCLAW_GATEWAY_PORT", "OPENCLAW_BRIDGE_PORT",
    "OPENCLAW_GATEWAY_TOKEN", "OPENCLAW_GATEWAY_BIND",
    "WEB_CONSOLE_PORT", "HTTP_PORT",
})


def _make_clean_env() -> dict[str, str]:
    """Build a fresh env dict each call, stripping host port vars.
    Must be built at call-time (not module-load time) because the host process
    might export these vars after module import."""
    return {k: v for k, v in os.environ.items() if k not in _PORT_SHADOW_KEYS}


def _run(cmd: list[str], cwd: Path | None = None, clean_env: bool = False, extra_env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        env = _make_clean_env() if clean_env else dict(os.environ)
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
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


def _apply_container_limits(project: str) -> None:
    """Apply memory/CPU/PID limits to all running containers in a compose project."""
    rc, out = _run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}"])
    if rc != 0 or not out.strip():
        return
    for cid in out.strip().splitlines():
        cid = cid.strip()
        if not cid:
            continue
        _run(["docker", "update",
              "--memory", _CONTAINER_MEMORY,
              "--memory-swap", str(int(_CONTAINER_MEMORY.rstrip('g')) * 2) + "g",
              "--cpus", _CONTAINER_CPUS,
              "--pids-limit", _CONTAINER_PIDS,
              cid])


def _inject_resource_limits(compose_file: Path) -> None:
    """Inject deploy.resources.limits into compose YAML file.

    Replaces the commented-out deploy block from the template, or appends
    a deploy block inside the first service if none exists.
    """
    import re
    text = compose_file.read_text()

    limits_block = (
        "    deploy:\n"
        "      resources:\n"
        "        limits:\n"
        f"          memory: {_CONTAINER_MEMORY}\n"
        f"          cpus: \"{_CONTAINER_CPUS}\"\n"
        "        reservations:\n"
        "          memory: 512m"
    )

    # Case 1: Replace commented deploy block from template
    commented = re.search(
        r'\n(\s+#\s*deploy:\s*\n(?:\s+#\s*.*\n)*)', text
    )
    if commented:
        text = text[:commented.start()] + '\n' + limits_block + '\n' + text[commented.end():]
        compose_file.write_text(text)
        return

    # Case 2: Already has uncommented deploy block — update limits
    existing = re.search(r'\n(\s+deploy:\s*\n(?:\s+\S.*\n)*)', text)
    if existing:
        text = text[:existing.start()] + '\n' + limits_block + '\n' + text[existing.end():]
        compose_file.write_text(text)
        return

    # Case 3: No deploy block at all — insert before 'volumes:' top-level key
    vol_match = re.search(r'\n(# ──.*volumes|volumes:)', text, re.IGNORECASE)
    if vol_match:
        text = text[:vol_match.start()] + '\n' + limits_block + '\n' + text[vol_match.start():]
        compose_file.write_text(text)
        return

    # Case 4: Fallback — append to end of first service (before top-level 'volumes:')
    compose_file.write_text(text)


def _compose_up(compose_file: Path, project: str, workdir: Path, runtime_dir: str | None = None) -> tuple[int, str]:
    # Inject resource limits into compose YAML before starting
    try:
        _inject_resource_limits(compose_file)
    except Exception:
        pass  # Best-effort; fall back to docker update

    env_args = _env_file_for(runtime_dir or str(workdir))
    rc, out = _run(["docker", "compose", "-f", str(compose_file), "-p", project] + env_args + ["up", "-d", "--build"], cwd=workdir, clean_env=True)
    if rc == 0:
        _apply_container_limits(project)
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", str(compose_file), "-p", project] + env_args + ["up", "-d", "--build"], cwd=workdir, clean_env=True)
    if rc2 == 0:
        _apply_container_limits(project)
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
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT install_state FROM instances WHERE id = %s", (instance_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
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
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, product, repo_url FROM instances WHERE id = %s", (instance_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    if row is None:
        return

    product = row["product"]
    repo_url = row["repo_url"]

    try:
        _runtime_root_path().mkdir(parents=True, exist_ok=True)
        _ensure_auth_env()

        _set_instance_state(instance_id, "pulling", status="installing")
        _add_install_event(instance_id, "pulling", f"Preparing source for {product}: {repo_url}")
        _set_instance_state(instance_id, "configuring")
        _add_install_event(instance_id, "configuring", "Running installer script and detecting compose file...")
        _set_instance_state(instance_id, "starting")

        # Scripts are in project root /scripts/, Python file is at backend/app/services/
        _project_root = Path(__file__).resolve().parent.parent.parent.parent
        script = _project_root / "scripts" / "install_instance.sh"
        # Inject admin-configurable settings from DB into installer env
        db_anthropic_base = get_setting("anthropic_base_url", "")
        db_anthropic_token = get_setting("anthropic_auth_token", "")
        db_openai_base = get_setting("openai_base_url", "")
        db_openai_key = get_setting("openai_api_key", "")
        db_hxa_org_id = get_setting("hxa_org_id", "")
        db_hxa_org_secret = get_setting("hxa_org_secret", "")
        install_extra_env: dict[str, str] = {}
        if db_anthropic_base:
            install_extra_env["ANTHROPIC_BASE_URL"] = db_anthropic_base
        if db_anthropic_token:
            install_extra_env["ANTHROPIC_AUTH_TOKEN"] = db_anthropic_token
        if db_openai_base:
            install_extra_env["OPENAI_BASE_URL"] = db_openai_base
        if db_openai_key:
            install_extra_env["OPENAI_API_KEY"] = db_openai_key
            install_extra_env["CODEX_API_KEY"] = db_openai_key
        if db_hxa_org_id:
            install_extra_env["HXA_CONNECT_ORG_ID"] = db_hxa_org_id
        if db_hxa_org_secret:
            install_extra_env["HXA_CONNECT_ORG_SECRET"] = db_hxa_org_secret
            install_extra_env["ORG_SECRET"] = db_hxa_org_secret
        # Container uses /app/runtime internally; HOST_RUNTIME_ROOT tells install script
        # what path to use for docker compose volume mounts (must be valid on host)
        container_runtime = str(Path(__file__).resolve().parent.parent.parent / "runtime")
        # OPENCLAW_HOME is the HOST path; RUNTIME_ROOT is the container path
        _openclaw_home = os.getenv("OPENCLAW_HOME", "")
        host_runtime = os.path.join(_openclaw_home, "runtime") if _openclaw_home else container_runtime
        install_extra_env["HOST_RUNTIME_ROOT"] = host_runtime
        rc, out = _run([str(script), instance_id, product, repo_url, container_runtime], clean_env=True, extra_env=install_extra_env)
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

        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE instances SET compose_project = %s, compose_file = %s, runtime_dir = %s, web_console_port = %s, web_console_url = %s, http_port = %s, updated_at = %s WHERE id = %s",
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
            cursor.close()
        finally:
            conn.close()

        _add_install_event(instance_id, "starting", f"Installer finished, verifying containers for project {project}...")
        _sync_runtime_status(instance_id, project)

    except Exception as exc:
        _add_install_event(instance_id, "failed", f"Install failed: {exc}")
        _set_instance_state(instance_id, "failed", status="failed")


def sync_instance_status(instance_id: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT compose_project FROM instances WHERE id = %s", (instance_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
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
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id FROM instances
            WHERE id <> %s AND telegram_bot_token = %s
              AND COALESCE(status, 'active') <> 'inactive'
              AND COALESCE(install_state, 'idle') <> 'failed'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (instance_id, telegram_bot_token),
        )
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
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

    # Ensure hxa-connect config.json exists after bootstrap
    fix_cmd = (
        "HXA_CFG=/home/zylos/zylos/components/hxa-connect/config.json; "
        "if [ ! -f \"$HXA_CFG\" ] || [ ! -s \"$HXA_CFG\" ]; then "
        "  echo [bootstrap] hxa-connect config missing, re-running post-install...; "
        "  cd /home/zylos/zylos/.claude/skills/hxa-connect && node hooks/post-install.js 2>&1 || true; "
        "fi; "
        "pm2 restart zylos-hxa-connect >/dev/null 2>&1 || true"
    )
    _run(["docker", "exec", container, "sh", "-lc", fix_cmd], cwd=Path(runtime_dir))
    return True, out


def _register_zylos_hxa_agent(instance_id: str, runtime_dir: str) -> tuple[bool, str]:
    """Register Zylos agent with HXA Connect as member via ticket, write config.json into container.
    Called BEFORE bootstrap so hxa-connect starts with a valid config.json."""
    agent_name = _safe_agent_name(instance_id)
    _ORG_SECRET_LIVE = _get_org_secret()
    _ORG_ID_LIVE = _get_org_id()
    if not _ORG_SECRET_LIVE:
        return False, "Server missing ORG_SECRET."

    hub = _get_hub_url().rstrip("/")
    from urllib.parse import urlparse as _up3
    _p3 = _up3(hub)
    origin = f"{_p3.scheme}://{_p3.netloc}"

    # Step 1: Admin login to get session cookie
    try:
        login_data = json.dumps({"type": "org_admin", "org_secret": _ORG_SECRET_LIVE, "org_id": _ORG_ID_LIVE}).encode()
        login_req = urllib.request.Request(f"{hub}/api/auth/login", data=login_data,
                                           headers={"Content-Type": "application/json", "Origin": origin}, method="POST")
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]
    except Exception as e:
        return False, f"Admin login failed: {e}"

    # Step 2: Cleanup existing bot if any
    _cleanup_zylos_hxa_bot(agent_name, _ORG_ID_LIVE, _ORG_SECRET_LIVE)

    # Step 3: Create a one-time ticket
    try:
        ticket_data = json.dumps({"reusable": False}).encode()
        ticket_req = urllib.request.Request(f"{hub}/api/org/tickets", data=ticket_data,
                                            headers={"Content-Type": "application/json", "Cookie": cookie, "Origin": origin}, method="POST")
        with urllib.request.urlopen(ticket_req, timeout=10) as resp:
            ticket_result = json.loads(resp.read().decode())
        ticket_secret = ticket_result.get("secret") or ticket_result.get("ticket") or ""
        if not ticket_secret:
            return False, f"Ticket creation returned no secret: {ticket_result}"
    except Exception as e:
        return False, f"Ticket creation failed: {e}"

    # Step 4: Register agent using ticket (member role)
    reg_url = f"{hub}/api/auth/register"
    reg_data = json.dumps({
        "org_id": _ORG_ID_LIVE,
        "ticket": ticket_secret,
        "name": agent_name,
    }).encode()
    try:
        reg_req = urllib.request.Request(reg_url, data=reg_data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(reg_req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        return False, f"HXA registration failed: {e}"

    agent_token = result.get("token", "")
    agent_id = result.get("agent_id") or result.get("id", "")
    if not agent_token:
        return False, f"HXA registration returned no token: {result}"

    # Write config.json into container
    config = {
        "default_hub_url": _get_hub_url(),
        "orgs": {
            "default": {
                "org_id": _ORG_ID_LIVE,
                "agent_id": agent_id,
                "agent_token": agent_token,
                "agent_name": agent_name,
                "hub_url": None,
                "access": {"dmPolicy": "open", "groupPolicy": "open", "threadMode": "mention"},
            }
        },
    }
    config_json = json.dumps(config, indent=2) + "\n"
    container = f"zylos_{instance_id}"
    config_path = "/home/zylos/zylos/components/hxa-connect/config.json"
    _run(["docker", "exec", container, "sh", "-c", f"mkdir -p $(dirname {config_path}) && cat > {config_path} << 'CFGEOF'\n{config_json}CFGEOF"])
    _run(["docker", "exec", container, "sh", "-lc", "pm2 restart zylos-hxa-connect 2>/dev/null || true"])

    return True, f"Agent {agent_name} registered (id: {agent_id})"


def _cleanup_zylos_hxa_bot(agent_name: str, org_id: str, org_secret: str) -> None:
    """Best effort: delete existing bot by name via admin API."""
    try:
        hub = _get_hub_url().rstrip("/")
        from urllib.parse import urlparse as _up4
        _p4 = _up4(hub)
        _origin = f"{_p4.scheme}://{_p4.netloc}"

        # Login as org admin
        login_data = json.dumps({"type": "org_admin", "org_secret": org_secret, "org_id": org_id}).encode()
        req = urllib.request.Request(f"{hub}/api/auth/login", data=login_data, headers={"Content-Type": "application/json", "Origin": _origin}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]

        # List bots
        list_req = urllib.request.Request(f"{hub}/api/bots", headers={"Cookie": cookie, "Origin": _origin})
        with urllib.request.urlopen(list_req, timeout=10) as resp:
            bots = json.loads(resp.read().decode())

        # Find and delete matching bot
        for bot in (bots if isinstance(bots, list) else []):
            if bot.get("name") == agent_name:
                del_req = urllib.request.Request(f"{hub}/api/bots/{bot['id']}", headers={"Cookie": cookie, "Origin": _origin}, method="DELETE")
                urllib.request.urlopen(del_req, timeout=10)
                break

        # Delete tombstone so the name can be reused
        try:
            ts_req = urllib.request.Request(f"{hub}/api/orgs/{org_id}/tombstones/{agent_name}", headers={"Cookie": cookie, "Origin": _origin}, method="DELETE")
            urllib.request.urlopen(ts_req, timeout=10)
        except Exception:
            pass
    except Exception:
        pass


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


def _relax_openclaw_runtime_permissions(runtime_dir: str, project: str) -> bool:
    """Fix ownership and set safe permissions.

    extensions/ must NOT be world-writable — OpenClaw refuses to load world-writable plugins.
    workspace/ gets 755/644 so the node user can read/write its own files.
    """
    ok = False
    root = Path(runtime_dir)

    # extensions: 755 dirs, 644 files (plugin security requirement)
    ext_root = root / "openclaw-config" / "extensions"
    if ext_root.exists():
        for p in [ext_root, *ext_root.rglob("*")]:
            try:
                os.chmod(p, 0o755 if p.is_dir() else 0o644)
                ok = True
            except Exception:
                pass

    # workspace: 755 dirs, 644 files
    ws_root = root / "openclaw-workspace"
    if ws_root.exists():
        for p in [ws_root, *ws_root.rglob("*")]:
            try:
                os.chmod(p, 0o755 if p.is_dir() else 0o644)
                ok = True
            except Exception:
                pass

    gateway_container = f"{project}-openclaw-gateway-1"
    rc, _ = _run([
        "docker", "exec", "--user", "root", gateway_container, "sh", "-lc",
        "chown -R node:node /home/node/.openclaw 2>/dev/null || true; "
        "find /home/node/.openclaw/extensions -type d -exec chmod 755 {} + 2>/dev/null || true; "
        "find /home/node/.openclaw/extensions -type f -exec chmod 644 {} + 2>/dev/null || true; "
        "find /home/node/.openclaw/workspace -type d -exec chmod 755 {} + 2>/dev/null || true; "
        "find /home/node/.openclaw/workspace -type f -exec chmod 644 {} + 2>/dev/null || true"
    ])
    if rc == 0:
        ok = True
    return ok


def _configure_openclaw_channels(
    instance_id: str,
    telegram_bot_token: str,
    agent_name: str,
    runtime_dir: str,
    _org_token_display: str,
    plugin_name: str,
) -> tuple[bool, str]:
    """Post-start bootstrap for OpenClaw.

    Use the container only to obtain the HXA registration token. Persist the final
    openclaw.json on the host, then restart and verify to avoid silent overwrite bugs.
    """
    project_raw = f"hire_{instance_id.replace('-', '')}"
    project = project_raw[:24]
    cli_container = f"{project}-openclaw-cli-1"
    gateway_container = f"{project}-openclaw-gateway-1"
    config_dir = Path(runtime_dir) / "openclaw-config"
    openclaw_json = config_dir / "openclaw.json"
    notes: list[str] = []

    if _relax_openclaw_runtime_permissions(runtime_dir, project):
        notes.append("Runtime permissions relaxed.")

    if not openclaw_json.exists():
        return False, f"Missing config file: {openclaw_json}"

    try:
        cfg = json.loads(openclaw_json.read_text())
    except Exception:
        cfg = {}

    _live_org_secret = _get_org_secret()
    _live_org_id = _get_org_id()
    hxa_token = ""

    if _live_org_secret:
        js = f"""
(async () => {{
  let sdk;
  try {{
    sdk = await import('/home/node/.openclaw/extensions/openclaw-hxa-connect/node_modules/@coco-xyz/hxa-connect-sdk/dist/index.js');
  }} catch (e) {{
    try {{ sdk = await import('/home/node/.openclaw/extensions/openclaw-hxa-connect/node_modules/@coco-xyz/hxa-connect-sdk/dist/index.cjs'); }} catch {{}}
  }}
  if (!sdk) {{ console.log('SDK_NOT_FOUND'); return; }}
  const {{ HxaConnectClient }} = sdk;
  try {{
    const reg = await HxaConnectClient.register({repr(_get_hub_url())}, {repr(_live_org_id)}, {{ org_secret: {repr(_live_org_secret)} }}, {repr(agent_name)});
    const token = reg.token || reg.agent_token || reg.bot_token || '';
    const agentId = reg.agent_id || reg.id || reg.bot_id || '';
    console.log('HXA_REG_OK::' + JSON.stringify({{ token, agentId }}));
  }} catch (e) {{
    console.error('HXA_REG_ERR::' + e.message);
  }}
}})();
"""
        _, out = _run(["docker", "exec", cli_container, "node", "-e", js])
        marker = "HXA_REG_OK::"
        if marker in out:
            raw = out.split(marker, 1)[1].strip().splitlines()[0]
            try:
                parsed = json.loads(raw)
                hxa_token = str(parsed.get("token") or "")
                if hxa_token:
                    notes.append("HXA org registration ok.")
            except Exception:
                notes.append("HXA registration parse failed.")
        else:
            notes.append(f"HXA registration note: {out[:200]}")

    if not cfg.get("channels"):
        cfg["channels"] = {}
    cfg["channels"]["telegram"] = {
        "enabled": bool(telegram_bot_token),
        "dmPolicy": "open",
        "botToken": telegram_bot_token or "",
        "groups": {"*": {"requireMention": False}},
        "allowFrom": ["*"],
        "groupPolicy": "allowlist",
        "streaming": "partial",
    }
    # openclaw-hxa-connect is a plugin, not a native channel.
    # Do not write cfg["channels"]["hxa-connect"].
    if not cfg.get("plugins"):
        cfg["plugins"] = {}
    if not cfg["plugins"].get("entries"):
        cfg["plugins"]["entries"] = {}
    cfg["plugins"]["entries"][plugin_name] = {"enabled": True}

    openclaw_json.write_text(json.dumps(cfg, indent=2) + "\n")
    notes.append("Host config written.")

    _run(["docker", "restart", gateway_container])
    time.sleep(2)

    try:
        verify = json.loads(openclaw_json.read_text())
    except Exception as e:
        return False, f"Config verify read failed: {e}"

    tg = ((verify.get("channels") or {}).get("telegram") or {})
    plugin_ok = bool(((((verify.get("plugins") or {}).get("entries") or {}).get(plugin_name)) or {}).get("enabled"))
    if not tg.get("enabled") or not tg.get("botToken"):
        return False, "Telegram config was overwritten after restart."
    if not plugin_ok:
        return False, f"Plugin entry {plugin_name} missing after restart."

    notes.append("Restart verified.")
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

    _ORG_SECRET_LIVE = _get_org_secret()
    _ORG_ID_LIVE = _get_org_id()
    if not _ORG_SECRET_LIVE:
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
    org_token_display = f"server-managed:{_ORG_SECRET_LIVE[-6:]}" if len(_ORG_SECRET_LIVE) >= 6 else "server-managed"

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
        "HUB_URL": _get_hub_url(),
        "HXA_CONNECT_HUB_URL": _get_hub_url(),
        "HXA_CONNECT_URL": _get_hub_url(),
        "ORG_ID": _ORG_ID_LIVE,
        "HXA_CONNECT_ORG_ID": _ORG_ID_LIVE,
        # Note: post-install hook currently expects org_secret in this field.
        "ORG_TOKEN": _ORG_SECRET_LIVE,
        "HXA_CONNECT_ORG_TICKET": _ORG_SECRET_LIVE,
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
            instance_id, telegram_bot_token, agent_name, runtime_dir, org_token_display, plugin
        )

    now = _utc_now()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO instance_configs (instance_id, telegram_bot_token, plugin_name, hub_url, org_id, org_token, agent_name, allow_group, allow_dm, configured_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 1, %s, %s)
            ON DUPLICATE KEY UPDATE
              telegram_bot_token=VALUES(telegram_bot_token),
              plugin_name=VALUES(plugin_name),
              hub_url=VALUES(hub_url),
              org_id=VALUES(org_id),
              org_token=VALUES(org_token),
              agent_name=VALUES(agent_name),
              allow_group=1,
              allow_dm=1,
              configured_at=VALUES(configured_at),
              updated_at=VALUES(updated_at)
            """,
            (instance_id, telegram_bot_token, plugin, _get_hub_url(), _ORG_ID_LIVE, org_token_display, agent_name, now, now),
        )
        cursor.execute(
            "UPDATE instances SET telegram_bot_token = %s, org_token = %s, agent_name = %s, updated_at = %s WHERE id = %s",
            (telegram_bot_token, org_token_display, agent_name, now, instance_id),
        )
        cursor.close()
    finally:
        conn.close()

    plugin_installed = (
        (Path(runtime_dir) / "zylos-data" / "components" / plugin).exists()
        or (Path(runtime_dir) / "zylos-data" / ".claude" / "skills" / plugin).exists()
        or (Path(runtime_dir) / "openclaw-config" / "extensions" / "openclaw-hxa-connect").exists()
    )

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


# ── Standalone Telegram-only configuration ────────────────────────────────────

def configure_telegram_only(
    instance_id: str,
    telegram_bot_token: str,
    runtime_dir: str,
    compose_file: str,
    project: str,
    product: str = "openclaw",
) -> tuple[bool, str]:
    """Configure only the Telegram channel. Routes to product-specific impl."""
    # Duplicate-token check (shared)
    duplicated_by = _telegram_token_in_use(instance_id, telegram_bot_token)
    if duplicated_by:
        return False, f"Telegram bot token is already used by instance {duplicated_by}."

    if product == "zylos":
        return _configure_zylos_telegram_only(instance_id, telegram_bot_token, runtime_dir, compose_file, project)
    else:
        return _configure_openclaw_telegram_only(instance_id, telegram_bot_token, runtime_dir, project)


def _configure_openclaw_telegram_only(
    instance_id: str,
    telegram_bot_token: str,
    runtime_dir: str,
    project: str,
) -> tuple[bool, str]:
    """Configure Telegram for OpenClaw: write to openclaw.json, restart gateway."""
    gateway_container = f"{project}-openclaw-gateway-1"
    config_dir = Path(runtime_dir) / "openclaw-config"
    openclaw_json = config_dir / "openclaw.json"

    if not openclaw_json.exists():
        return False, f"Missing config file: {openclaw_json}"

    try:
        cfg = json.loads(openclaw_json.read_text())
    except Exception as e:
        return False, f"Config parse error: {e}"

    if not cfg.get("channels"):
        cfg["channels"] = {}
    cfg["channels"]["telegram"] = {
        "enabled": True,
        "dmPolicy": "open",
        "botToken": telegram_bot_token,
        "groups": {"*": {"requireMention": False}},
        "allowFrom": ["*"],
        "groupPolicy": "allowlist",
        "streaming": "partial",
    }
    openclaw_json.write_text(json.dumps(cfg, indent=2) + "\n")

    # Fix permissions
    ext_root = config_dir / "extensions"
    if ext_root.exists():
        for p in [ext_root, *ext_root.rglob("*")]:
            try:
                os.chmod(p, 0o755 if p.is_dir() else 0o644)
            except Exception:
                pass

    _run(["docker", "restart", gateway_container])

    # Quick verification (max ~15s to avoid nginx 504)
    for _ in range(5):
        time.sleep(3)
        _, logs = _run(["docker", "logs", "--tail", "30", gateway_container])
        if "[telegram]" in logs and "starting provider" in logs:
            return True, "Telegram configured and verified."

    return True, "Telegram bot token 已写入 openclaw.json，网关已重启。"


def _configure_zylos_telegram_only(
    instance_id: str,
    telegram_bot_token: str,
    runtime_dir: str,
    compose_file: str,
    project: str,
) -> tuple[bool, str]:
    """Configure only Telegram for Zylos: write bot token to .env, restart, start telegram component."""
    env_path = Path(runtime_dir) / ".env"
    container = f"zylos_{instance_id}"

    # Write to host .env files
    env = _read_env_file(env_path)
    updates = {
        "TELEGRAM_BOT_TOKEN": telegram_bot_token,
        "TELEGRAM_ENABLE_GROUPS": "true",
        "TELEGRAM_ENABLE_DMS": "true",
    }
    env.update(updates)
    _write_env_file(env_path, env)
    _sync_instance_runtime_env(runtime_dir, updates)

    # Update the mounted volume .env file for persistence
    inject_cmd = (
        f"sed -i 's|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN={telegram_bot_token}|' /home/zylos/zylos/.env; "
        f"grep -q '^TELEGRAM_BOT_TOKEN=' /home/zylos/zylos/.env || "
        f"echo 'TELEGRAM_BOT_TOKEN={telegram_bot_token}' >> /home/zylos/zylos/.env; "
        f"grep -q '^TELEGRAM_ENABLE_GROUPS=' /home/zylos/zylos/.env || "
        f"echo 'TELEGRAM_ENABLE_GROUPS=true' >> /home/zylos/zylos/.env; "
        f"grep -q '^TELEGRAM_ENABLE_DMS=' /home/zylos/zylos/.env || "
        f"echo 'TELEGRAM_ENABLE_DMS=true' >> /home/zylos/zylos/.env"
    )
    _run(["docker", "exec", container, "sh", "-c", inject_cmd])

    # Key fix: pm2 start with explicit env vars to bypass the dotenv vs
    # docker-env conflict. Docker sets TELEGRAM_BOT_TOKEN="" at container
    # creation (from compose ${TELEGRAM_BOT_TOKEN:-}), and dotenv refuses
    # to overwrite existing env vars. So we must inject via pm2 env.
    _run(["docker", "exec", container, "sh", "-lc",
          "pm2 delete zylos-telegram 2>/dev/null || true"])
    pm2_start_cmd = (
        f"cd /home/zylos/zylos/.claude/skills/telegram && "
        f"TELEGRAM_BOT_TOKEN={telegram_bot_token!r} "
        f"TELEGRAM_ENABLE_GROUPS=true "
        f"TELEGRAM_ENABLE_DMS=true "
        f"pm2 start ecosystem.config.cjs --update-env 2>/dev/null || true; "
        f"pm2 save 2>/dev/null || true"
    )
    _run(["docker", "exec", container, "sh", "-lc", pm2_start_cmd])

    # Verify telegram started (max ~15s)
    for _ in range(5):
        time.sleep(3)
        rc2, out2 = _run(["docker", "exec", container, "sh", "-lc",
                          "pm2 jlist 2>/dev/null || true"])
        if "zylos-telegram" in out2 and "online" in out2:
            _add_install_event(instance_id, "running", "Telegram configured and verified (Zylos).")
            _sync_runtime_status(instance_id, project)
            return True, "Telegram 已配置并验证启动。"

    _add_install_event(instance_id, "running", "Telegram configured (Zylos).")
    _sync_runtime_status(instance_id, project)
    return True, "Telegram bot token 已写入。"


# ── Standalone HXA-only configuration ────────────────────────────────────────

def configure_hxa_only(
    instance_id: str,
    runtime_dir: str,
    project: str,
    product: str = "openclaw",
    compose_file: str = "",
) -> tuple[bool, str]:
    """Register with HXA org. Routes to product-specific impl."""
    if product == "zylos":
        return _configure_zylos_hxa_only(instance_id, runtime_dir, compose_file, project)
    return _configure_openclaw_hxa_only(instance_id, runtime_dir, project)


def _configure_zylos_hxa_only(
    instance_id: str,
    runtime_dir: str,
    compose_file: str,
    project: str,
) -> tuple[bool, str]:
    """Register Zylos instance with HXA org: inject env vars, restart, bootstrap components."""
    env_path = Path(runtime_dir) / ".env"
    agent_name = _safe_agent_name(instance_id)
    plugin = _PLUGIN_MAP.get("zylos", "hxa-connect")

    _ORG_SECRET_LIVE = _get_org_secret()
    _ORG_ID_LIVE = _get_org_id()
    if not _ORG_SECRET_LIVE:
        return False, "Server missing ORG_SECRET."

    env = _read_env_file(env_path)

    # Sync latest API keys from admin settings into instance .env
    _db_anthropic_base = get_setting("anthropic_base_url", "")
    _db_anthropic_token = get_setting("anthropic_auth_token", "")
    _db_openai_base = get_setting("openai_base_url", "")
    _db_openai_key = get_setting("openai_api_key", "")

    updates = {
        "HUB_URL": _get_hub_url(),
        "HXA_CONNECT_HUB_URL": _get_hub_url(),
        "HXA_CONNECT_URL": _get_hub_url(),
        "ORG_ID": _ORG_ID_LIVE,
        "HXA_CONNECT_ORG_ID": _ORG_ID_LIVE,
        "ORG_TOKEN": _ORG_SECRET_LIVE,
        "HXA_CONNECT_ORG_TICKET": _ORG_SECRET_LIVE,
        "HXA_CONNECT_AGENT_NAME": agent_name,
        "HXA_PLUGIN": plugin,
        "PLUGIN_NAME": plugin,
    }
    if _db_anthropic_base:
        updates["ANTHROPIC_BASE_URL"] = _db_anthropic_base
    if _db_anthropic_token:
        updates["ANTHROPIC_AUTH_TOKEN"] = _db_anthropic_token
        updates["ANTHROPIC_API_KEY"] = _db_anthropic_token
    if _db_openai_base:
        updates["OPENAI_BASE_URL"] = _db_openai_base
    if _db_openai_key:
        updates["OPENAI_API_KEY"] = _db_openai_key
        updates["CODEX_API_KEY"] = _db_openai_key
    env.update(updates)
    _write_env_file(env_path, env)
    _sync_instance_runtime_env(runtime_dir, updates)

    # Docker compose down/up
    wd = Path(runtime_dir)
    _compose_control(compose_file, project, runtime_dir, "down")
    rc, out = _compose_up(Path(compose_file), project, wd, runtime_dir)
    if rc != 0:
        return False, f"Compose restart failed: {out[:500]}"

    _patch_zylos_web_console(runtime_dir)
    _patch_zylos_comm_bridge(runtime_dir)

    # Register agent BEFORE bootstrap so hxa-connect starts with valid config.json
    reg_ok, reg_msg = _register_zylos_hxa_agent(instance_id, runtime_dir)

    _restart_zylos_pm2_services(instance_id)
    bootstrap_ok, bootstrap_msg = _bootstrap_zylos_components(instance_id, runtime_dir)
    if not reg_ok:
        return False, f"HXA registration failed: {reg_msg}"

    _add_install_event(instance_id, "running", f"HXA configured (Zylos). Agent: {agent_name}")
    _sync_runtime_status(instance_id, project)
    return True, f"HXA connected. Agent: {agent_name}"


def _configure_openclaw_hxa_only(
    instance_id: str,
    runtime_dir: str,
    project: str,
) -> tuple[bool, str]:
    """Register with HXA org, write token to HOST openclaw.json, restart, verify WebSocket."""
    gateway_container = f"{project}-openclaw-gateway-1"
    config_dir = Path(runtime_dir) / "openclaw-config"
    openclaw_json = config_dir / "openclaw.json"
    agent_name = _safe_agent_name(instance_id)
    _live_org_secret = _get_org_secret()
    _live_org_id = _get_org_id()
    # Origin must match Hub's domain for CSRF check (not our site URL)
    hub_url = _get_hub_url()
    from urllib.parse import urlparse
    _parsed = urlparse(hub_url)
    origin = f"{_parsed.scheme}://{_parsed.netloc}"

    if not _live_org_secret:
        return False, "Server missing ORG_SECRET."

    # Fix plugin directory permissions
    ext_root = config_dir / "extensions"
    if ext_root.exists():
        for p in [ext_root, *ext_root.rglob("*")]:
            try:
                os.chmod(p, 0o755 if p.is_dir() else 0o644)
            except Exception:
                pass

    if not openclaw_json.exists():
        return False, f"Missing config file: {openclaw_json}"

    # Sync API keys from admin settings into openclaw.json (in case they were set after install)
    try:
        _cfg = json.loads(openclaw_json.read_text())
        _anthropic = _cfg.get("models", {}).get("providers", {}).get("anthropic", {})
        _db_base = get_setting("anthropic_base_url", "")
        _db_token = get_setting("anthropic_auth_token", "")
        _changed = False
        if _db_base and _anthropic.get("baseUrl") != _db_base:
            _anthropic["baseUrl"] = _db_base
            _changed = True
        if _db_token and _anthropic.get("apiKey") != _db_token:
            _anthropic["apiKey"] = _db_token
            _changed = True
        if _changed:
            openclaw_json.write_text(json.dumps(_cfg, indent=2) + "\n")
    except Exception:
        pass  # Non-fatal

    def _do_register() -> tuple[str, str, str]:
        """Create ticket then register as member. Returns (token, agentId, error_msg)."""
        js = f"""
(async () => {{
  const origin = {repr(origin)};
  const hub = {repr(_get_hub_url())};
  try {{
    // Step 1: Admin login
    const loginR = await fetch(hub + "/api/auth/login", {{
      method: "POST",
      headers: {{"Content-Type": "application/json", Origin: origin}},
      body: JSON.stringify({{type: "org_admin", org_secret: {repr(_live_org_secret)}, org_id: {repr(_live_org_id)}}})
    }});
    if (!loginR.ok) throw new Error("Admin login failed: " + loginR.status);
    const cookie = loginR.headers.get("set-cookie").split(";")[0];

    // Step 2: Create one-time ticket
    const ticketR = await fetch(hub + "/api/org/tickets", {{
      method: "POST",
      headers: {{"Content-Type": "application/json", Cookie: cookie, Origin: origin}},
      body: JSON.stringify({{reusable: false}})
    }});
    if (!ticketR.ok) throw new Error("Ticket creation failed: " + ticketR.status);
    const ticketData = await ticketR.json();
    const ticket = ticketData.secret || ticketData.ticket || "";
    if (!ticket) throw new Error("No ticket secret returned");

    // Step 3: Register as member using ticket
    const regR = await fetch(hub + "/api/auth/register", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{org_id: {repr(_live_org_id)}, ticket: ticket, name: {repr(agent_name)}}})
    }});
    if (!regR.ok) {{
      const body = await regR.text().catch(() => "");
      throw new Error("Registration failed (" + regR.status + "): " + body);
    }}
    const reg = await regR.json();
    const token = reg.token || reg.agent_token || reg.bot_token || "";
    const agentId = reg.id || reg.bot_id || reg.agent_id || "";
    console.log("HXA_REG_OK::" + JSON.stringify({{ token, agentId }}));
  }} catch(e) {{
    console.log("HXA_REG_ERR::" + e.message);
  }}
}})();
"""
        _, out = _run(["docker", "exec", gateway_container, "node", "-e", js])
        if "HXA_REG_OK::" in out:
            raw = out.split("HXA_REG_OK::")[1].strip().splitlines()[0]
            try:
                parsed = json.loads(raw)
                return str(parsed.get("token", "")), str(parsed.get("agentId", "")), ""
            except Exception as pe:
                return "", "", f"Parse error: {pe}"
        err = ""
        if "HXA_REG_ERR::" in out:
            err = out.split("HXA_REG_ERR::")[-1].strip()[:200]
        else:
            err = out[:200]
        return "", "", err

    def _cleanup_and_retry() -> tuple[str, str, str]:
        """Delete existing bot + tombstone, then re-register."""
        cleanup_js = f"""
(async () => {{
  try {{
    const origin = {repr(origin)};
    const loginR = await fetch({repr(_get_hub_url() + "/api/auth/login")}, {{
      method: "POST", headers: {{"Content-Type": "application/json", Origin: origin}},
      body: JSON.stringify({{type: "org_admin", org_secret: {repr(_live_org_secret)}, org_id: {repr(_live_org_id)}}})
    }});
    const cookie = loginR.headers.get("set-cookie").split(";")[0];
    const bots = await (await fetch({repr(_get_hub_url() + "/api/bots")}, {{headers: {{Cookie: cookie, Origin: origin}}}})).json();
    const bot = Array.isArray(bots) ? bots.find(b => b.name === {repr(agent_name)}) : null;
    if (bot) await fetch({repr(_get_hub_url())} + "/api/bots/" + bot.id, {{method: "DELETE", headers: {{Cookie: cookie, Origin: origin}}}});
    await fetch({repr(_get_hub_url() + "/api/orgs/")} + {repr(_live_org_id)} + "/tombstones/" + {repr(agent_name)}, {{method: "DELETE", headers: {{Cookie: cookie, Origin: origin}}}});
    console.log("CLEANUP_OK");
  }} catch(e) {{ console.log("CLEANUP_ERR::" + e.message); }}
}})();
"""
        _run(["docker", "exec", gateway_container, "node", "-e", cleanup_js])
        return _do_register()

    # First attempt
    token, agent_id, err = _do_register()
    if not token and ("already exists" in err or "NAME_CONFLICT" in err or "reserved" in err or "Reserved" in err):
        token, agent_id, err = _cleanup_and_retry()

    if not token:
        return False, f"HXA registration failed: {err}"

    # Write agentToken to HOST openclaw.json
    try:
        cfg = json.loads(openclaw_json.read_text())
    except Exception:
        cfg = {}
    if not cfg.get("channels"):
        cfg["channels"] = {}
    cfg["channels"]["hxa-connect"] = {
        "enabled": True,
        "hubUrl": _get_hub_url(),
        "agentToken": token,
        "agentName": agent_name,
        "agentId": agent_id,
        "orgId": _live_org_id,
        "access": {"dmPolicy": "open", "groupPolicy": "open", "threads": {}},
    }
    openclaw_json.write_text(json.dumps(cfg, indent=2) + "\n")

    _run(["docker", "restart", gateway_container])

    # Verify WebSocket connection up to 30s
    for _ in range(10):
        time.sleep(3)
        _, logs = _run(["docker", "logs", "--tail", "30", gateway_container])
        if "hxa-connect" in logs and "WebSocket connected" in logs:
            return True, f"HXA connected. Agent: {agent_name}"

    return False, "HXA token written but WebSocket connection not confirmed within 30s. Check container logs."

