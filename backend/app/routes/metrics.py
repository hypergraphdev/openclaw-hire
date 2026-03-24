"""Instance metrics API — historical resource usage + connectivity tests."""
from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_current_user, get_db
from ..services.docker_utils import get_container_name, get_resource_usage, get_claude_info

router = APIRouter(prefix="/api/instances", tags=["metrics"])


def _check_owner(instance_id: str, user_id: str, db: sqlite3.Connection, is_admin: bool = False):
    """Verify user owns the instance or is admin."""
    if is_admin:
        row = db.execute("SELECT id FROM instances WHERE id = ?", (instance_id,)).fetchone()
    else:
        row = db.execute(
            "SELECT id FROM instances WHERE id = ? AND owner_id = ?",
            (instance_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found.")


@router.get("/{instance_id}/metrics")
def get_metrics(
    instance_id: str,
    hours: int = Query(24, ge=1, le=168),
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get historical metrics for an instance."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = db.execute(
        """SELECT cpu_percent, mem_used_mb, mem_total_mb, disk_usage_mb,
                  claude_running, claude_mem_mb, collected_at
           FROM instance_metrics
           WHERE instance_id = ? AND collected_at >= ?
           ORDER BY collected_at ASC""",
        (instance_id, cutoff),
    ).fetchall()

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
    db: sqlite3.Connection = Depends(get_db),
):
    """Get sparkline data (7 evenly-spaced points) for an instance metric."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    if field not in ("cpu_percent", "mem_used_mb"):
        raise HTTPException(status_code=400, detail="field must be cpu_percent or mem_used_mb")

    # Get last 7 data points
    rows = db.execute(
        f"""SELECT {field} as val, collected_at
            FROM instance_metrics
            WHERE instance_id = ? AND {field} IS NOT NULL
            ORDER BY collected_at DESC LIMIT 7""",
        (instance_id,),
    ).fetchall()

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
    db: sqlite3.Connection = Depends(get_db),
):
    """Run connectivity tests for HXA, Telegram, and Claude."""
    _check_owner(instance_id, current_user["id"], db, current_user.get("is_admin", False))

    inst = db.execute(
        "SELECT product FROM instances WHERE id = ?", (instance_id,)
    ).fetchone()
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
    cfg = db.execute(
        "SELECT telegram_bot_token FROM instance_configs WHERE instance_id = ?",
        (instance_id,),
    ).fetchone()
    tg_token = cfg["telegram_bot_token"] if cfg else None
    if not tg_token:
        # Check instances table fallback
        inst2 = db.execute("SELECT telegram_bot_token FROM instances WHERE id = ?", (instance_id,)).fetchone()
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
