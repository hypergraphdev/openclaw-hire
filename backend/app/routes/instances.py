from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user, get_db
from ..schemas import (
    PRODUCT_MAP,
    CreateInstanceRequest,
    InstallEventResponse,
    InstanceDetailResponse,
    InstanceResponse,
)
from ..services.install_service import sync_instance_status, trigger_install

router = APIRouter(prefix="/api/instances", tags=["instances"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_instance(row) -> InstanceResponse:
    return InstanceResponse(**dict(row))


def _get_instance_or_404(instance_id: str, owner_id: str, db: sqlite3.Connection) -> dict:
    row = db.execute(
        "SELECT * FROM instances WHERE id = ? AND owner_id = ?",
        (instance_id, owner_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    return dict(row)


@router.post("", response_model=InstanceResponse, status_code=status.HTTP_201_CREATED)
def create_instance(
    payload: CreateInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceResponse:
    product = PRODUCT_MAP[payload.product]
    instance_id = f"inst_{uuid4().hex[:12]}"
    now = _utc_now()

    db.execute(
        """
        INSERT INTO instances (id, owner_id, name, product, repo_url, status, install_state, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', 'idle', ?, ?)
        """,
        (instance_id, current_user["id"], payload.name, payload.product, product.repo_url, now, now),
    )
    db.commit()

    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return _row_to_instance(row)


@router.get("", response_model=list[InstanceResponse])
def list_instances(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> list[InstanceResponse]:
    rows = db.execute(
        "SELECT * FROM instances WHERE owner_id = ? ORDER BY created_at DESC",
        (current_user["id"],),
    ).fetchall()

    for row in rows:
        if row["compose_project"] and row["install_state"] in {"starting", "running", "failed"}:
            sync_instance_status(row["id"])

    rows = db.execute(
        "SELECT * FROM instances WHERE owner_id = ? ORDER BY created_at DESC",
        (current_user["id"],),
    ).fetchall()
    return [_row_to_instance(row) for row in rows]


@router.get("/{instance_id}", response_model=InstanceDetailResponse)
def get_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceDetailResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    if inst.get("compose_project") and inst.get("install_state") in {"starting", "running", "failed"}:
        sync_instance_status(instance_id)
        inst = _get_instance_or_404(instance_id, current_user["id"], db)

    events = db.execute(
        "SELECT * FROM install_events WHERE instance_id = ? ORDER BY id ASC",
        (instance_id,),
    ).fetchall()
    return InstanceDetailResponse(
        instance=InstanceResponse(**inst),
        install_timeline=[InstallEventResponse(**dict(e)) for e in events],
    )


@router.post("/{instance_id}/install", response_model=InstanceResponse)
def start_install(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)

    if inst["install_state"] not in ("idle", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Install already in progress or completed (state: {inst['install_state']}).",
        )

    now = _utc_now()
    db.execute(
        "UPDATE instances SET install_state = 'pulling', updated_at = ? WHERE id = ?",
        (now, instance_id),
    )
    db.commit()

    trigger_install(instance_id)

    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return _row_to_instance(row)
