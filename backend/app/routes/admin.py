from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..deps import get_current_user, get_db
from ..schemas import AdminUserInstancesResponse, InstanceResponse, UserResponse

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(current_user: dict) -> None:
    if not bool(current_user.get("is_admin", 0)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")


def _row_to_user(row) -> UserResponse:
    return UserResponse(**{k: row[k] for k in ("id", "name", "email", "company_name", "is_admin", "created_at")})


@router.get("/users", response_model=list[UserResponse])
def list_users(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> list[UserResponse]:
    _require_admin(current_user)
    rows = db.execute(
        "SELECT * FROM users ORDER BY created_at DESC",
    ).fetchall()
    return [_row_to_user(row) for row in rows]


@router.get("/users/{user_id}/instances", response_model=AdminUserInstancesResponse)
def list_user_instances(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> AdminUserInstancesResponse:
    _require_admin(current_user)

    urow = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not urow:
        raise HTTPException(status_code=404, detail="User not found.")

    irows = db.execute(
        """SELECT i.*, c.org_id FROM instances i
           LEFT JOIN instance_configs c ON i.id = c.instance_id
           WHERE i.owner_id = ? ORDER BY i.created_at DESC""",
        (user_id,),
    ).fetchall()

    return AdminUserInstancesResponse(
        user=_row_to_user(urow),
        instances=[InstanceResponse(**dict(row)) for row in irows],
    )


@router.get("/stats")
def platform_stats(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Platform statistics. Admin sees global; regular user sees own org scope."""
    is_admin = bool(current_user.get("is_admin", 0))

    if is_admin:
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_bots = db.execute(
            "SELECT COUNT(*) FROM instances WHERE install_state = 'running'"
        ).fetchone()[0]
        running_bots = db.execute(
            "SELECT COUNT(*) FROM instances WHERE install_state = 'running' AND status = 'active'"
        ).fetchone()[0]
        org_bots = db.execute(
            "SELECT COUNT(*) FROM instance_configs WHERE agent_name IS NOT NULL AND agent_name != ''"
        ).fetchone()[0]
    else:
        # Get org_ids that this user's bots belong to
        user_id = current_user["id"]
        user_org_ids = db.execute(
            """SELECT DISTINCT c.org_id FROM instance_configs c
               JOIN instances i ON c.instance_id = i.id
               WHERE i.owner_id = ? AND c.org_id IS NOT NULL AND c.org_id != ''""",
            (user_id,),
        ).fetchall()
        org_ids = [r[0] for r in user_org_ids]

        if not org_ids:
            return {"total_users": 0, "total_bots": 0, "running_bots": 0, "org_bots": 0}

        placeholders = ",".join("?" for _ in org_ids)
        # Count users who have bots in these orgs
        total_users = db.execute(
            f"""SELECT COUNT(DISTINCT i.owner_id) FROM instances i
                JOIN instance_configs c ON i.id = c.instance_id
                WHERE c.org_id IN ({placeholders})""",
            org_ids,
        ).fetchone()[0]
        # Count running bots in these orgs
        total_bots = db.execute(
            f"""SELECT COUNT(*) FROM instances i
                JOIN instance_configs c ON i.id = c.instance_id
                WHERE i.install_state = 'running' AND c.org_id IN ({placeholders})""",
            org_ids,
        ).fetchone()[0]
        running_bots = db.execute(
            f"""SELECT COUNT(*) FROM instances i
                JOIN instance_configs c ON i.id = c.instance_id
                WHERE i.install_state = 'running' AND i.status = 'active' AND c.org_id IN ({placeholders})""",
            org_ids,
        ).fetchone()[0]
        org_bots = db.execute(
            f"""SELECT COUNT(*) FROM instance_configs c
                WHERE c.agent_name IS NOT NULL AND c.agent_name != '' AND c.org_id IN ({placeholders})""",
            org_ids,
        ).fetchone()[0]

    return {
        "total_users": total_users,
        "total_bots": total_bots,
        "running_bots": running_bots,
        "org_bots": org_bots,
    }


# ---------------------------------------------------------------------------
#  Instance diagnostics & control
# ---------------------------------------------------------------------------

def _docker_run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Run a subprocess command with timeout, return (returncode, stdout)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def _get_container_name(instance_id: str, product: str) -> str:
    """Derive docker container name from instance_id and product type."""
    if product == "zylos":
        return f"zylos_{instance_id}"
    # OpenClaw: hire_{instance_id_no_dashes}-openclaw-gateway-1
    project_raw = f"hire_{instance_id.replace('-', '')}"
    project = project_raw[:24]
    return f"{project}-openclaw-gateway-1"


def _get_compose_project(instance_id: str, product: str) -> str:
    """Derive docker compose project name."""
    if product == "zylos":
        return f"zylos_{instance_id}"
    project_raw = f"hire_{instance_id.replace('-', '')}"
    return project_raw[:24]


def _get_hxa_plugin_info(instance_id: str) -> dict:
    """Read HXA plugin info from runtime config files."""
    runtime_dir = RUNTIME_ROOT / instance_id
    agent_token = ""
    agent_name = ""
    org_id = ""

    # OpenClaw
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"
    if oc_cfg.exists():
        try:
            cfg = json.loads(oc_cfg.read_text())
            hxa = cfg.get("channels", {}).get("hxa-connect", {})
            agent_token = hxa.get("agentToken", "")
            agent_name = hxa.get("agentName", "")
            org_id = hxa.get("orgId", "")
        except Exception:
            pass

    # Zylos
    if not agent_token:
        zy_cfg = runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
        if zy_cfg.exists():
            try:
                cfg = json.loads(zy_cfg.read_text())
                org = cfg.get("orgs", {}).get("default", {})
                agent_token = org.get("agent_token", "")
                agent_name = org.get("agent_name", "")
                org_id = org.get("org_id", "")
            except Exception:
                pass

    installed = bool(agent_token or agent_name)
    hxa_status = "not_configured"
    if installed:
        hxa_status = "offline"  # default when configured but can't verify online

    return {
        "installed": installed,
        "status": hxa_status,
        "agent_name": agent_name or None,
        "org_id": org_id or None,
    }


def _get_claude_info(container_name: str) -> dict:
    """Get Claude process info from inside the container."""
    result: dict = {"running": False, "pid": None, "uptime_seconds": None, "memory_mb": None, "command_line": None}
    rc, out = _docker_run(["docker", "exec", container_name, "ps", "aux"])
    if rc != 0 or not out:
        return result

    for line in out.splitlines():
        if "claude" in line and "grep" not in line and "--dangerously" in line:
            parts = line.split()
            if len(parts) >= 11:
                result["running"] = True
                # Full command is everything from column 10 onwards
                result["command_line"] = " ".join(parts[10:])
                try:
                    result["pid"] = int(parts[1])
                except (ValueError, IndexError):
                    pass
                # RSS is column 5 in ps aux (in KB)
                try:
                    rss_kb = int(parts[5])
                    result["memory_mb"] = round(rss_kb / 1024)
                except (ValueError, IndexError):
                    pass
                if result["pid"]:
                    rc2, out2 = _docker_run([
                        "docker", "exec", container_name,
                        "sh", "-c",
                        f"stat -c %Y /proc/{result['pid']} 2>/dev/null || echo ''"
                    ])
                    if rc2 == 0 and out2.strip().isdigit():
                        start_time = int(out2.strip())
                        result["uptime_seconds"] = int(time.time()) - start_time
            break

    return result


def _get_container_info(container_name: str) -> dict:
    """Get container running status, disk usage, and resource limits."""
    result: dict = {
        "running": False,
        "disk_usage_mb": None,
        "memory_limit_mb": None,
        "cpu_limit": None,
    }

    # Check if container is running
    rc, out = _docker_run([
        "docker", "inspect", "--format", "{{.State.Running}}", container_name
    ])
    if rc != 0:
        return result
    result["running"] = out.strip().lower() == "true"

    if not result["running"]:
        return result

    # Disk usage
    rc, out = _docker_run([
        "docker", "exec", container_name, "du", "-sm", "/home"
    ])
    if rc == 0 and out:
        try:
            result["disk_usage_mb"] = int(out.split()[0])
        except (ValueError, IndexError):
            pass

    # Container memory/cpu limits
    rc, out = _docker_run([
        "docker", "inspect", "--format",
        "{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}", container_name
    ])
    if rc == 0 and out:
        parts = out.split()
        try:
            mem_bytes = int(parts[0])
            if mem_bytes > 0:
                result["memory_limit_mb"] = round(mem_bytes / (1024 * 1024))
        except (ValueError, IndexError):
            pass
        try:
            nano_cpus = int(parts[1])
            if nano_cpus > 0:
                result["cpu_limit"] = round(nano_cpus / 1e9, 2)
        except (ValueError, IndexError):
            pass

    return result


def _get_resource_usage(container_name: str) -> dict:
    """Get live CPU and memory usage via docker stats."""
    result: dict = {"cpu_percent": None, "mem_used_mb": None, "mem_total_mb": None}
    rc, out = _docker_run([
        "docker", "stats", "--no-stream", "--format",
        "{{.CPUPerc}} {{.MemUsage}}", container_name,
    ])
    if rc != 0 or not out:
        return result
    # Example output: "12.34% 512MiB / 8GiB"
    try:
        parts = out.split()
        # CPU percent – strip trailing '%'
        cpu_str = parts[0].rstrip("%")
        result["cpu_percent"] = float(cpu_str)

        # Memory – parts[1] is used, parts[2] is '/', parts[3] is total
        def _parse_mem(s: str) -> int:
            """Convert a docker memory string like '512MiB' or '2GiB' to MB."""
            s = s.strip()
            if s.upper().endswith("GIB"):
                return int(float(s[:-3]) * 1024)
            if s.upper().endswith("MIB"):
                return int(float(s[:-3]))
            if s.upper().endswith("KIB"):
                return max(1, int(float(s[:-3]) / 1024))
            # Fallback: try plain number as bytes
            return int(float(s) / (1024 * 1024))

        result["mem_used_mb"] = _parse_mem(parts[1])
        result["mem_total_mb"] = _parse_mem(parts[3])
    except (IndexError, ValueError):
        pass
    return result


@router.get("/instances/{instance_id}/diagnostics")
def instance_diagnostics(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Return comprehensive health diagnostics for an instance."""
    _require_admin(current_user)

    # Fetch instance + owner + config
    row = db.execute(
        """SELECT i.*, u.name AS owner_name, u.email AS owner_email,
                  c.telegram_bot_token, c.org_id AS config_org_id
           FROM instances i
           JOIN users u ON i.owner_id = u.id
           LEFT JOIN instance_configs c ON i.id = c.instance_id
           WHERE i.id = ?""",
        (instance_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = row["product"] or "openclaw"
    container_name = _get_container_name(instance_id, product)

    # Basic info
    basic_info = {
        "name": row["name"],
        "product": product,
        "instance_id": instance_id,
        "owner_name": row["owner_name"],
        "owner_email": row["owner_email"],
        "install_state": row["install_state"],
        "status": row["status"],
    }

    # HXA plugin
    hxa_plugin = _get_hxa_plugin_info(instance_id)

    # Telegram
    tg_token = row["telegram_bot_token"] if "telegram_bot_token" in row.keys() else None
    telegram = {
        "configured": bool(tg_token),
        "bot_token_set": bool(tg_token),
    }

    # Claude process
    claude = _get_claude_info(container_name)

    # Container info
    container = _get_container_info(container_name)

    # Resource usage (live CPU / memory)
    resource_usage = _get_resource_usage(container_name)

    return {
        "basic_info": basic_info,
        "hxa_plugin": hxa_plugin,
        "telegram": telegram,
        "claude": claude,
        "container": container,
        "resource_usage": resource_usage,
    }


# ---------------------------------------------------------------------------
#  Instance control (start / stop / restart / kill_claude)
# ---------------------------------------------------------------------------

class InstanceControlRequest(BaseModel):
    action: str


def _find_compose_file(instance_id: str) -> Path | None:
    """Find compose file in runtime directory."""
    runtime_dir = RUNTIME_ROOT / instance_id
    candidates = [
        "docker-compose.yml",
        "compose.yml",
        "docker/docker-compose.yml",
        "docker/compose.yml",
    ]
    for c in candidates:
        p = runtime_dir / c
        if p.exists():
            return p
    return None


@router.post("/instances/{instance_id}/control")
def instance_control(
    instance_id: str,
    payload: InstanceControlRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Control an instance: stop, start, restart, or kill_claude."""
    _require_admin(current_user)

    row = db.execute(
        "SELECT product, compose_file, compose_project, runtime_dir FROM instances WHERE id = ?",
        (instance_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = row["product"] or "openclaw"
    action = payload.action.strip().lower()

    if action not in ("stop", "start", "restart", "kill_claude"):
        raise HTTPException(status_code=400, detail="Invalid action. Use: stop, start, restart, kill_claude")

    container_name = _get_container_name(instance_id, product)

    # For compose operations, resolve compose file and project
    compose_file = row["compose_file"] or ""
    runtime_dir = row["runtime_dir"] or str(RUNTIME_ROOT / instance_id)
    project = row["compose_project"] or _get_compose_project(instance_id, product)

    if not compose_file:
        found = _find_compose_file(instance_id)
        if found:
            compose_file = str(found)

    if action == "kill_claude":
        if product == "zylos":
            rc, out = _docker_run(["docker", "exec", container_name, "pkill", "-f", "claude --"])
        else:
            rc, out = _docker_run(["docker", "exec", container_name, "pkill", "-f", "claude"])
        if rc == 0 or rc == 1:  # 1 means no process matched, which is fine
            return {"ok": True, "action": action, "detail": "Claude process kill signal sent."}
        return {"ok": False, "action": action, "detail": out}

    if action == "restart":
        rc, out = _docker_run(["docker", "restart", container_name])
        return {"ok": rc == 0, "action": action, "detail": out}

    if not compose_file:
        raise HTTPException(status_code=400, detail="Compose file not found for this instance.")

    env_args: list[str] = []
    env_path = Path(runtime_dir) / ".env"
    if env_path.exists():
        env_args = ["--env-file", str(env_path)]

    if action == "stop":
        rc, out = _docker_run(
            ["docker", "compose", "-f", compose_file, "-p", project] + env_args + ["down"],
            timeout=30,
        )
        if rc != 0:
            rc, out = _docker_run(
                ["docker-compose", "-f", compose_file, "-p", project] + env_args + ["down"],
                timeout=30,
            )
        return {"ok": rc == 0, "action": action, "detail": out}

    if action == "start":
        rc, out = _docker_run(
            ["docker", "compose", "-f", compose_file, "-p", project] + env_args + ["up", "-d"],
            timeout=60,
        )
        if rc != 0:
            rc, out = _docker_run(
                ["docker-compose", "-f", compose_file, "-p", project] + env_args + ["up", "-d"],
                timeout=60,
            )
        return {"ok": rc == 0, "action": action, "detail": out}

    # Should not reach here
    raise HTTPException(status_code=400, detail="Unknown action.")


# ---------------------------------------------------------------------------
#  Instance resource limits
# ---------------------------------------------------------------------------

class ResourceLimitRequest(BaseModel):
    memory_mb: int
    cpus: float


@router.post("/instances/{instance_id}/resources")
def instance_resources(
    instance_id: str,
    payload: ResourceLimitRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Update container resource limits (memory & CPU)."""
    _require_admin(current_user)

    row = db.execute(
        "SELECT product FROM instances WHERE id = ?", (instance_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = row["product"] or "openclaw"
    container_name = _get_container_name(instance_id, product)

    rc, out = _docker_run([
        "docker", "update",
        f"--memory={payload.memory_mb}m",
        f"--cpus={payload.cpus}",
        container_name,
    ], timeout=15)

    if rc != 0:
        return {"ok": False, "detail": out or "docker update failed"}
    return {"ok": True, "detail": f"Resources updated: {payload.memory_mb}MB memory, {payload.cpus} CPUs"}
