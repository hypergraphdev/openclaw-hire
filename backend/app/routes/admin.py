from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..database import runtime_root
from ..deps import get_current_user, get_db
from ..schemas import AdminUserInstancesResponse, InstanceResponse, UserResponse

RUNTIME_ROOT = Path(runtime_root())

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


@router.get("/users/stats")
def users_stats(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """User list with instance counts for user management tab."""
    _require_admin(current_user)
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.id, u.name, u.email, u.is_admin, u.created_at, u.last_login_at,
               COUNT(i.id) AS instance_count,
               SUM(CASE WHEN i.status = 'active' THEN 1 ELSE 0 END) AS running_count
        FROM users u
        LEFT JOIN instances i ON u.id = i.owner_id
        GROUP BY u.id
        ORDER BY u.created_at DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


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
    """Get HXA online status for all instances.

    Strategy: query ALL known orgs from Hub first, build a global
    bot_name → {online, org_id} map, then match instances by agent_name.
    This handles bots that were transferred between orgs (local DB org_id stale).
    """
    _require_admin(current_user)
    from ..database import get_setting, get_connection
    from .admin_hxa import _hub_org_admin_request

    default_org_id = get_setting("hxa_org_id", "")
    default_org_secret = get_setting("hxa_org_secret", "")

    # Step 1: Collect ALL known org secrets
    all_orgs: dict[str, str] = {}  # org_id → org_secret
    if default_org_id and default_org_secret:
        all_orgs[default_org_id] = default_org_secret
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT org_id, org_secret FROM org_secrets WHERE org_secret IS NOT NULL AND org_secret != ''")
        for r in cur.fetchall():
            all_orgs[r["org_id"]] = r["org_secret"]
        cur.close()
    finally:
        conn.close()

    # Step 2: Query ALL orgs from Hub, build global bot_name → {online, org_id} map
    global_bot_map: dict[str, dict] = {}  # bot_name → {online, org_id}
    for org_id, secret in all_orgs.items():
        try:
            hub_bots = _hub_org_admin_request("GET", "/api/bots", org_id, secret) or []
            if isinstance(hub_bots, dict):
                hub_bots = hub_bots.get("bots", hub_bots.get("items", []))
            for b in hub_bots:
                bname = b.get("name", "")
                if not bname:
                    continue
                is_online = b.get("online", False)
                # If bot exists in multiple orgs, prefer the online one
                if bname not in global_bot_map or is_online:
                    global_bot_map[bname] = {"online": is_online, "org_id": org_id}
        except Exception:
            pass

    # Step 3: Get all instances with their agent_names
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT i.id, i.agent_name AS inst_agent,
                  c.agent_name AS cfg_agent, c.org_id AS cfg_org_id
           FROM instances i
           LEFT JOIN instance_configs c ON i.id = c.instance_id""",
    )
    rows = cursor.fetchall()
    cursor.close()

    # Step 4: Match instances to global bot map
    result: dict[str, dict] = {}
    # Build reverse index: extract instance_id suffix from bot names for fuzzy matching
    # e.g. "hire_e27571bdbfed" → "e27571bdbfed", "hire_inst_603992fdd3" → "603992fdd3"
    bot_by_suffix: dict[str, dict] = {}
    for bname, binfo in global_bot_map.items():
        for prefix in ("hire_inst_", "hire_"):
            if bname.startswith(prefix):
                bot_by_suffix[bname[len(prefix):]] = {**binfo, "hub_name": bname}
                break

    for r in rows:
        inst_id = r["id"]
        agent_name = r["cfg_agent"] or r["inst_agent"] or ""
        db_org_id = r["cfg_org_id"] or ""

        if not agent_name:
            continue

        # Exact match first
        hub_info = global_bot_map.get(agent_name)
        hub_name = agent_name

        # Fuzzy match: try matching by instance_id suffix
        if not hub_info:
            inst_suffix = inst_id.replace("inst_", "")
            for suffix, sinfo in bot_by_suffix.items():
                if inst_suffix.startswith(suffix) or suffix.startswith(inst_suffix[:10]):
                    hub_info = sinfo
                    hub_name = sinfo["hub_name"]
                    break

        if hub_info:
            actual_org_id = hub_info["org_id"]
            # Auto-fix stale data in DB
            needs_fix = False
            if db_org_id and db_org_id != actual_org_id:
                needs_fix = True
            if hub_name != agent_name:
                needs_fix = True
            if needs_fix:
                try:
                    fix_cur = db.cursor()
                    fix_cur.execute(
                        "UPDATE instance_configs SET org_id = %s, agent_name = %s WHERE instance_id = %s",
                        (actual_org_id, hub_name, inst_id),
                    )
                    fix_cur.execute(
                        "UPDATE instances SET agent_name = %s WHERE id = %s",
                        (hub_name, inst_id),
                    )
                    fix_cur.close()
                except Exception:
                    pass
            result[inst_id] = {
                "online": hub_info["online"],
                "org_id": actual_org_id,
                "agent_name": hub_name,
            }
        else:
            result[inst_id] = {
                "online": False,
                "org_id": db_org_id,
                "agent_name": agent_name,
            }

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

    # Config file paths
    runtime_dir = RUNTIME_ROOT / instance_id
    config_files: list[dict] = []
    candidates = [
        ("openclaw.json", runtime_dir / "openclaw-config" / "openclaw.json"),
        (".env", runtime_dir / ".env"),
        ("docker-compose.yml", runtime_dir / "docker-compose.yml"),
        ("compose.yml", runtime_dir / "compose.yml"),
        ("hxa config.json", runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"),
    ]
    for label, p in candidates:
        if p.exists():
            config_files.append({"label": label, "path": str(p)})

    # Zylos config (activity monitor tuning)
    zylos_config: dict | None = None
    if product == "zylos":
        zy_cfg_path = runtime_dir / "zylos-data" / ".zylos" / "config.json"
        if zy_cfg_path.exists():
            try:
                zylos_config = json.loads(zy_cfg_path.read_text())
            except Exception:
                zylos_config = {}
        # Read hardcoded defaults from activity-monitor.js for display
        am_defaults = {
            "periodic_probe_interval": {"default": 180, "unit": "秒", "desc": "定期探针间隔（费token主因）"},
            "health_check_interval": {"default": 21600, "unit": "秒", "desc": "完整健康检查间隔"},
            "heartbeat_interval": {"default": 7200, "unit": "秒", "desc": "心跳安全网间隔"},
            "usage_check_interval": {"default": 3600, "unit": "秒", "desc": "用量检查间隔", "configurable": True},
            "usage_warn_threshold": {"default": 80, "unit": "%", "desc": "用量警告阈值", "configurable": True},
        }
        zylos_config = {
            "path": str(zy_cfg_path),
            "values": zylos_config or {},
            "am_defaults": am_defaults,
        }

    # OpenClaw version
    openclaw_version = None
    if product == "openclaw" and container.get("running"):
        try:
            rc, ver_out = _docker_run(["docker", "exec", container_name, "openclaw", "--version"])
            openclaw_version = ver_out.strip() if rc == 0 else None
        except Exception:
            pass

    return {
        "basic_info": basic_info,
        "hxa_plugin": hxa_plugin,
        "telegram": telegram,
        "claude": claude,
        "container": container,
        "resource_usage": resource_usage,
        "config_files": config_files,
        "runtime_dir": str(runtime_dir),
        "zylos_config": zylos_config,
        "openclaw_version": openclaw_version,
    }


# ---------------------------------------------------------------------------
#  Zylos config update
# ---------------------------------------------------------------------------

class ZylosConfigUpdateRequest(BaseModel):
    updates: dict[str, int | float | str]
    restart_pm2: bool = False


# Replacements to make hardcoded constants read from config.json
_AM_PATCHES: list[tuple[str, str]] = [
    (
        "const HEARTBEAT_INTERVAL = 7200;",
        "const HEARTBEAT_INTERVAL = readConfigInt('heartbeat_interval', 7200);",
    ),
    (
        "const DOWN_RETRY_INTERVAL = 3600;",
        "const DOWN_RETRY_INTERVAL = readConfigInt('down_retry_interval', 3600);",
    ),
    (
        "const PERIODIC_PROBE_INTERVAL = 180;",
        "const PERIODIC_PROBE_INTERVAL = readConfigInt('periodic_probe_interval', 180);",
    ),
    (
        "const HEALTH_CHECK_INTERVAL = 21600;",
        "const HEALTH_CHECK_INTERVAL = readConfigInt('health_check_interval', 21600);",
    ),
]


@router.post("/instances/{instance_id}/zylos-config")
def update_zylos_config(
    instance_id: str,
    payload: ZylosConfigUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Update Zylos config.json + optionally patch activity-monitor.js to use readConfigInt."""
    _require_admin(current_user)

    zy_cfg_path = RUNTIME_ROOT / instance_id / "zylos-data" / ".zylos" / "config.json"
    if not zy_cfg_path.exists():
        raise HTTPException(status_code=404, detail="Zylos config not found.")

    try:
        cfg = json.loads(zy_cfg_path.read_text())
    except Exception:
        cfg = {}

    cfg.update(payload.updates)
    zy_cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")

    # Auto-patch activity-monitor.js to use readConfigInt for hardcoded constants
    am_path = RUNTIME_ROOT / instance_id / "zylos-data" / ".claude" / "skills" / "activity-monitor" / "scripts" / "activity-monitor.js"
    patched = False
    if am_path.exists():
        src = am_path.read_text()
        for old, new in _AM_PATCHES:
            if old in src:
                src = src.replace(old, new)
                patched = True
        if patched:
            am_path.write_text(src)

    # Restart pm2 activity-monitor to pick up changes
    details: list[str] = []
    if patched:
        details.append("activity-monitor.js patched to use readConfigInt")
    details.append("config.json updated")

    if payload.restart_pm2:
        container = f"zylos_{instance_id}"
        rc, out = _docker_run(["docker", "exec", container, "pm2", "restart", "activity-monitor"], timeout=15)
        details.append(f"pm2 restart: {'ok' if rc == 0 else out}")

    return {"ok": True, "config": cfg, "details": details, "patched": patched}


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

    if action not in ("stop", "start", "restart", "kill_claude", "restart_hxa", "upgrade"):
        raise HTTPException(status_code=400, detail="Invalid action. Use: stop, start, restart, kill_claude, restart_hxa, upgrade")

    container_name = _get_container_name(instance_id, product)

    # For compose operations, resolve compose file and project
    compose_file = row["compose_file"] or ""
    runtime_dir = row["runtime_dir"] or str(RUNTIME_ROOT / instance_id)
    project = row["compose_project"] or _get_compose_project(instance_id, product)

    if not compose_file:
        found = _find_compose_file(instance_id)
        if found:
            compose_file = str(found)

    if action == "upgrade":
        if product != "openclaw":
            return {"ok": False, "action": action, "detail": "Upgrade only supported for OpenClaw."}
        import os as _os
        env_file = _os.path.join(runtime_dir, ".env") if runtime_dir else ""
        # docker compose pull + up -d (proper image upgrade, not npm i -g)
        base_cmd = ["docker", "compose", "-f", compose_file, "-p", project]
        if env_file and _os.path.exists(env_file):
            base_cmd += ["--env-file", env_file]
        rc, out = _docker_run(base_cmd + ["pull"], timeout=180, cwd=runtime_dir)
        if rc != 0:
            return {"ok": False, "action": action, "detail": out[-2000:]}
        rc2, out2 = _docker_run(base_cmd + ["up", "-d"], timeout=120, cwd=runtime_dir)
        # Get new version
        rc3, ver = _docker_run(["docker", "exec", container_name, "openclaw", "--version"])
        new_ver = ver.strip() if rc3 == 0 else "unknown"
        return {"ok": rc2 == 0, "action": action, "detail": (out + "\n" + out2)[-2000:], "new_version": new_ver}

    if action == "restart_hxa":
        # Restart hxa-connect to make bot online in Hub
        if product == "zylos":
            rc, out = _docker_run(["docker", "exec", container_name, "pm2", "restart", "zylos-hxa-connect"])
            if rc != 0 and "not found" in out.lower():
                eco = "/home/zylos/zylos/.claude/skills/hxa-connect/ecosystem.config.cjs"
                rc, out = _docker_run(["docker", "exec", container_name, "pm2", "start", eco])
        else:
            # OpenClaw gateway embeds hxa-connect — restart the whole container
            rc, out = _docker_run(["docker", "restart", container_name])
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


# ---------------------------------------------------------------------------
#  Docker container management (orphan detection & cleanup)
# ---------------------------------------------------------------------------

@router.get("/docker-containers")
def list_docker_containers(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List ALL hire_/zylos_ Docker containers, match with DB, detect orphans."""
    _require_admin(current_user)

    # 1. Get all relevant containers
    raw_containers: list[dict] = []
    for prefix in ("hire_", "zylos_"):
        rc, out = _docker_run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}", "--filter", f"name={prefix}"],
            timeout=10,
        )
        if rc == 0 and out.strip():
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    raw_containers.append({"name": parts[0], "state": parts[1], "status": parts[2]})

    # 2. Get all instances from DB with owner info
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT i.id, i.name, i.product, i.owner_id, i.install_state,
                  u.email AS owner_email, u.name AS owner_name
           FROM instances i JOIN users u ON i.owner_id = u.id"""
    )
    db_instances = cursor.fetchall()
    cursor.close()

    # Build compose_project → instance mapping
    project_to_inst: dict[str, dict] = {}
    inst_ids_in_db: set[str] = set()
    for inst in db_instances:
        inst_id = inst["id"]
        product = inst["product"] or "openclaw"
        proj = _get_compose_project(inst_id, product)
        project_to_inst[proj] = inst
        inst_ids_in_db.add(inst_id)

    # 3. Group containers by project
    groups: dict[str, dict] = {}  # project → group info
    for c in raw_containers:
        name = c["name"]
        # Determine product and project from container name
        if name.startswith("zylos_"):
            # zylos_{instance_id} — the entire name IS the project
            project = name
            product = "zylos"
        elif "-openclaw-" in name:
            # hire_XXXX-openclaw-gateway-1 → project = hire_XXXX
            project = name.split("-openclaw-")[0]
            product = "openclaw"
        else:
            # Other hire_ container (maybe cli or unknown)
            project = name.rsplit("-", 2)[0] if "-" in name else name
            product = "unknown"

        if project not in groups:
            groups[project] = {
                "project": project,
                "containers": [],
                "product": product,
                "instance_id": None,
                "instance_name": None,
                "owner_email": None,
                "install_state": None,
                "runtime_dir": None,
                "runtime_exists": False,
                "is_orphan": True,
            }
        groups[project]["containers"].append({
            "name": name,
            "state": c["state"],
            "status": c["status"],
        })

    # 4. Match groups to DB instances
    for proj, group in groups.items():
        inst = project_to_inst.get(proj)
        if inst:
            inst_id = inst["id"]
            rt_dir = str(RUNTIME_ROOT / inst_id)
            group["instance_id"] = inst_id
            group["instance_name"] = inst["name"]
            group["owner_email"] = inst["owner_email"]
            group["install_state"] = inst["install_state"]
            group["runtime_dir"] = rt_dir
            group["runtime_exists"] = (RUNTIME_ROOT / inst_id).is_dir()
            group["is_orphan"] = False

    # 5. For orphan groups, try to find runtime dir by scanning RUNTIME_ROOT
    if RUNTIME_ROOT.is_dir():
        for proj, group in groups.items():
            if not group["is_orphan"] or group["runtime_dir"]:
                continue
            # Try to match project to a runtime dir
            for d in RUNTIME_ROOT.iterdir():
                if not d.is_dir():
                    continue
                # Check if this dir's compose project matches
                for prod in ("openclaw", "zylos"):
                    if _get_compose_project(d.name, prod) == proj:
                        group["runtime_dir"] = str(d)
                        group["runtime_exists"] = True
                        break
                if group["runtime_dir"]:
                    break

    # 6. Also find orphan runtime dirs (no matching container)
    matched_runtime_dirs: set[str] = set()
    for g in groups.values():
        if g["runtime_dir"]:
            matched_runtime_dirs.add(g["runtime_dir"])

    orphan_dirs: list[dict] = []
    if RUNTIME_ROOT.is_dir():
        for d in RUNTIME_ROOT.iterdir():
            if not d.is_dir():
                continue
            dir_path = str(d)
            if dir_path in matched_runtime_dirs:
                continue
            inst_id = d.name
            if inst_id in inst_ids_in_db:
                continue  # Has DB record, just no container — not an orphan dir
            orphan_dirs.append({
                "project": f"dir:{inst_id}",
                "containers": [],
                "product": "unknown",
                "instance_id": None,
                "instance_name": None,
                "owner_email": None,
                "install_state": None,
                "runtime_dir": dir_path,
                "runtime_exists": True,
                "is_orphan": True,
            })

    # 7. Find "ghost" instances: in DB but no container at all
    matched_inst_ids = set()
    for g in groups.values():
        if g.get("instance_id"):
            matched_inst_ids.add(g["instance_id"])
    ghost_instances: list[dict] = []
    for inst in db_instances:
        inst_id = inst["id"]
        if inst_id in matched_inst_ids:
            continue
        product = inst["product"] or "openclaw"
        proj = _get_compose_project(inst_id, product)
        rt_dir = str(RUNTIME_ROOT / inst_id)
        ghost_instances.append({
            "project": proj,
            "containers": [],
            "product": product,
            "instance_id": inst_id,
            "instance_name": inst["name"],
            "owner_email": inst.get("owner_email", ""),
            "owner_name": inst.get("owner_name", ""),
            "install_state": inst["install_state"],
            "runtime_dir": rt_dir,
            "runtime_exists": (RUNTIME_ROOT / inst_id).is_dir(),
            "is_orphan": False,
            "is_ghost": True,
        })

    # Sort: orphans first, then ghosts, then normal by project name
    result = sorted(groups.values(), key=lambda g: (not g["is_orphan"], g["project"]))
    result.extend(sorted(orphan_dirs, key=lambda g: g["project"]))
    result.extend(sorted(ghost_instances, key=lambda g: g["project"]))

    return {"groups": result}


class DockerCleanupRequest(BaseModel):
    project: str
    remove_runtime: bool = True


@router.post("/docker-cleanup")
def docker_cleanup(
    payload: DockerCleanupRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Clean up orphan Docker containers and runtime directories."""
    _require_admin(current_user)

    project = payload.project
    details: list[str] = []

    # Handle orphan runtime dir (no containers)
    if project.startswith("dir:"):
        inst_id = project[4:]
        rt_path = RUNTIME_ROOT / inst_id
        if payload.remove_runtime and rt_path.is_dir():
            shutil.rmtree(rt_path, ignore_errors=True)
            details.append(f"Runtime dir removed: {rt_path}")
        return {"ok": True, "details": details}

    # Safety: only allow hire_/zylos_ prefixes
    if not (project.startswith("hire_") or project.startswith("zylos_")):
        raise HTTPException(status_code=400, detail="Invalid project prefix.")

    # Find all containers for this project
    rc, out = _docker_run(
        ["docker", "ps", "-a", "--format", "{{.Names}}", "--filter", f"name={project}"],
        timeout=10,
    )
    container_names = [n.strip() for n in (out or "").splitlines() if n.strip()] if rc == 0 else []

    # Stop and remove containers
    for cname in container_names:
        _docker_run(["docker", "stop", cname], timeout=15)
        rc_rm, out_rm = _docker_run(["docker", "rm", "-f", cname], timeout=10)
        details.append(f"{cname}: {'removed' if rc_rm == 0 else out_rm}")

    # Find matching instance_id for DB cleanup
    matched_inst_id: str | None = None
    if RUNTIME_ROOT.is_dir():
        for d in RUNTIME_ROOT.iterdir():
            if not d.is_dir():
                continue
            for prod in ("openclaw", "zylos"):
                if _get_compose_project(d.name, prod) == project:
                    matched_inst_id = d.name
                    break
            if matched_inst_id:
                break
    # Also check DB directly by project name pattern
    if not matched_inst_id:
        # hire_inst_xxx → inst_xxx, zylos_inst_xxx → inst_xxx
        for prefix in ("hire_", "zylos_"):
            if project.startswith(prefix):
                candidate = project[len(prefix):]
                if not candidate.startswith("inst_"):
                    candidate = "inst_" + candidate
                cursor = db.cursor(dictionary=True)
                cursor.execute("SELECT id FROM instances WHERE id = %s", (candidate,))
                if cursor.fetchone():
                    matched_inst_id = candidate
                cursor.close()
                break

    # Remove runtime directory
    if payload.remove_runtime:
        removed = False
        if matched_inst_id:
            rt_path = RUNTIME_ROOT / matched_inst_id
            if rt_path.is_dir():
                shutil.rmtree(rt_path, ignore_errors=True)
                details.append(f"Runtime dir removed: {rt_path}")
                removed = True
        if not removed and RUNTIME_ROOT.is_dir():
            for d in RUNTIME_ROOT.iterdir():
                if not d.is_dir():
                    continue
                for prod in ("openclaw", "zylos"):
                    if _get_compose_project(d.name, prod) == project:
                        shutil.rmtree(d, ignore_errors=True)
                        details.append(f"Runtime dir removed: {d}")
                        removed = True
                        break
                if removed:
                    break
        if not removed:
            details.append("No matching runtime dir found")

    # Clean up DB records (ghost instances)
    if matched_inst_id:
        cursor = db.cursor()
        cursor.execute("DELETE FROM instance_configs WHERE instance_id = %s", (matched_inst_id,))
        cursor.execute("DELETE FROM install_events WHERE instance_id = %s", (matched_inst_id,))
        cursor.execute("DELETE FROM instances WHERE id = %s", (matched_inst_id,))
        cursor.close()
        details.append(f"DB records cleaned: {matched_inst_id}")

    return {"ok": True, "details": details}
