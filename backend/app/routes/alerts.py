"""Alert notification API endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user, get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    unread: bool = False,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """List recent alerts. Optional ?unread=true to filter unread only."""
    limit = min(limit, 200)
    if unread:
        rows = db.execute(
            "SELECT * FROM alerts WHERE is_read = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    unread_count = db.execute("SELECT COUNT(*) as c FROM alerts WHERE is_read = 0").fetchone()["c"]

    return {
        "alerts": [dict(r) for r in rows],
        "unread_count": unread_count,
    }


def _safe_write(db: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    """Execute a write with retry on database locked."""
    import time
    for attempt in range(3):
        try:
            db.execute(sql, params)
            db.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < 2:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise


@router.post("/{alert_id}/read")
def mark_alert_read(
    alert_id: str,
    current_user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Mark a single alert as read."""
    row = db.execute("SELECT id FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found.")
    _safe_write(db, "UPDATE alerts SET is_read = 1 WHERE id = ?", (alert_id,))
    return {"ok": True}


@router.post("/read-all")
def mark_all_alerts_read(
    current_user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Mark all alerts as read."""
    _safe_write(db, "UPDATE alerts SET is_read = 1 WHERE is_read = 0")
    return {"ok": True}
