from __future__ import annotations

import json
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
    db=Depends(get_db),
) -> list[UserResponse]:
    _require_admin(current_user)
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    rows = cursor.fetchall()
    cursor.close()
    return [_row_to_user(row) for row in rows]


@router.get("/users/{user_id}/instances", response_model=AdminUserInstancesResponse)
def list_user_instances(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> AdminUserInstancesResponse:
    _require_admin(current_user)

    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    urow = cursor.fetchone()
    cursor.close()
    if not urow:
        raise HTTPException(status_code=404, detail="User not found.")

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT i.*, c.org_id FROM instances i
           LEFT JOIN instance_configs c ON i.id = c.instance_id
           WHERE i.owner_id = %s ORDER BY i.created_at DESC""",
        (user_id,),
    )
    irows = cursor.fetchall()
    cursor.close()

    return AdminUserInstancesResponse(
        user=_row_to_user(urow),
        instances=[InstanceResponse(**dict(row)) for row in irows],
    )


@router.get("/instances/hxa-status")
def batch_hxa_status(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get HXA online status for all instances by querying Hub per org."""
    _require_admin(current_user)
    from ..database import get_setting, get_connection
    from .admin_hxa import _hub_org_admin_request

    # Collect all org_ids and their agent_names
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT c.instance_id, c.agent_name, c.org_id
           FROM instance_configs c
           WHERE c.org_id IS NOT NULL AND c.org_id != ''
             AND c.agent_name IS NOT NULL AND c.agent_name != ''""",
    )
    rows = cursor.fetchall()
    cursor.close()

    # Also include instances without instance_configs but with known Hub names
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, agent_name FROM instances WHERE agent_name IS NOT NULL AND agent_name != ''")
    inst_rows = cursor.fetchall()
    cursor.close()
    inst_agent_map = {r["id"]: r["agent_name"] for r in inst_rows}

    # Group by org_id
    orgs: dict[str, list[dict]] = {}
    for r in rows:
        orgs.setdefault(r["org_id"], []).append(r)

    # Helper to resolve org secret
    default_org_id = get_setting("hxa_org_id", "")
    default_org_secret = get_setting("hxa_org_secret", "")

    def _get_secret(oid: str) -> str:
        if oid == default_org_id:
            return default_org_secret
        conn = get_connection()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT org_secret FROM org_secrets WHERE org_id = %s", (oid,))
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        return row["org_secret"] if row else ""

    # Query each org's bots from Hub
    result: dict[str, dict] = {}  # instance_id -> {online, org_id, agent_name}
    for org_id, items in orgs.items():
        secret = _get_secret(org_id)
        if not secret:
            for item in items:
                result[item["instance_id"]] = {"online": False, "org_id": org_id, "agent_name": item["agent_name"]}
            continue
        try:
            hub_bots = _hub_org_admin_request("GET", "/api/bots", org_id, secret) or []
            if isinstance(hub_bots, dict):
                hub_bots = hub_bots.get("bots", hub_bots.get("items", []))
            online_map = {b.get("name", ""): b.get("online", False) for b in hub_bots}
        except Exception:
            online_map = {}
        for item in items:
            result[item["instance_id"]] = {
                "online": online_map.get(item["agent_name"], False),
                "org_id": org_id,
                "agent_name": item["agent_name"],
            }

    # Also check default org for instances without instance_configs
    # (bots auto-registered with hire_ prefix)
    if default_org_secret:
        try:
            default_bots = _hub_org_admin_request("GET", "/api/bots", default_org_id, default_org_secret) or []
            if isinstance(default_bots, dict):
                default_bots = default_bots.get("bots", default_bots.get("items", []))
            for b in default_bots:
                bname = b.get("name", "")
                # Match hire_{instance_id_prefix} pattern
                if bname.startswith("hire_"):
                    suffix = bname[5:]
                    for inst_id, aname in inst_agent_map.items():
                        if inst_id.replace("inst_", "").startswith(suffix) and inst_id not in result:
                            result[inst_id] = {"online": b.get("online", False), "org_id": default_org_id, "agent_name": bname}
        except Exception:
            pass

    return result


@router.get("/stats")
def platform_stats(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Platform statistics. Admin sees global; regular user sees own org scope."""
    is_admin = bool(current_user.get("is_admin", 0))

    if is_admin:
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS c FROM users")
        total_users = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) AS c FROM instances WHERE install_state = 'running'")
        total_bots = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) AS c FROM instances WHERE install_state = 'running' AND status = 'active'")
        running_bots = cursor.fetchone()["c"]
        cursor.execute("SELECT COUNT(*) AS c FROM instance_configs WHERE agent_name IS NOT NULL AND agent_name != ''")
        org_bots = cursor.fetchone()["c"]
        cursor.close()
    else:
        # Get org_ids that this user's bots belong to
        user_id = current_user["id"]
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            """SELECT DISTINCT c.org_id FROM instance_configs c
               JOIN instances i ON c.instance_id = i.id
               WHERE i.owner_id = %s AND c.org_id IS NOT NULL AND c.org_id != ''""",
            (user_id,),
        )
        user_org_ids = cursor.fetchall()
        cursor.close()
        org_ids = [r["org_id"] for r in user_org_ids]

        if not org_ids:
            return {"total_users": 0, "total_bots": 0, "running_bots": 0, "org_bots": 0}

        placeholders = ",".join("%s" for _ in org_ids)
        cursor = db.cursor(dictionary=True)
        # Count users who have bots in these orgs
        cursor.execute(
            f"""SELECT COUNT(DISTINCT i.owner_id) AS c FROM instances i
                JOIN instance_configs c ON i.id = c.instance_id
                WHERE c.org_id IN ({placeholders})""",
            org_ids,
        )
        total_users = cursor.fetchone()["c"]
        # Count running bots in these orgs
        cursor.execute(
            f"""SELECT COUNT(*) AS c FROM instances i
                JOIN instance_configs c ON i.id = c.instance_id
                WHERE i.install_state = 'running' AND c.org_id IN ({placeholders})""",
            org_ids,
        )
        total_bots = cursor.fetchone()["c"]
        cursor.execute(
            f"""SELECT COUNT(*) AS c FROM instances i
                JOIN instance_configs c ON i.id = c.instance_id
                WHERE i.install_state = 'running' AND i.status = 'active' AND c.org_id IN ({placeholders})""",
            org_ids,
        )
        running_bots = cursor.fetchone()["c"]
        cursor.execute(
            f"""SELECT COUNT(*) AS c FROM instance_configs c
                WHERE c.agent_name IS NOT NULL AND c.agent_name != '' AND c.org_id IN ({placeholders})""",
            org_ids,
        )
        org_bots = cursor.fetchone()["c"]
        cursor.close()

    return {
        "total_users": total_users,
        "total_bots": total_bots,
        "running_bots": running_bots,
        "org_bots": org_bots,
    }


