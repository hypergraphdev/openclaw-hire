from __future__ import annotations

import secrets
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..database import get_connection

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")

_HUB_URL = "https://www.ucai.net/connect"
_ORG_ID = "123cd566-c2ea-409f-8f7e-4fa9f5296dd1"
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


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        out = (proc.stdout or "").strip()
        return proc.returncode, out
    except FileNotFoundError as exc:
        return 127, str(exc)


def _compose_up(compose_file: Path, project: str, workdir: Path) -> tuple[int, str]:
    # Prefer docker compose plugin, fallback to docker-compose binary.
    rc, out = _run(["docker", "compose", "-f", str(compose_file), "-p", project, "up", "-d", "--build"], cwd=workdir)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", str(compose_file), "-p", project, "up", "-d", "--build"], cwd=workdir)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose failed:\n{out}\n\ndocker-compose failed:\n{out2}"


def _compose_control(compose_file: str, project: str, workdir: str, action: str) -> tuple[int, str]:
    wd = Path(workdir)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project, action], cwd=wd)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", compose_file, "-p", project, action], cwd=wd)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose {action} failed:\n{out}\n\ndocker-compose {action} failed:\n{out2}"


def compose_logs(compose_file: str, project: str, workdir: str, lines: int = 200) -> tuple[int, str]:
    wd = Path(workdir)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project, "logs", "--tail", str(lines)], cwd=wd)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", compose_file, "-p", project, "logs", "--tail", str(lines)], cwd=wd)
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

        _set_instance_state(instance_id, "pulling", status="installing")
        _add_install_event(instance_id, "pulling", f"Preparing source for {product}: {repo_url}")
        _set_instance_state(instance_id, "configuring")
        _add_install_event(instance_id, "configuring", "Running installer script and detecting compose file...")
        _set_instance_state(instance_id, "starting")

        script = Path("/home/wwwroot/openclaw-hire/scripts/install_instance.sh")
        rc, out = _run([str(script), instance_id, product, repo_url, str(RUNTIME_ROOT)])
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


def configure_instance_telegram(
    instance_id: str,
    telegram_bot_token: str,
    product: str,
    runtime_dir: str,
    compose_file: str,
    project: str,
) -> tuple[bool, str, str, str]:
    """Write telegram/plugin env vars, persist org token, restart compose."""
    org_token = secrets.token_hex(24)
    plugin = _PLUGIN_MAP.get(product, "hxa-connect")
    env_path = Path(runtime_dir) / ".env"

    env = _read_env_file(env_path)
    env.update({
        "TELEGRAM_BOT_TOKEN": telegram_bot_token,
        "TELEGRAM_ENABLE_GROUPS": "true",
        "TELEGRAM_ENABLE_DMS": "true",
        "HUB_URL": _HUB_URL,
        "HXA_CONNECT_HUB_URL": _HUB_URL,
        "ORG_ID": _ORG_ID,
        "ORG_TOKEN": org_token,
        "HXA_PLUGIN": plugin,
        "PLUGIN_NAME": plugin,
    })
    _write_env_file(env_path, env)

    wd = Path(runtime_dir)
    env_file = str(env_path)

    # Bring down then up with updated env-file
    _run(["docker", "compose", "-f", compose_file, "-p", project, "--env-file", env_file, "down"], cwd=wd)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project, "--env-file", env_file, "up", "-d"], cwd=wd)
    if rc != 0:
        _run(["docker-compose", "-f", compose_file, "-p", project, "--env-file", env_file, "down"], cwd=wd)
        rc, out = _run(["docker-compose", "-f", compose_file, "-p", project, "--env-file", env_file, "up", "-d"], cwd=wd)

    if rc != 0:
        return False, f"Compose restart failed: {out[:500]}", org_token, plugin

    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO instance_configs (instance_id, telegram_bot_token, plugin_name, hub_url, org_id, org_token, allow_group, allow_dm, configured_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
              telegram_bot_token=excluded.telegram_bot_token,
              plugin_name=excluded.plugin_name,
              hub_url=excluded.hub_url,
              org_id=excluded.org_id,
              org_token=excluded.org_token,
              allow_group=1,
              allow_dm=1,
              configured_at=excluded.configured_at,
              updated_at=excluded.updated_at
            """,
            (instance_id, telegram_bot_token, plugin, _HUB_URL, _ORG_ID, org_token, now, now),
        )
        conn.commit()

    _add_install_event(instance_id, "running", f"Telegram configured. Plugin {plugin} linked to org {_ORG_ID}.")
    _sync_runtime_status(instance_id, project)
    return True, "配置完成：可通过 Telegram 在群聊和私信联系该实例。", org_token, plugin
