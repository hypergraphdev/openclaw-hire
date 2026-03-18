from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user, get_db
from ..schemas import (
    PRODUCT_MAP,
    ConfigureTelegramRequest,
    ConfigureTelegramResponse,
    CreateInstanceRequest,
    InstallEventResponse,
    InstanceConfigResponse,
    InstanceDetailResponse,
    InstanceLogsResponse,
    InstanceResponse,
)
from ..services.install_service import (
    _HUB_URL,
    _ORG_ID,
    compose_logs,
    configure_instance_telegram,
    restart_instance,
    stop_instance,
    sync_instance_status,
    trigger_install,
    uninstall_instance,
)

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


def _require_compose(inst: dict) -> tuple[str, str, str]:
    compose_file = inst.get("compose_file")
    project = inst.get("compose_project")
    runtime_dir = inst.get("runtime_dir")
    if not compose_file or not project or not runtime_dir:
        raise HTTPException(status_code=409, detail="Instance has not completed initial install; compose metadata missing.")
    return compose_file, project, runtime_dir


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
    cfg = db.execute(
        "SELECT plugin_name, hub_url, org_id, org_token, allow_group, allow_dm, configured_at FROM instance_configs WHERE instance_id = ?",
        (instance_id,),
    ).fetchone()
    config = None
    if cfg:
        c = dict(cfg)
        config = InstanceConfigResponse(
            plugin_name=c.get("plugin_name"),
            hub_url=c.get("hub_url"),
            org_id=c.get("org_id"),
            org_token=c.get("org_token"),
            allow_group=bool(c.get("allow_group", 1)),
            allow_dm=bool(c.get("allow_dm", 1)),
            configured_at=c.get("configured_at"),
        )

    return InstanceDetailResponse(
        instance=InstanceResponse(**inst),
        install_timeline=[InstallEventResponse(**dict(e)) for e in events],
        config=config,
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
        "UPDATE instances SET install_state = 'pulling', updated_at = ?, status='installing' WHERE id = ?",
        (now, instance_id),
    )
    db.commit()

    trigger_install(instance_id)

    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return _row_to_instance(row)


@router.post("/{instance_id}/stop", response_model=InstanceResponse)
def stop_instance_api(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    compose_file, project, runtime_dir = _require_compose(inst)
    ok, out = stop_instance(instance_id, compose_file, project, runtime_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out[:500])
    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return _row_to_instance(row)


@router.post("/{instance_id}/restart", response_model=InstanceResponse)
def restart_instance_api(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    compose_file, project, runtime_dir = _require_compose(inst)
    ok, out = restart_instance(instance_id, compose_file, project, runtime_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out[:500])
    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return _row_to_instance(row)


@router.post("/{instance_id}/uninstall", response_model=InstanceResponse)
def uninstall_instance_api(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    compose_file, project, runtime_dir = _require_compose(inst)
    ok, out = uninstall_instance(instance_id, compose_file, project, runtime_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out[:500])
    row = db.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
    return _row_to_instance(row)


@router.get("/{instance_id}/logs", response_model=InstanceLogsResponse)
def instance_logs(
    instance_id: str,
    lines: int = 200,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceLogsResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    compose_file, project, runtime_dir = _require_compose(inst)
    rc, out = compose_logs(compose_file, project, runtime_dir, lines=max(20, min(lines, 2000)))
    if rc != 0:
        raise HTTPException(status_code=500, detail=out[:500])
    return InstanceLogsResponse(instance_id=instance_id, compose_project=project, logs=out)


@router.post("/{instance_id}/configure", response_model=ConfigureTelegramResponse)
def configure_instance(
    instance_id: str,
    payload: ConfigureTelegramRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> ConfigureTelegramResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    compose_file, project, runtime_dir = _require_compose(inst)

    ok, message, org_token, plugin = configure_instance_telegram(
        instance_id,
        payload.telegram_bot_token,
        inst["product"],
        runtime_dir,
        compose_file,
        project,
    )

    if not ok:
        duplicate_hint = "already used by instance" in (message or "")
        raise HTTPException(status_code=409 if duplicate_hint else 500, detail=message)

    return ConfigureTelegramResponse(
        instance_id=instance_id,
        plugin_name=plugin,
        hub_url=_HUB_URL,
        org_id=_ORG_ID,
        org_token=org_token,
        message=f"Telegram bot configured. Plugin: {plugin}. DMs and group messages enabled.",
    )


@router.delete("/{instance_id}")
def delete_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, str]:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)

    # best effort teardown of runtime containers/data
    compose_file = inst.get("compose_file")
    project = inst.get("compose_project")
    runtime_dir = inst.get("runtime_dir")
    if compose_file and project and runtime_dir:
        uninstall_instance(instance_id, compose_file, project, runtime_dir)

    if runtime_dir:
        shutil.rmtree(Path(runtime_dir), ignore_errors=True)

    db.execute("DELETE FROM install_events WHERE instance_id = ?", (instance_id,))
    db.execute("DELETE FROM instances WHERE id = ? AND owner_id = ?", (instance_id, current_user["id"]))
    db.commit()
    return {"status": "deleted", "instance_id": instance_id}