# ---------------------------------------------------------------------------
#  Instance diagnostics & control
# ---------------------------------------------------------------------------

from ..services.docker_utils import (
    docker_run as _docker_run,
    get_container_name as _get_container_name,
    get_compose_project as _get_compose_project,
    get_resource_usage as _get_resource_usage,
    get_claude_info as _get_claude_info,
    get_container_info as _get_container_info,
)


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


@router.get("/instances/{instance_id}/diagnostics")
def instance_diagnostics(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Return comprehensive health diagnostics for an instance."""
    _require_admin(current_user)

    # Fetch instance + owner + config
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT i.*, u.name AS owner_name, u.email AS owner_email,
                  c.telegram_bot_token, c.org_id AS config_org_id
           FROM instances i
           JOIN users u ON i.owner_id = u.id
           LEFT JOIN instance_configs c ON i.id = c.instance_id
           WHERE i.id = %s""",
        (instance_id,),
    )
    row = cursor.fetchone()
    cursor.close()
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
    tg_token = row.get("telegram_bot_token")
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
    db=Depends(get_db),
):
    """Control an instance: stop, start, restart, or kill_claude."""
    _require_admin(current_user)

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT product, compose_file, compose_project, runtime_dir FROM instances WHERE id = %s",
        (instance_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = row["product"] or "openclaw"
    action = payload.action.strip().lower()

    if action not in ("stop", "start", "restart", "kill_claude", "restart_hxa"):
        raise HTTPException(status_code=400, detail="Invalid action. Use: stop, start, restart, kill_claude, restart_hxa")

    container_name = _get_container_name(instance_id, product)

    # For compose operations, resolve compose file and project
    compose_file = row["compose_file"] or ""
    runtime_dir = row["runtime_dir"] or str(RUNTIME_ROOT / instance_id)
    project = row["compose_project"] or _get_compose_project(instance_id, product)

    if not compose_file:
        found = _find_compose_file(instance_id)
        if found:
            compose_file = str(found)

    if action == "restart_hxa":
        # Restart only hxa-connect process inside the container (makes bot online in Hub)
        if product == "zylos":
            rc, out = _docker_run(["docker", "exec", container_name, "pm2", "restart", "zylos-hxa-connect"])
        else:
            rc, out = _docker_run(["docker", "exec", container_name, "pm2", "restart", "all"])
        return {"ok": rc == 0, "action": action, "detail": out or "hxa-connect restarted"}

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
    db=Depends(get_db),
):
    """Update container resource limits (memory & CPU)."""
    _require_admin(current_user)

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT product FROM instances WHERE id = %s", (instance_id,)
    )
    row = cursor.fetchone()
    cursor.close()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = row["product"] or "openclaw"
    container_name = _get_container_name(instance_id, product)

    # Must set --memory-swap equal to --memory (or -1 for unlimited swap)
    # to avoid "Memory limit should be smaller than memoryswap limit" error
    # Also update all containers for this instance (OpenClaw has gateway + cli)
    all_containers = []
    rc_ls, out_ls = _docker_run(["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name=hire_{instance_id}"], timeout=5)
    if rc_ls == 0 and out_ls.strip():
        all_containers = [c.strip() for c in out_ls.strip().splitlines() if c.strip()]
    if not all_containers:
        # Zylos or fallback
        rc_ls2, out_ls2 = _docker_run(["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name=zylos_{instance_id}"], timeout=5)
        if rc_ls2 == 0 and out_ls2.strip():
            all_containers = [c.strip() for c in out_ls2.strip().splitlines() if c.strip()]
    if not all_containers:
        all_containers = [container_name]

    errors = []
    for cname in all_containers:
        rc, out = _docker_run([
            "docker", "update",
            f"--memory={payload.memory_mb}m",
            f"--memory-swap={payload.memory_mb}m",
            f"--cpus={payload.cpus}",
            cname,
        ], timeout=15)
        if rc != 0:
            errors.append(f"{cname}: {out}")

    if errors:
        return {"ok": False, "detail": "; ".join(errors)}
    return {"ok": True, "detail": f"Resources updated on {len(all_containers)} container(s): {payload.memory_mb}MB, {payload.cpus} CPUs"}
