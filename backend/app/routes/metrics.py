"""Instance metrics API — historical resource usage + connectivity tests."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_current_user, get_db
from ..services.docker_utils import docker_run, get_container_name, get_resource_usage, get_claude_info

router = APIRouter(prefix="/api/instances", tags=["metrics"])


def _check_owner(instance_id: str, user_id: str, db, is_admin: bool = False):
    """Verify user owns the instance or is admin."""
    if is_admin:
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT id FROM instances WHERE id = %s", (instance_id,))
        row = _cur.fetchone()
        _cur.close()
    else:
        _cur = db.cursor(dictionary=True)
        _cur.execute(
            "SELECT id FROM instances WHERE id = %s AND owner_id = %s",
            (instance_id, user_id),
        )
        row = _cur.fetchone()
        _cur.close()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")


@router.get("/{instance_id}/metrics")
def get_metrics(
    instance_id: str,
    hours: int = Query(24, ge=1, le=168),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get historical metrics for an instance."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    _cur = db.cursor(dictionary=True)
    _cur.execute(
        """SELECT cpu_percent, mem_used_mb, mem_total_mb, disk_usage_mb,
                  claude_running, claude_mem_mb, collected_at
           FROM instance_metrics
           WHERE instance_id = %s AND collected_at >= %s
           ORDER BY collected_at ASC""",
        (instance_id, cutoff),
    )
    rows = _cur.fetchall()
    _cur.close()

    metrics = [dict(r) for r in rows]

    # Summary
    cpus = [m["cpu_percent"] for m in metrics if m["cpu_percent"] is not None]
    mems = [m["mem_used_mb"] for m in metrics if m["mem_used_mb"] is not None]

    summary = {
        "avg_cpu": round(sum(cpus) / len(cpus), 2) if cpus else 0,
        "max_cpu": round(max(cpus), 2) if cpus else 0,
        "avg_mem": round(sum(mems) / len(mems)) if mems else 0,
        "max_mem": max(mems) if mems else 0,
        "data_points": len(metrics),
    }

    return {"metrics": metrics, "summary": summary}


@router.get("/{instance_id}/metrics/sparkline")
def get_sparkline(
    instance_id: str,
    field: str = Query("cpu_percent"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get sparkline data (7 evenly-spaced points) for an instance metric."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    if field not in ("cpu_percent", "mem_used_mb"):
        raise HTTPException(status_code=400, detail="field must be cpu_percent or mem_used_mb")

    # Get last 7 data points
    _cur = db.cursor(dictionary=True)
    _cur.execute(
        f"""SELECT {field} as val, collected_at
            FROM instance_metrics
            WHERE instance_id = %s AND {field} IS NOT NULL
            ORDER BY collected_at DESC LIMIT 7""",
        (instance_id,),
    )
    rows = _cur.fetchall()
    _cur.close()

    values = [r["val"] for r in reversed(rows)]
    labels = [r["collected_at"][-8:-3] for r in reversed(rows)]  # HH:MM

    # Pad to 7 if less
    while len(values) < 7:
        values.insert(0, 0)
        labels.insert(0, "")

    return {"values": values, "labels": labels}


@router.post("/{instance_id}/connectivity-test")
def connectivity_test(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Run connectivity tests for HXA, Telegram, and Claude."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    _cur = db.cursor(dictionary=True)
    _cur.execute("SELECT product FROM instances WHERE id = %s", (instance_id,))
    inst = _cur.fetchone()
    _cur.close()
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = inst["product"]
    container = get_container_name(instance_id, product)
    results: dict = {}

    # Test Claude process
    import time
    t0 = time.time()
    claude = get_claude_info(container)
    elapsed = round((time.time() - t0) * 1000)
    results["claude"] = {
        "ok": claude["running"],
        "elapsed_ms": elapsed,
        "detail": f"PID {claude['pid']}, {claude.get('memory_mb', '?')}MB" if claude["running"] else None,
        "error": "Claude not running" if not claude["running"] else None,
    }

    # Test HXA connection
    from .admin_hxa import _get_agent_token
    from ..database import get_setting
    token = _get_agent_token(instance_id)
    hub_url = get_setting("hxa_hub_url", "https://www.ucai.net/connect").rstrip("/")
    if token:
        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"{hub_url}/api/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                me = json.loads(resp.read().decode())
            elapsed = round((time.time() - t0) * 1000)
            online = me.get("online", False)
            results["hxa"] = {
                "ok": True,
                "elapsed_ms": elapsed,
                "detail": f"{me.get('name', '?')} ({'在线' if online else '离线'})",
            }
        except Exception as e:
            elapsed = round((time.time() - t0) * 1000)
            results["hxa"] = {"ok": False, "elapsed_ms": elapsed, "error": str(e)[:100]}
    else:
        results["hxa"] = {"ok": False, "elapsed_ms": 0, "error": "No agent token configured"}

    # Test Telegram
    _cur = db.cursor(dictionary=True)
    _cur.execute(
        "SELECT telegram_bot_token FROM instance_configs WHERE instance_id = %s",
        (instance_id,),
    )
    cfg = _cur.fetchone()
    _cur.close()
    tg_token = cfg["telegram_bot_token"] if cfg else None
    if not tg_token:
        # Check instances table fallback
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT telegram_bot_token FROM instances WHERE id = %s", (instance_id,))
        inst2 = _cur.fetchone()
        _cur.close()
        tg_token = inst2["telegram_bot_token"] if inst2 and inst2["telegram_bot_token"] else None

    if tg_token:
        t0 = time.time()
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{tg_token}/getMe")
            with urllib.request.urlopen(req, timeout=5) as resp:
                tg_data = json.loads(resp.read().decode())
            elapsed = round((time.time() - t0) * 1000)
            if tg_data.get("ok"):
                bot_name = tg_data.get("result", {}).get("username", "?")
                results["telegram"] = {"ok": True, "elapsed_ms": elapsed, "detail": f"@{bot_name}"}
            else:
                results["telegram"] = {"ok": False, "elapsed_ms": elapsed, "error": tg_data.get("description", "Unknown")}
        except Exception as e:
            elapsed = round((time.time() - t0) * 1000)
            results["telegram"] = {"ok": False, "elapsed_ms": elapsed, "error": str(e)[:100]}
    else:
        results["telegram"] = {"ok": False, "elapsed_ms": 0, "error": "No Telegram token configured"}

    return results


# ---------------------------------------------------------------------------
#  Agent activity (Claude + pm2 services + activity-monitor state)
# ---------------------------------------------------------------------------

def _parse_pm2_jlist(raw: str) -> list[dict]:
    """Parse pm2 jlist JSON output into a clean service list."""
    try:
        procs = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []

    services: list[dict] = []
    for p in procs:
        name = p.get("name", "unknown")
        pm2_env = p.get("pm2_env", {})
        monit = p.get("monit", {})

        status = pm2_env.get("status", "unknown")
        uptime_ms = pm2_env.get("pm_uptime", 0)
        restarts = pm2_env.get("restart_time", 0)
        memory_bytes = monit.get("memory", 0)

        # Human-readable uptime
        import time as _time
        now_ms = int(_time.time() * 1000)
        elapsed_ms = max(0, now_ms - uptime_ms) if uptime_ms else 0
        elapsed_s = elapsed_ms // 1000
        if elapsed_s < 60:
            uptime_str = f"{elapsed_s}s"
        elif elapsed_s < 3600:
            uptime_str = f"{elapsed_s // 60}m"
        elif elapsed_s < 86400:
            uptime_str = f"{elapsed_s // 3600}h"
        else:
            uptime_str = f"{elapsed_s // 86400}d"

        services.append({
            "name": name,
            "status": status,
            "uptime": uptime_str if status == "online" else "-",
            "memory_mb": round(memory_bytes / (1024 * 1024), 1) if memory_bytes else 0,
            "restarts": restarts,
        })

    return services


def _determine_state(claude_running: bool, services: list[dict], activity_state: str | None) -> str:
    """Determine overall agent state: idle, busy, waiting, offline."""
    # If explicit activity-monitor state exists, use it
    if activity_state and activity_state in ("idle", "busy", "waiting"):
        return activity_state

    if not claude_running:
        # Check if any pm2 service is online
        any_online = any(s["status"] == "online" for s in services)
        return "waiting" if any_online else "offline"

    return "idle"


@router.get("/{instance_id}/agent-activity")
def agent_activity(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get real-time agent activity: Claude process, pm2 services, overall state."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    _cur = db.cursor(dictionary=True)
    _cur.execute("SELECT product FROM instances WHERE id = %s", (instance_id,))
    inst = _cur.fetchone()
    _cur.close()
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found.")

    product = inst["product"]
    container = get_container_name(instance_id, product)

    # 1. Claude process info
    claude = get_claude_info(container)

    # 2. pm2 services
    rc, pm2_raw = docker_run(
        ["docker", "exec", container, "bash", "-c", "pm2 jlist 2>/dev/null"],
        timeout=8,
    )
    services = _parse_pm2_jlist(pm2_raw) if rc == 0 else []

    # 3. Activity monitor state (Zylos only)
    activity_state: str | None = None
    if product == "zylos":
        rc_s, state_raw = docker_run(
            ["docker", "exec", container, "cat",
             "/home/zylos/zylos/activity-monitor/state.json"],
            timeout=5,
        )
        if rc_s == 0 and state_raw.strip():
            try:
                state_obj = json.loads(state_raw)
                activity_state = state_obj.get("state")
            except (json.JSONDecodeError, TypeError):
                pass

    # 4. Determine overall state
    state = _determine_state(claude["running"], services, activity_state)

    return {
        "claude": {
            "running": claude["running"],
            "pid": claude["pid"],
            "uptime_seconds": claude["uptime_seconds"],
            "memory_mb": claude["memory_mb"],
        },
        "services": services,
        "state": state,
    }
