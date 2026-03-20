from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user, get_db
from ..schemas import AdminUserInstancesResponse, InstanceResponse, UserResponse

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
        "SELECT * FROM instances WHERE owner_id = ? ORDER BY created_at DESC",
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
    """Global platform statistics visible to all users."""
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

    return {
        "total_users": total_users,
        "total_bots": total_bots,
        "running_bots": running_bots,
        "org_bots": org_bots,
    }
