"""Alert notification API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_current_user, get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    unread: bool = False,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """List recent alerts scoped to user's instances. Admin sees all."""
    limit = min(limit, 200)
    is_admin = bool(current_user.get("is_admin"))
    user_id = current_user["id"]

    cursor = db.cursor(dictionary=True)
    if is_admin:
        # Admin sees all alerts
        where = "WHERE is_read = 0" if unread else ""
        cursor.execute(f"SELECT * FROM alerts {where} ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) as c FROM alerts WHERE is_read = 0")
        unread_count = cursor.fetchone()["c"]
    else:
        # Regular user: only alerts for their own instances
        base = """FROM alerts a JOIN instances i ON a.instance_id = i.id WHERE i.owner_id = %s"""
        if unread:
            base += " AND a.is_read = 0"
        cursor.execute(f"SELECT a.* {base} ORDER BY a.created_at DESC LIMIT %s", (user_id, limit))
        rows = cursor.fetchall()
        cursor.execute(f"SELECT COUNT(*) as c {base} AND a.is_read = 0", (user_id,))
        unread_count = cursor.fetchone()["c"]
    cursor.close()

    return {
        "alerts": [dict(r) for r in rows],
        "unread_count": unread_count,
    }


@router.post("/{alert_id}/read")
def mark_alert_read(
    alert_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Mark a single alert as read."""
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id FROM alerts WHERE id = %s", (alert_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        raise HTTPException(status_code=404, detail="Alert not found.")
    cursor.execute("UPDATE alerts SET is_read = 1 WHERE id = %s", (alert_id,))
    cursor.close()
    return {"ok": True}


@router.post("/read-all")
def mark_all_alerts_read(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Mark all alerts as read."""
    cursor = db.cursor()
    cursor.execute("UPDATE alerts SET is_read = 1 WHERE is_read = 0")
    cursor.close()
    return {"ok": True}
