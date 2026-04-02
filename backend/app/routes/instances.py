from __future__ import annotations

import json
import os
import shutil
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel as _BaseModel

from ..database import site_base_url, runtime_root
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
    _get_hub_url,
    _ORG_ID,
    _safe_agent_name,
    compose_logs,
    configure_instance_telegram,
    configure_telegram_only,
    configure_hxa_only,
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
    d = dict(row)
    # Convert raw token fields to safe boolean + hint - never expose full token
    token = d.pop("telegram_bot_token", None)
    d["is_telegram_configured"] = bool(token)
    d["telegram_token_hint"] = token[-4:] if token else None
    d.pop("org_token", None)  # remove sensitive field entirely
    return InstanceResponse(**d)


def _get_instance_or_404(instance_id: str, owner_id: str, db, *, is_admin: bool = False) -> dict:
    # Admin can view any instance; also try admin fallback if owner check fails
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM instances WHERE id = %s AND owner_id = %s",
        (instance_id, owner_id),
    )
    row = cursor.fetchone()
    if row is None and is_admin:
        cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
        row = cursor.fetchone()
    cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Instance not found.")
    return dict(row)


def _require_compose(inst: dict) -> tuple[str, str, str]:
    compose_file = inst.get("compose_file")
    project = inst.get("compose_project")
    runtime_dir = inst.get("runtime_dir")
    if not compose_file or not project or not runtime_dir:
        raise HTTPException(status_code=409, detail="Instance has not completed initial install; compose metadata missing.")
    # Convert host paths to container paths if running in Docker
    if not os.path.exists(runtime_dir):
        from ..database import runtime_root
        _rt = runtime_root()  # Container-internal runtime root (e.g. /app/runtime)
        inst_id = inst.get("id", "")
        container_rt = os.path.join(_rt, inst_id)
        if os.path.exists(container_rt):
            runtime_dir = container_rt
            # Also fix compose_file path
            compose_basename = os.path.basename(compose_file)
            compose_file = os.path.join(container_rt, compose_basename)
    return compose_file, project, runtime_dir


def _resolve_org_names(org_ids: set[str]) -> dict[str, str]:
    """Resolve org_ids to org_names. Try Hub admin API, fall back to local DB."""
    if not org_ids:
        return {}
    result = {}
    # Try admin API
    try:
        from .admin_hxa import _hub_admin_request
        orgs = _hub_admin_request("GET", "/api/orgs")
        for o in (orgs or []):
            if o.get("id") in org_ids:
                result[o["id"]] = o.get("name", "")
    except Exception:
        pass
    # Fall back to local org_secrets for any missing
    missing = org_ids - set(result.keys())
    if missing:
        from ..database import get_connection
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            placeholders = ",".join("%s" for _ in missing)
            cursor.execute(f"SELECT org_id, org_name FROM org_secrets WHERE org_id IN ({placeholders})", list(missing))
            rows = cursor.fetchall()
            cursor.close()
            for r in rows:
                result[r["org_id"]] = r["org_name"]
        finally:
            conn.close()
    return result


def _merge_instance_config_fields(inst: dict, db) -> dict:
    """Backfill list/detail fields from instance_configs when legacy rows are partially empty."""
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT telegram_bot_token, org_token, agent_name, org_id FROM instance_configs WHERE instance_id = %s",
        (inst["id"],),
    )
    cfg = cursor.fetchone()
    cursor.close()
    if cfg:
        c = dict(cfg)
        if not inst.get("telegram_bot_token") and c.get("telegram_bot_token"):
            inst["telegram_bot_token"] = c.get("telegram_bot_token")
        if not inst.get("org_token") and c.get("org_token"):
            inst["org_token"] = c.get("org_token")
        if not inst.get("agent_name") and c.get("agent_name"):
            inst["agent_name"] = c.get("agent_name")
        if not inst.get("org_id") and c.get("org_id"):
            inst["org_id"] = c.get("org_id")
    return inst


@router.post("", response_model=InstanceResponse, status_code=status.HTTP_201_CREATED)
def create_instance(
    payload: CreateInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> InstanceResponse:
    product = PRODUCT_MAP[payload.product]
    if not bool(current_user.get("is_admin", 0)):
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS c FROM instances WHERE owner_id = %s", (current_user["id"],))
        cnt = cursor.fetchone()["c"]
        cursor.close()
        if cnt >= 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Regular users can only create one instance. Contact admin for quota increase.",
            )

    instance_id = f"inst_{uuid4().hex[:12]}"
    now = _utc_now()

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """
        INSERT INTO instances (id, owner_id, name, product, repo_url, status, install_state, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'active', 'idle', %s, %s)
        """,
        (instance_id, current_user["id"], payload.name, payload.product, product.repo_url, now, now),
    )
    cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
    row = cursor.fetchone()
    cursor.close()
    return _row_to_instance(row)


@router.get("", response_model=list[InstanceResponse])
def list_instances(
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> list[InstanceResponse]:
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM instances WHERE owner_id = %s ORDER BY created_at DESC",
        (current_user["id"],),
    )
    rows = cursor.fetchall()
    cursor.close()

    # Sync at most one stale instance per request to avoid DB lock contention
    import time
    _now = time.time()
    for row in rows:
        if row["compose_project"] and row["install_state"] in {"starting", "running", "failed"}:
            # Only sync if last update was >30s ago
            updated = row["updated_at"] or ""
            if updated:
                try:
                    from datetime import datetime
                    age = _now - datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
                    if age < 30:
                        continue
                except Exception:
                    pass
            try:
                sync_instance_status(row["id"])
            except Exception:
                pass  # Don't let sync errors break listing
            break  # Only sync one per request

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM instances WHERE owner_id = %s ORDER BY created_at DESC",
        (current_user["id"],),
    )
    rows = cursor.fetchall()
    cursor.close()
    merged = [_merge_instance_config_fields(dict(row), db) for row in rows]

    # Resolve org_id → org_name for all instances
    org_ids = {m["org_id"] for m in merged if m.get("org_id")}
    org_name_map = _resolve_org_names(org_ids)

    # Convert to response: drop sensitive fields, add bool flag
    results = []
    for m in merged:
        m["is_telegram_configured"] = bool(m.pop("telegram_bot_token", None))
        m.pop("org_token", None)
        if m.get("org_id"):
            m["org_name"] = org_name_map.get(m["org_id"], "")
        results.append(InstanceResponse(**m))
    return results


@router.get("/{instance_id}")
def get_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    is_admin = bool(current_user.get("is_admin"))
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=is_admin)
    if inst.get("compose_project") and inst.get("install_state") in {"starting", "running", "failed"}:
        try:
            sync_instance_status(instance_id)
        except Exception:
            pass
        inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=is_admin)

    inst = _merge_instance_config_fields(inst, db)

    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM install_events WHERE instance_id = %s ORDER BY id ASC",
        (instance_id,),
    )
    events = cursor.fetchall()
    cursor.execute(
        "SELECT plugin_name, hub_url, org_id, org_token, agent_name, allow_group, allow_dm, configured_at FROM instance_configs WHERE instance_id = %s",
        (instance_id,),
    )
    cfg = cursor.fetchone()
    cursor.close()
    config = None
    if cfg:
        c = dict(cfg)
        org_name = ""
        if c.get("org_id"):
            names = _resolve_org_names({c["org_id"]})
            org_name = names.get(c["org_id"], "")
        config = InstanceConfigResponse(
            plugin_name=c.get("plugin_name"),
            hub_url=c.get("hub_url"),
            org_id=c.get("org_id"),
            org_name=org_name,
            org_token=c.get("org_token"),
            agent_name=c.get("agent_name"),
            allow_group=bool(c.get("allow_group", 1)),
            allow_dm=bool(c.get("allow_dm", 1)),
            configured_at=c.get("configured_at"),
        )

    # Check WeChat plugin install status (OpenClaw or Zylos)
    cursor2 = db.cursor(dictionary=True)
    cursor2.execute(
        "SELECT status FROM marketplace_installs WHERE instance_id = %s AND item_id IN ('weixin-plugin', 'weixin-zylos-plugin')",
        (instance_id,),
    )
    weixin_row = cursor2.fetchone()
    cursor2.close()
    is_weixin_installed = weixin_row["status"] == "installed" if weixin_row else False

    resp = InstanceDetailResponse(
        instance=_row_to_instance(inst),
        install_timeline=[InstallEventResponse(**dict(e)) for e in events],
        config=config,
    )
    # Attach extra fields not in the Pydantic model
    resp_dict = resp.dict() if hasattr(resp, "dict") else resp.model_dump()
    resp_dict["is_weixin_installed"] = is_weixin_installed
    # Check if any AI provider API key is configured
    from ..database import get_setting
    has_anthropic = bool(get_setting("anthropic_auth_token", ""))
    has_openai = bool(get_setting("openai_api_key", ""))
    resp_dict["api_key_configured"] = has_anthropic or has_openai

    # Check if container is actually running (for self-check button logic)
    try:
        from ..services.docker_utils import get_container_name as _gcn, get_container_info as _gci
        _cn = _gcn(instance_id, inst.get("product", "openclaw"))
        _ci = _gci(_cn)
        resp_dict["container_running"] = _ci.get("running", False)
    except Exception:
        resp_dict["container_running"] = False
    return resp_dict


@router.post("/{instance_id}/install", response_model=InstanceResponse)
def start_install(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))

    if inst["install_state"] not in ("idle", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Install already in progress or completed (state: {inst['install_state']}).",
        )

    now = _utc_now()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "UPDATE instances SET install_state = 'pulling', updated_at = %s, status='installing' WHERE id = %s",
        (now, instance_id),
    )

    trigger_install(instance_id)

    cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
    row = cursor.fetchone()
    cursor.close()
    return _row_to_instance(row)


@router.post("/{instance_id}/stop", response_model=InstanceResponse)
def stop_instance_api(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    compose_file, project, runtime_dir = _require_compose(inst)
    ok, out = stop_instance(instance_id, compose_file, project, runtime_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out[:500])
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
    row = cursor.fetchone()
    cursor.close()
    return _row_to_instance(row)


@router.post("/{instance_id}/restart", response_model=InstanceResponse)
def restart_instance_api(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    compose_file, project, runtime_dir = _require_compose(inst)
    ok, out = restart_instance(instance_id, compose_file, project, runtime_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out[:500])
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
    row = cursor.fetchone()
    cursor.close()
    return _row_to_instance(row)


@router.post("/{instance_id}/uninstall", response_model=InstanceResponse)
def uninstall_instance_api(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> InstanceResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    compose_file, project, runtime_dir = _require_compose(inst)
    ok, out = uninstall_instance(instance_id, compose_file, project, runtime_dir)
    if not ok:
        raise HTTPException(status_code=500, detail=out[:500])
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instances WHERE id = %s", (instance_id,))
    row = cursor.fetchone()
    cursor.close()
    return _row_to_instance(row)


@router.post("/{instance_id}/upgrade")
async def upgrade_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> dict:
    """Upgrade OpenClaw to latest version inside the container."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    if inst["product"] != "openclaw":
        raise HTTPException(status_code=400, detail="Upgrade is only supported for OpenClaw instances.")
    compose_file, project, runtime_dir = _require_compose(inst)
    container = f"{project}-openclaw-gateway-1"

    import asyncio, subprocess
    loop = asyncio.get_event_loop()

    env_file = os.path.join(runtime_dir, ".env")

    def _do_upgrade():
        logs = []
        # Step 1: docker compose pull (pulls latest image)
        pull_cmd = ["docker", "compose", "-f", compose_file, "-p", project]
        if os.path.exists(env_file):
            pull_cmd += ["--env-file", env_file]
        r1 = subprocess.run(pull_cmd + ["pull"], capture_output=True, text=True, timeout=180, cwd=runtime_dir)
        logs.append("=== pull ===\n" + (r1.stdout + r1.stderr).strip())
        if r1.returncode != 0:
            return r1.returncode, "\n".join(logs)

        # Step 2: docker compose up -d (recreates containers with new image)
        up_cmd = ["docker", "compose", "-f", compose_file, "-p", project]
        if os.path.exists(env_file):
            up_cmd += ["--env-file", env_file]
        r2 = subprocess.run(up_cmd + ["up", "-d"], capture_output=True, text=True, timeout=120, cwd=runtime_dir)
        logs.append("\n=== up -d ===\n" + (r2.stdout + r2.stderr).strip())

        return r2.returncode, "\n".join(logs)

    try:
        rc, output = await loop.run_in_executor(None, _do_upgrade)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Get new version
    try:
        vr = subprocess.run(
            ["docker", "exec", f"{project}-openclaw-gateway-1", "openclaw", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        new_ver = vr.stdout.strip() if vr.returncode == 0 else ""
    except Exception:
        new_ver = ""

    return {"ok": rc == 0, "output": output[-3000:], "new_version": new_ver}


@router.post("/{instance_id}/weixin-login")
def weixin_login(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Start WeChat login and stream output to a log file.
    Frontend polls GET /weixin-login-log to read QR code output."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")

    import os, subprocess, threading

    if product == "zylos":
        container = f"zylos_{instance_id}"
        # Clear accounts so plugin re-generates QR on restart
        subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             "rm -f /home/zylos/zylos/components/weixin/accounts.json; "
             "truncate -s 0 /home/zylos/zylos/components/weixin/logs/out.log 2>/dev/null; "
             "rm -f /home/zylos/zylos/components/weixin/accounts/*.json"],
            capture_output=True, timeout=10,
        )
        # Restart PM2 process to trigger new QR code
        subprocess.run(
            ["docker", "exec", container, "pm2", "restart", "zylos-weixin"],
            capture_output=True, timeout=15,
        )
        return {"ok": True, "message": "WeChat login started. Poll /weixin-login-log for QR code."}

    if product != "openclaw":
        raise HTTPException(status_code=400, detail="WeChat login not supported for this product.")

    compose_file, project, runtime_dir = _require_compose(inst)
    container = f"{project}-openclaw-gateway-1"

    # Write log to host-accessible file (same approach as marketplace: script + tee inside container)
    container_log = "/home/node/.openclaw/weixin-login.log"
    host_log = os.path.join(runtime_dir, "openclaw-config", "weixin-login.log")

    def _run_login():
        try:
            # Clear previous log
            subprocess.run(["docker", "exec", container, "sh", "-c", f"rm -f {container_log}; touch {container_log}"],
                           capture_output=True, timeout=10)
            # Run channels login via script (PTY for unbuffered) + tee to file
            proc = subprocess.Popen(
                ["docker", "exec", container, "script", "-qc",
                 f"openclaw channels login --channel openclaw-weixin 2>&1 | tee {container_log}",
                 "/dev/null"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            )
            import time
            deadline = time.time() + 600  # 10 min
            while time.time() < deadline:
                time.sleep(1)
                if proc.poll() is not None:
                    break
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as e:
            try:
                with open(host_log, "a") as f:
                    f.write(f"\nERROR: {e}\n")
            except Exception:
                pass

    thread = threading.Thread(target=_run_login, daemon=True)
    thread.start()
    return {"ok": True, "message": "WeChat login started. Poll /weixin-login-log for QR code."}


@router.get("/{instance_id}/weixin-login-log")
def weixin_login_log(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Read WeChat login log (QR code output)."""
    import os, subprocess
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")

    if product == "zylos":
        # Read PM2 log via docker exec
        container = f"zylos_{instance_id}"
        r = subprocess.run(
            ["docker", "exec", container, "tail", "-200", "/home/zylos/zylos/components/weixin/logs/out.log"],
            capture_output=True, text=True, timeout=10,
        )
        content = r.stdout if r.returncode == 0 else ""
    else:
        runtime_dir = inst.get("runtime_dir", f"{runtime_root()}/{instance_id}")
        host_log = os.path.join(runtime_dir, "openclaw-config", "weixin-login.log")
        try:
            content = open(host_log, "r", errors="replace").read()
        except FileNotFoundError:
            content = ""

    content = content.replace('\r\n', '\n').replace('\r', '')
    # Detect status
    status = "waiting"
    if "扫码成功" in content or "登录成功" in content or "连接成功" in content or "connected" in content.lower():
        status = "success"
    elif "ERROR" in content or "失败" in content:
        status = "failed"
    elif "二维码" in content or "扫描" in content or "liteapp.weixin" in content:
        status = "qr_ready"
    return {"log": content[-50000:], "status": status}


@router.get("/{instance_id}/logs", response_model=InstanceLogsResponse)
def instance_logs(
    instance_id: str,
    lines: int = 200,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> InstanceLogsResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
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
    db = Depends(get_db),
) -> ConfigureTelegramResponse:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    compose_file, project, runtime_dir = _require_compose(inst)

    ok, message, org_token, plugin, agent_name = configure_instance_telegram(
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
        hub_url=_get_hub_url(),
        org_id=_ORG_ID,
        org_token=org_token,
        agent_name=agent_name,
        message=f"Telegram bot configured. Plugin: {plugin}. DMs and group messages enabled.",
    )


@router.post("/{instance_id}/configure-telegram")
async def configure_telegram_endpoint(
    instance_id: str,
    payload: ConfigureTelegramRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> dict:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    compose_file, project, runtime_dir = _require_compose(inst)

    # Run blocking docker/pm2 ops in thread pool so other requests aren't blocked
    import asyncio
    loop = asyncio.get_event_loop()
    ok, message = await loop.run_in_executor(
        None,
        lambda: configure_telegram_only(
            instance_id, payload.telegram_bot_token, runtime_dir, compose_file, project,
            product=inst["product"],
        ),
    )
    if not ok:
        raise HTTPException(status_code=500, detail=message)

    now = _utc_now()
    plugin_name = "openclaw-hxa-connect" if inst["product"] == "openclaw" else "hxa-connect"
    cursor = db.cursor()
    cursor.execute(
        "UPDATE instances SET telegram_bot_token=%s, updated_at=%s WHERE id=%s",
        (payload.telegram_bot_token, now, instance_id),
    )
    cursor.execute(
        """
        INSERT INTO instance_configs (instance_id, telegram_bot_token, plugin_name, allow_group, allow_dm, configured_at, updated_at)
        VALUES (%s, %s, %s, 1, 1, %s, %s)
        ON DUPLICATE KEY UPDATE
          telegram_bot_token=VALUES(telegram_bot_token),
          plugin_name=VALUES(plugin_name),
          allow_group=1, allow_dm=1,
          configured_at=VALUES(configured_at),
          updated_at=VALUES(updated_at)
        """,
        (instance_id, payload.telegram_bot_token, plugin_name, now, now),
    )
    cursor.close()
    return {"ok": True, "message": message, "is_telegram_configured": True}


@router.post("/{instance_id}/configure-hxa")
async def configure_hxa_endpoint(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> dict:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    compose_file, project, runtime_dir = _require_compose(inst)

    # Check if HXA org is configured; auto-create via invite code if not
    from ..database import get_setting, set_setting, get_config, hxa_hub_url, get_connection
    org_secret = get_setting("hxa_org_secret", "")

    if not org_secret:
        # Try auto-bootstrap: create org via platform invite code (no admin_secret needed)
        invite_code = get_config("hxa_invite_code", "")
        hub = hxa_hub_url()
        if invite_code and hub:
            try:
                org_name = (current_user.get("name") or "default") + "'s Organization"
                import urllib.request
                req_data = json.dumps({"invite_code": invite_code, "name": org_name}).encode()
                req = urllib.request.Request(
                    f"{hub}/api/platform/orgs",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode())
                new_org_id = result.get("org_id", "")
                new_org_secret = result.get("org_secret", "")
                if new_org_id and new_org_secret:
                    set_setting("hxa_org_id", new_org_id)
                    set_setting("hxa_org_secret", new_org_secret)
                    import datetime
                    now_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    conn2 = get_connection()
                    try:
                        cur2 = conn2.cursor()
                        cur2.execute(
                            "REPLACE INTO org_secrets (org_id, org_secret, org_name, created_at) VALUES (%s, %s, %s, %s)",
                            (new_org_id, new_org_secret, org_name, now_ts),
                        )
                        cur2.close()
                    finally:
                        conn2.close()
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"自动创建组织失败: {e}")
        else:
            raise HTTPException(
                status_code=400,
                detail="HXA 组织尚未配置。请在管理 → 全局配置中设置 Invite Code 或 Admin Secret，然后创建组织。",
            )

    # Run blocking docker/compose/registration ops in thread pool so other requests aren't blocked
    import asyncio
    from pathlib import Path
    # runtime_dir from DB may be host path; convert to container-internal path if needed
    _app_runtime = str(Path(__file__).resolve().parent.parent.parent / "runtime")
    container_runtime_dir = os.path.join(_app_runtime, instance_id) if not os.path.exists(runtime_dir) else runtime_dir

    loop = asyncio.get_event_loop()
    ok, message = await loop.run_in_executor(
        None,
        lambda: configure_hxa_only(
            instance_id, container_runtime_dir, project,
            product=inst["product"], compose_file=compose_file,
        ),
    )
    if not ok:
        raise HTTPException(status_code=500, detail=message)

    now = _utc_now()
    agent_name = _safe_agent_name(instance_id)
    plugin_name = "openclaw-hxa-connect" if inst["product"] == "openclaw" else "hxa-connect"
    cursor = db.cursor()
    cursor.execute(
        "UPDATE instances SET agent_name=%s, updated_at=%s WHERE id=%s",
        (agent_name, now, instance_id),
    )
    cursor.execute(
        """
        INSERT INTO instance_configs (instance_id, agent_name, plugin_name, hub_url, org_id, org_token, configured_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          agent_name=VALUES(agent_name),
          plugin_name=VALUES(plugin_name),
          hub_url=VALUES(hub_url),
          org_id=VALUES(org_id),
          org_token=COALESCE(VALUES(org_token), org_token),
          updated_at=VALUES(updated_at)
        """,
        (instance_id, agent_name, plugin_name, _get_hub_url(), _ORG_ID, None, now, now),
    )
    cursor.close()
    return {"ok": True, "message": message, "agent_name": agent_name}


class _RenameAgentRequest(_BaseModel):
    agent_name: str


@router.put("/{instance_id}/agent-name")
def rename_agent(
    instance_id: str,
    req: _RenameAgentRequest,
    current_user=Depends(get_current_user),
    db = Depends(get_db),
):
    """Rename instance's agent in HXA org (only if current name starts with hire_)."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    current_name = inst["agent_name"] or ""
    if not current_name.startswith("hire_"):
        raise HTTPException(status_code=400, detail="已改名的实例不允许再次修改。")

    new_name = req.agent_name.strip()
    if not new_name or len(new_name) < 2:
        raise HTTPException(status_code=400, detail="名称不能为空且至少2个字符。")
    # Auto-append _Bot suffix if missing
    if not new_name.endswith("_Bot"):
        new_name = new_name + "_Bot"

    from .admin_hxa import _get_agent_token, _update_agent_name_in_config
    from ..services.install_service import _get_hub_url

    agent_token = _get_agent_token(instance_id)
    if not agent_token:
        raise HTTPException(status_code=400, detail="找不到该实例的 agent token。")

    # Call HXA Hub rename API
    hub = _get_hub_url().rstrip("/")
    rename_data = json.dumps({"name": new_name}).encode()
    try:
        rename_req = urllib.request.Request(
            f"{hub}/api/me/name",
            data=rename_data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {agent_token}"},
            method="PATCH",
        )
        with urllib.request.urlopen(rename_req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise HTTPException(status_code=e.code, detail=f"改名失败: {body}")

    # Update local DB
    cursor = db.cursor()
    cursor.execute("UPDATE instances SET agent_name = %s WHERE id = %s", (new_name, instance_id))
    cursor.execute("UPDATE instance_configs SET agent_name = %s WHERE instance_id = %s", (new_name, instance_id))
    cursor.close()
    _update_agent_name_in_config(instance_id, new_name)

    return {"ok": True, "agent_name": new_name}


@router.delete("/{instance_id}")
def delete_instance(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
) -> dict[str, str]:
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))

    # best effort teardown of runtime containers/data
    compose_file = inst.get("compose_file")
    project = inst.get("compose_project")
    runtime_dir = inst.get("runtime_dir")
    if compose_file and project and runtime_dir:
        uninstall_instance(instance_id, compose_file, project, runtime_dir)

    if runtime_dir:
        shutil.rmtree(Path(runtime_dir), ignore_errors=True)

    cursor = db.cursor()
    # Delete child rows first to satisfy FK constraints before removing the parent instance row.
    cursor.execute("DELETE FROM install_events WHERE instance_id = %s", (instance_id,))
    cursor.execute("DELETE FROM instance_metrics WHERE instance_id = %s", (instance_id,))
    cursor.execute("DELETE FROM instance_configs WHERE instance_id = %s", (instance_id,))
    cursor.execute("DELETE FROM instances WHERE id = %s AND owner_id = %s", (instance_id, current_user["id"]))
    cursor.close()
    return {"status": "deleted", "instance_id": instance_id}


# ─── Chat proxy helpers ─────────────────────────────────────────────

RUNTIME_ROOT = Path(runtime_root())


def _read_runtime_agent_name(instance_id: str) -> str:
    """Read agent name from runtime config files (source of truth)."""
    runtime_dir = RUNTIME_ROOT / instance_id

    # OpenClaw: openclaw-config/openclaw.json
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"
    if oc_cfg.exists():
        try:
            cfg = json.loads(oc_cfg.read_text())
            name = cfg.get("channels", {}).get("hxa-connect", {}).get("agentName", "")
            if name:
                return name
        except Exception:
            pass

    # Zylos: zylos-data/components/hxa-connect/config.json
    zy_cfg = runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
    if zy_cfg.exists():
        try:
            cfg = json.loads(zy_cfg.read_text())
            name = cfg.get("orgs", {}).get("default", {}).get("agent_name", "")
            if name:
                return name
        except Exception:
            pass

    return ""


def _get_chat_config(instance_id: str, owner_id: str, db):
    """Return (hub_url, admin_bot_token, target_agent_name) for chatting WITH an instance bot.

    Uses a dedicated admin bot identity so the user chats with (not as) the instance bot.
    Reads agent_name from runtime config (source of truth) rather than DB which may be stale.
    """
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, agent_name FROM instances WHERE id = %s AND owner_id = %s",
        (instance_id, owner_id),
    )
    inst = cursor.fetchone()
    if not inst:
        cursor.close()
        raise HTTPException(status_code=404, detail="Instance not found.")
    cursor.execute(
        "SELECT hub_url, agent_name FROM instance_configs WHERE instance_id = %s",
        (instance_id,),
    )
    cfg = cursor.fetchone()
    if not cfg or not cfg["hub_url"]:
        cursor.close()
        raise HTTPException(status_code=400, detail="Instance not configured for HXA.")

    hub_url = cfg["hub_url"].rstrip("/")

    # Read agent_name from runtime config (source of truth)
    target_agent_name = _read_runtime_agent_name(instance_id)
    # Fall back to DB if runtime read fails
    if not target_agent_name:
        target_agent_name = cfg["agent_name"] or inst["agent_name"] or ""
    if not target_agent_name:
        cursor.close()
        raise HTTPException(status_code=400, detail="Instance has no agent name.")

    # Get instance's org_id for admin bot registration
    cursor.execute("SELECT org_id FROM instance_configs WHERE instance_id = %s", (instance_id,))
    cfg2 = cursor.fetchone()
    instance_org_id = cfg2["org_id"] if cfg2 and cfg2["org_id"] else None

    # Get user display name for bot registration
    cursor.execute("SELECT name, email FROM users WHERE id = %s", (owner_id,))
    user_row = cursor.fetchone()
    cursor.close()
    display_name = (user_row["name"] if user_row else "") or ""

    # Get or register per-user admin bot in the SAME org as the instance
    admin_token = _ensure_user_bot(hub_url, owner_id, display_name, target_org_id=instance_org_id)
    if not admin_token:
        raise HTTPException(status_code=500, detail="Failed to initialize chat bot.")
    return hub_url, admin_token, target_agent_name


# In-memory cache: {user_id: token} — avoids hitting Hub /api/me on every request
_user_bot_cache: dict[str, str] = {}


def _make_admin_bot_name(display_name: str, user_id: str) -> str:
    """Generate admin bot name from user's display name."""
    import re
    if display_name:
        sanitized = re.sub(r'[^a-zA-Z0-9_\-\u4e00-\u9fff]', '_', display_name.strip())
        sanitized = re.sub(r'_+', '_', sanitized).strip('_')
        if sanitized:
            return sanitized
    short_id = user_id.replace("user_", "")[:12]
    return f"u_{short_id}"


def _ensure_user_bot(hub_url: str, user_id: str, display_name: str = "", target_org_id: str | None = None) -> str:
    """Return per-user bot token, registering one if needed. Token is stable.
    If target_org_id is given, register in that org instead of default."""
    from ..database import get_setting, set_setting
    from ..services.install_service import _get_org_id, _get_org_secret

    # Cache key includes org_id so different orgs get different bots
    cache_suffix = f"_{target_org_id[:8]}" if target_org_id else ""
    setting_key = f"hxa_user_bot_token_{user_id}{cache_suffix}"
    cache_key = f"{user_id}{cache_suffix}"
    bot_name = _make_admin_bot_name(display_name, user_id)

    # Check memory cache first
    if cache_key in _user_bot_cache:
        return _user_bot_cache[cache_key]

    # Check DB — token is stable, only verify once per process
    token = get_setting(setting_key, "")
    if token:
        try:
            req = urllib.request.Request(
                f"{hub_url}/api/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                me = json.loads(resp.read().decode())
            # Rename if user changed their display name
            if me.get("name", "") != bot_name:
                try:
                    urllib.request.urlopen(urllib.request.Request(
                        f"{hub_url}/api/me/name",
                        data=json.dumps({"name": bot_name}).encode(),
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        method="PATCH",
                    ), timeout=5)
                except Exception:
                    pass
            _user_bot_cache[cache_key] = token
            return token
        except Exception:
            pass  # Token invalid, re-register below

    # Register a new bot for this user — use target org if specified
    if target_org_id:
        from .admin_hxa import _hub_org_admin_request
        from ..database import get_connection as _gc
        # Resolve org_secret for target org
        default_oid = _get_org_id()
        if target_org_id == default_oid:
            org_secret = _get_org_secret()
        else:
            conn = _gc()
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT org_secret FROM org_secrets WHERE org_id = %s", (target_org_id,))
                row = cursor.fetchone()
                cursor.close()
            finally:
                conn.close()
            org_secret = row["org_secret"] if row else ""
        org_id = target_org_id
    else:
        org_secret = _get_org_secret()
        org_id = _get_org_id()
    if not org_secret:
        return ""

    from urllib.parse import urlparse as _up2
    _ph2 = _up2(_get_hub_url())
    origin = f"{_ph2.scheme}://{_ph2.netloc}"

    try:
        # Admin login (for cleanup if needed)
        login_data = json.dumps({"type": "org_admin", "org_secret": org_secret, "org_id": org_id}).encode()
        login_req = urllib.request.Request(
            f"{hub_url}/api/auth/login", data=login_data,
            headers={"Content-Type": "application/json", "Origin": origin}, method="POST",
        )
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]

        # Cleanup existing bot with same name + release tombstone (best effort)
        try:
            bots_req = urllib.request.Request(
                f"{hub_url}/api/bots?limit=200",
                headers={"Cookie": cookie, "Origin": origin},
            )
            with urllib.request.urlopen(bots_req, timeout=10) as resp:
                bots = json.loads(resp.read().decode())
            items = bots if isinstance(bots, list) else bots.get("bots", bots.get("items", []))
            for b in items:
                if b.get("name") == bot_name:
                    urllib.request.urlopen(urllib.request.Request(
                        f"{hub_url}/api/bots/{b['id']}",
                        headers={"Cookie": cookie, "Origin": origin}, method="DELETE",
                    ), timeout=10)
                    break
        except Exception:
            pass
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{hub_url}/api/orgs/{org_id}/tombstones/{bot_name}",
                headers={"Cookie": cookie, "Origin": origin}, method="DELETE",
            ), timeout=10)
        except Exception:
            pass

        # Register — try with display name first, fallback with user_id suffix on conflict
        short_id = user_id.replace("user_", "")[:7]
        candidates = [bot_name, f"{bot_name}_{short_id}"]
        for name_candidate in candidates:
            try:
                reg_data = json.dumps({"org_id": org_id, "org_secret": org_secret, "name": name_candidate}).encode()
                reg_req = urllib.request.Request(
                    f"{hub_url}/api/auth/register", data=reg_data,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(reg_req, timeout=15) as resp:
                    result = json.loads(resp.read().decode())
                new_token = result.get("token", "")
                if new_token:
                    set_setting(setting_key, new_token)
                    _user_bot_cache[cache_key] = new_token
                    return new_token
            except urllib.error.HTTPError as e:
                body = e.read().decode() if e.fp else ""
                if e.code == 409 and "NAME" in body:
                    continue  # Try next candidate
                break
    except Exception:
        pass
    return ""


def _hub_origin():
    from urllib.parse import urlparse
    from ..services.install_service import _get_hub_url
    p = urlparse(_get_hub_url())
    return f"{p.scheme}://{p.netloc}"


def _hub_request(hub_url: str, token: str, method: str, path: str, body: dict | None = None):
    """Make an authenticated request to the HXA Hub API."""
    url = f"{hub_url}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": _hub_origin(),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500] if e.fp else str(e)
        raise HTTPException(status_code=e.code, detail=f"Hub API error: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Hub unreachable: {e}")


# ─── Chat proxy endpoints ───────────────────────────────────────────

@router.get("/{instance_id}/chat/info")
def chat_info(
    instance_id: str,
    current_user=Depends(get_current_user),
    db = Depends(get_db),
):
    """Return chat info: target bot status and admin bot name."""
    hub_url, admin_token, target_name = _get_chat_config(instance_id, current_user["id"], db)
    # Get admin bot identity from Hub /api/me
    try:
        me = _hub_request(hub_url, admin_token, "GET", "/api/me")
        admin_bot_name = me.get("name", "hire_admin_panel")
        admin_bot_id = me.get("id", "")
    except Exception:
        admin_bot_name = "hire_admin_panel"
        admin_bot_id = ""
    # Check if target bot is online
    result = _hub_request(hub_url, admin_token, "GET", "/api/bots")
    bots = result if isinstance(result, list) else result.get("bots", result.get("items", []))
    target = next((b for b in bots if b.get("name") == target_name), None)
    target_id = target.get("id", "") if target else ""

    # Find existing DM channel_id from inbox
    dm_channel_id = ""
    if target_id:
        try:
            inbox = _hub_request(hub_url, admin_token, "GET", "/api/inbox?since=0&limit=50")
            if isinstance(inbox, list):
                for msg in inbox:
                    if msg.get("sender_id") == target_id or msg.get("sender_name") == target_name:
                        dm_channel_id = msg.get("channel_id", "")
                        break
        except Exception:
            pass

    return {
        "target_name": target_name,
        "target_online": target.get("online", False) if target else False,
        "target_id": target_id,
        "admin_bot_name": admin_bot_name,
        "admin_bot_id": admin_bot_id,
        "dm_channel_id": dm_channel_id,
    }


class _ChatSendRequest(_BaseModel):
    content: str
    image_url: str | None = None


# Upload directory served by nginx at /openclaw/uploads/
_UPLOAD_DIR = Path(runtime_root()).parent / "frontend" / "dist" / "uploads"
_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


@router.post("/{instance_id}/chat/upload")
async def chat_upload(
    instance_id: str,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db = Depends(get_db),
):
    """Upload an image and return a public URL."""
    # Verify instance access
    _get_chat_config(instance_id, current_user["id"], db)

    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的图片格式: {ext}")

    data = await file.read()
    if len(data) > _MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="图片大小不能超过 10MB")

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex[:16]}{ext}"
    dest = _UPLOAD_DIR / filename
    dest.write_bytes(data)

    url = f"{site_base_url()}/uploads/{filename}"
    return {"url": url, "filename": filename}


@router.post("/{instance_id}/chat/send")
def chat_send(
    instance_id: str,
    req: _ChatSendRequest,
    current_user=Depends(get_current_user),
    db = Depends(get_db),
):
    """Send a DM to the instance bot via admin bot."""
    hub_url, admin_token, target_name = _get_chat_config(instance_id, current_user["id"], db)
    # Build message content: if image_url present, include it for AI to see
    content = req.content or ""
    if req.image_url:
        content = f"[图片]({req.image_url})\n{content}" if content else f"[图片]({req.image_url})"
    result = _hub_request(hub_url, admin_token, "POST", "/api/send", {"to": target_name, "content": content})
    return result


@router.get("/{instance_id}/chat/messages")
def chat_messages(
    instance_id: str,
    channel_id: str,
    before: str | None = None,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db = Depends(get_db),
):
    """Get messages from a DM channel."""
    hub_url, admin_token, _ = _get_chat_config(instance_id, current_user["id"], db)
    params = [f"limit={min(limit, 200)}"]
    if before:
        params.append(f"before={before}")
    qs = "&".join(params)
    result = _hub_request(hub_url, admin_token, "GET", f"/api/channels/{channel_id}/messages?{qs}")
    # Hub may return a raw array or {messages: [], has_more: bool} — normalize
    if isinstance(result, list):
        return {"messages": result, "has_more": len(result) >= limit}
    if "messages" not in result:
        return {"messages": [], "has_more": False}
    return result


@router.post("/{instance_id}/chat/ws-ticket")
def chat_ws_ticket(
    instance_id: str,
    current_user=Depends(get_current_user),
    db = Depends(get_db),
):
    """Get a WebSocket ticket for real-time chat (using admin bot identity)."""
    hub_url, admin_token, _ = _get_chat_config(instance_id, current_user["id"], db)
    result = _hub_request(hub_url, admin_token, "POST", "/api/ws-ticket", {})
    ws_url = hub_url.replace("https://", "wss://").replace("http://", "ws://")
    if not ws_url.endswith("/ws"):
        ws_url = ws_url.rstrip("/") + "/ws"
    return {"ticket": result["ticket"], "ws_url": ws_url}


# ─── Claude Session management ──────────────────────────────────────

from ..services.docker_utils import docker_run as _docker_run, get_container_name as _get_container_name


def _get_sessions_paths(product: str) -> tuple[str, str]:
    """Return (sessions_json_path, sessions_dir) inside the container for each product."""
    if product == "zylos":
        return (
            "/home/zylos/.claude/projects/-home-zylos-zylos/.sessions.json",
            "/home/zylos/.claude/sessions",
        )
    # OpenClaw
    return (
        "/home/node/.openclaw/sessions/sessions.json",
        "/home/node/.openclaw/sessions",
    )


def _parse_sessions_json(raw: str) -> list[dict]:
    """Parse sessions JSON and return normalized list of session info dicts."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []

    sessions: list[dict] = []
    # Handle both array and dict formats
    items = data if isinstance(data, list) else list(data.values()) if isinstance(data, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        session: dict = {
            "id": item.get("id") or item.get("sessionId") or "",
            "type": item.get("type") or item.get("model") or "unknown",
            "lastActivity": item.get("lastActivity") or item.get("last_activity") or item.get("updatedAt") or "",
        }
        # Token usage if available
        usage = item.get("tokenUsage") or item.get("usage") or {}
        if usage:
            session["tokenUsage"] = {
                "input": usage.get("input") or usage.get("inputTokens") or 0,
                "output": usage.get("output") or usage.get("outputTokens") or 0,
            }
        sessions.append(session)
    return sessions


@router.get("/{instance_id}/sessions")
def list_sessions(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """List Claude sessions for an instance."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product") or "openclaw"
    container_name = _get_container_name(instance_id, product)

    sessions_json_path, sessions_dir = _get_sessions_paths(product)

    # Try reading sessions.json first
    rc, out = _docker_run(["docker", "exec", container_name, "cat", sessions_json_path], timeout=10)
    sessions: list[dict] = []
    if rc == 0 and out.strip():
        sessions = _parse_sessions_json(out)

    # If no sessions.json or empty, try listing session directories
    if not sessions:
        rc2, out2 = _docker_run(
            ["docker", "exec", container_name, "sh", "-c", f"ls -1t {sessions_dir}/ 2>/dev/null || true"],
            timeout=10,
        )
        if rc2 == 0 and out2.strip():
            for dirname in out2.strip().splitlines():
                dirname = dirname.strip()
                if not dirname or dirname.startswith("."):
                    continue
                sessions.append({
                    "id": dirname,
                    "type": "session",
                    "lastActivity": "",
                })

    return {
        "sessions": sessions,
        "count": len(sessions),
        "container": container_name,
    }


# ─── Skills / Plugins viewer ─────────────────────────────────────────


def _list_skills(container_name: str, product: str) -> list[dict]:
    """List installed skills/plugins from inside a container."""
    skills: list[dict] = []

    if product == "openclaw":
        # OpenClaw extensions
        rc, out = _docker_run(
            ["docker", "exec", container_name, "ls", "/home/node/.openclaw/extensions/"],
            timeout=10,
        )
        if rc == 0 and out.strip():
            for name in out.strip().splitlines():
                name = name.strip()
                if not name or name.startswith("."):
                    continue
                skill: dict = {"id": name, "name": name, "source": "extension", "description": ""}
                # Try to read package.json for metadata
                rc2, pkg = _docker_run(
                    ["docker", "exec", container_name, "cat", f"/home/node/.openclaw/extensions/{name}/package.json"],
                    timeout=5,
                )
                if rc2 == 0 and pkg.strip():
                    try:
                        meta = json.loads(pkg)
                        skill["name"] = meta.get("name", name)
                        skill["description"] = meta.get("description", "")
                    except (json.JSONDecodeError, ValueError):
                        pass
                skills.append(skill)
    else:
        # Zylos components
        rc, out = _docker_run(
            ["docker", "exec", container_name, "ls", "/home/zylos/zylos/components/"],
            timeout=10,
        )
        if rc == 0 and out.strip():
            for name in out.strip().splitlines():
                name = name.strip()
                if not name or name.startswith("."):
                    continue
                skill: dict = {"id": name, "name": name, "source": "component", "description": ""}
                rc2, pkg = _docker_run(
                    ["docker", "exec", container_name, "cat", f"/home/zylos/zylos/components/{name}/package.json"],
                    timeout=5,
                )
                if rc2 == 0 and pkg.strip():
                    try:
                        meta = json.loads(pkg)
                        skill["name"] = meta.get("name", name)
                        skill["description"] = meta.get("description", "")
                    except (json.JSONDecodeError, ValueError):
                        pass
                skills.append(skill)

        # Zylos Claude skills
        rc3, out3 = _docker_run(
            ["docker", "exec", container_name, "ls", "/home/zylos/.claude/skills/"],
            timeout=10,
        )
        if rc3 == 0 and out3.strip():
            for name in out3.strip().splitlines():
                name = name.strip()
                if not name or name.startswith("."):
                    continue
                skill_entry: dict = {"id": f"skill_{name}", "name": name, "source": "skill", "description": ""}
                # Try to read SKILL.md first line as description
                rc4, md = _docker_run(
                    ["docker", "exec", container_name, "head", "-5", f"/home/zylos/.claude/skills/{name}/SKILL.md"],
                    timeout=5,
                )
                if rc4 == 0 and md.strip():
                    lines = [l.strip() for l in md.strip().splitlines() if l.strip() and not l.strip().startswith("#")]
                    if lines:
                        skill_entry["description"] = lines[0][:200]
                skills.append(skill_entry)

    return skills


def _get_skill_base_path(product: str, skill_id: str) -> str:
    """Return the base path inside container for a given skill id."""
    if product == "openclaw":
        return f"/home/node/.openclaw/extensions/{skill_id}"
    if skill_id.startswith("skill_"):
        real_name = skill_id[len("skill_"):]
        return f"/home/zylos/.claude/skills/{real_name}"
    return f"/home/zylos/zylos/components/{skill_id}"


@router.get("/{instance_id}/skills")
def list_instance_skills(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """List installed skills/plugins for an instance."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product") or "openclaw"
    container_name = _get_container_name(instance_id, product)
    skills = _list_skills(container_name, product)
    return {"skills": skills}


@router.get("/{instance_id}/skills/{skill_id}/content")
def get_skill_content(
    instance_id: str,
    skill_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Read main source file of a skill."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product") or "openclaw"
    container_name = _get_container_name(instance_id, product)
    base_path = _get_skill_base_path(product, skill_id)

    # Try common entry files in order
    candidates = ["SKILL.md", "index.ts", "index.js", "index.mjs", "main.ts", "main.js", "package.json"]
    for filename in candidates:
        rc, content = _docker_run(
            ["docker", "exec", container_name, "cat", f"{base_path}/{filename}"],
            timeout=10,
        )
        if rc == 0 and content.strip():
            return {"content": content, "filename": filename}

    # Fallback: list files
    rc, listing = _docker_run(
        ["docker", "exec", container_name, "ls", "-la", base_path],
        timeout=10,
    )
    if rc == 0:
        return {"content": listing, "filename": "(directory listing)"}
    raise HTTPException(status_code=404, detail="No readable source file found.")


@router.post("/{instance_id}/sessions/clear")
def clear_sessions(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Clear all Claude sessions for an instance. Helps recover stuck instances."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product") or "openclaw"
    container_name = _get_container_name(instance_id, product)

    sessions_json_path, sessions_dir = _get_sessions_paths(product)

    errors: list[str] = []

    # Remove session files
    rc, out = _docker_run(
        ["docker", "exec", container_name, "sh", "-c", f"rm -rf {sessions_dir}/* 2>&1"],
        timeout=15,
    )
    if rc != 0:
        errors.append(f"rm sessions dir: {out}")

    # Remove sessions.json
    rc2, out2 = _docker_run(
        ["docker", "exec", container_name, "sh", "-c", f"rm -f {sessions_json_path} 2>&1"],
        timeout=10,
    )
    if rc2 != 0:
        errors.append(f"rm sessions json: {out2}")

    if errors:
        return {"ok": False, "detail": "; ".join(errors)}
    return {"ok": True, "detail": "All Claude sessions cleared."}


@router.post("/{instance_id}/restart-plugins")
def restart_plugins(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Restart HXA/Telegram plugins for an instance."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")
    container_name = _get_container_name(instance_id, product)

    if product == "zylos":
        # Try restarting zylos-hxa-connect; if not in PM2 yet, start it from ecosystem config
        rc, out = _docker_run(["docker", "exec", container_name, "pm2", "restart", "zylos-hxa-connect"], timeout=15)
        if rc != 0 and "not found" in out.lower():
            eco = "/home/zylos/zylos/.claude/skills/hxa-connect/ecosystem.config.cjs"
            rc, out = _docker_run(["docker", "exec", container_name, "pm2", "start", eco], timeout=15)
    else:
        rc, out = _docker_run(["docker", "restart", container_name], timeout=30)

    return {"ok": rc == 0, "detail": out or "Plugins restarted."}


# ── File Browser ─────────────────────────────────────────────────────────────

def _workspace_root(product: str) -> str:
    if product == "zylos":
        return "/home/zylos/zylos"
    return "/home/node/.openclaw/workspace"


def _safe_path(root: str, rel: str) -> str:
    """Resolve path safely within root. Rejects traversal."""
    import posixpath
    clean = posixpath.normpath("/" + rel).lstrip("/")
    if ".." in clean.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    return f"{root}/{clean}" if clean else root


@router.get("/{instance_id}/files")
def list_files(
    instance_id: str,
    path: str = Query(default="/"),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List files in the instance workspace."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")
    container = _get_container_name(instance_id, product)
    root = _workspace_root(product)
    target = _safe_path(root, path)

    rc, out = _docker_run(
        ["docker", "exec", container, "ls", "-la", "--time-style=+%Y-%m-%d %H:%M", target],
        timeout=10,
    )
    if rc != 0:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    files = []
    for line in out.splitlines()[1:]:  # skip "total N" line
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        perms, _, _, _, size_str, date_str, time_str, name = parts
        if name in (".", ".."):
            continue
        is_dir = perms.startswith("d")
        is_link = perms.startswith("l")
        display_name = name.split(" -> ")[0] if is_link else name
        files.append({
            "name": display_name,
            "type": "dir" if is_dir else "file",
            "size": int(size_str) if not is_dir else None,
            "modified": f"{date_str} {time_str}",
        })
    return {"path": path, "files": files}


@router.get("/{instance_id}/files/download")
def download_file(
    instance_id: str,
    path: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Download a file from the instance workspace."""
    import subprocess
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")
    container = _get_container_name(instance_id, product)
    root = _workspace_root(product)
    target = _safe_path(root, path)

    # Verify it's a file (not directory)
    rc, out = _docker_run(["docker", "exec", container, "test", "-f", target], timeout=5)
    if rc != 0:
        raise HTTPException(status_code=404, detail="File not found")

    filename = os.path.basename(target)

    def stream():
        proc = subprocess.Popen(
            ["docker", "cp", f"{container}:{target}", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        # docker cp outputs a tar stream; extract the single file
        import tarfile, io
        try:
            tar = tarfile.open(fileobj=proc.stdout, mode="r|")
            for member in tar:
                f = tar.extractfile(member)
                if f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        yield chunk
                    break
            tar.close()
        finally:
            proc.wait()

    return StreamingResponse(
        stream(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Self-Check & Repair ─────────────────────────────────────────────────────


def _self_check_instance(instance_id: str, product: str, db, inst: dict | None = None) -> list[dict]:
    """Run all checks, return list of {name, status, detail, fixable}."""
    from ..database import get_setting, runtime_root, get_connection
    from ..services.docker_utils import get_container_name, get_container_info, docker_run
    from ..services.install_service import _safe_agent_name, _read_env_file

    checks: list[dict] = []
    container = get_container_name(instance_id, product)
    # Prefer DB runtime_dir (may differ from default runtime_root in manual installs)
    db_runtime_dir = (inst or {}).get("runtime_dir", "")
    _rt = runtime_root()
    inst_runtime = db_runtime_dir if db_runtime_dir and os.path.isdir(db_runtime_dir) else os.path.join(_rt, instance_id)

    # ── 1. Container running ───────────────────────────────────────────
    try:
        info = get_container_info(container)
        running = info.get("running", False)
    except Exception:
        running = False
    checks.append({
        "name": "container_running",
        "label": "容器运行状态",
        "status": "ok" if running else "fail",
        "detail": f"{container}: {'运行中' if running else '未运行'}",
        "fixable": False,
    })

    if not running:
        return checks  # No point checking further

    # ── 2. DB metadata ─────────────────────────────────────────────────
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT compose_project, compose_file, runtime_dir, status, install_state FROM instances WHERE id = %s", (instance_id,))
    inst = cursor.fetchone()
    cursor.close()
    missing = []
    if not inst.get("compose_project"):
        missing.append("compose_project")
    if not inst.get("runtime_dir"):
        missing.append("runtime_dir")
    if inst.get("install_state") != "running":
        missing.append(f"install_state={inst.get('install_state')}")
    if inst.get("status") != "active":
        missing.append(f"status={inst.get('status')}")
    checks.append({
        "name": "db_metadata",
        "label": "数据库元数据",
        "status": "fail" if missing else "ok",
        "detail": f"缺失: {', '.join(missing)}" if missing else "完整",
        "fixable": bool(missing),
    })

    # ── 3. API Keys ────────────────────────────────────────────────────
    db_anthropic_base = get_setting("anthropic_base_url", "")
    db_anthropic_token = get_setting("anthropic_auth_token", "")
    db_openai_base = get_setting("openai_base_url", "")
    db_openai_key = get_setting("openai_api_key", "")
    has_any_key = bool(db_anthropic_token or db_openai_key)

    key_issues = []
    if not has_any_key:
        key_issues.append("全局未配置任何 AI API Key")
    else:
        if product == "openclaw":
            oc_json = os.path.join(inst_runtime, "openclaw-config", "openclaw.json")
            if os.path.exists(oc_json):
                try:
                    cfg = json.loads(open(oc_json).read())
                    ant = cfg.get("models", {}).get("providers", {}).get("anthropic", {})
                    if db_anthropic_token and ant.get("apiKey") != db_anthropic_token:
                        key_issues.append("openclaw.json apiKey 与全局配置不一致")
                    if db_anthropic_base and ant.get("baseUrl") != db_anthropic_base:
                        key_issues.append("openclaw.json baseUrl 与全局配置不一致")
                except Exception:
                    key_issues.append("openclaw.json 读取失败")
            else:
                key_issues.append("openclaw.json 不存在")
        else:  # zylos
            env_path = os.path.join(inst_runtime, ".env")
            if os.path.exists(env_path):
                env = _read_env_file(Path(env_path))
                if db_anthropic_token and env.get("ANTHROPIC_AUTH_TOKEN") != db_anthropic_token:
                    key_issues.append("实例 .env ANTHROPIC_AUTH_TOKEN 与全局不一致")
                if db_anthropic_base and env.get("ANTHROPIC_BASE_URL") != db_anthropic_base:
                    key_issues.append("实例 .env ANTHROPIC_BASE_URL 与全局不一致")
                if db_openai_key and env.get("OPENAI_API_KEY") != db_openai_key:
                    key_issues.append("实例 .env OPENAI_API_KEY 与全局不一致")
                if db_openai_base and env.get("OPENAI_BASE_URL") != db_openai_base:
                    key_issues.append("实例 .env OPENAI_BASE_URL 与全局不一致")
                # Check compose yaml for stale defaults
                compose_yaml = os.path.join(inst_runtime, "docker-compose.instance.yml")
                if os.path.exists(compose_yaml):
                    yaml_text = open(compose_yaml).read()
                    if db_anthropic_base and f'ANTHROPIC_BASE_URL: "{db_anthropic_base}"' not in yaml_text and "api.anthropic.com" in yaml_text:
                        key_issues.append("compose yaml ANTHROPIC_BASE_URL 默认值未更新")
            else:
                key_issues.append("实例 .env 不存在")
    checks.append({
        "name": "api_keys",
        "label": "AI API Key 配置",
        "status": "fail" if key_issues else ("missing" if not has_any_key else "ok"),
        "detail": "; ".join(key_issues) if key_issues else ("全局无 API Key" if not has_any_key else "已同步"),
        "fixable": bool(key_issues) and has_any_key,
    })

    # ── 4. HXA Config (with Hub consistency check) ─────────────────────
    hxa_issues = []
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT hub_url, org_id, org_token, agent_name FROM instance_configs WHERE instance_id = %s", (instance_id,))
    ic = cursor.fetchone()
    cursor.close()

    container_token = ""
    container_org_id = ""
    container_agent_name = ""
    if product == "openclaw":
        oc_json = os.path.join(inst_runtime, "openclaw-config", "openclaw.json")
        if os.path.exists(oc_json):
            try:
                cfg = json.loads(open(oc_json).read())
                hxa = cfg.get("channels", {}).get("hxa-connect", {})
                container_token = hxa.get("agentToken", "")
                container_org_id = hxa.get("orgId", "")
                container_agent_name = hxa.get("agentName", "")
                if not container_token:
                    hxa_issues.append("openclaw.json 无 agentToken")
            except Exception:
                hxa_issues.append("openclaw.json 读取失败")
    else:
        zy_cfg = os.path.join(inst_runtime, "zylos-data", "components", "hxa-connect", "config.json")
        if os.path.exists(zy_cfg):
            try:
                cfg = json.loads(open(zy_cfg).read())
                org = cfg.get("orgs", {}).get("default", {})
                container_token = org.get("agent_token", "")
                container_org_id = org.get("org_id", "")
                container_agent_name = org.get("agent_name", "")
                if not container_token:
                    hxa_issues.append("config.json 无 agent_token")
            except Exception:
                hxa_issues.append("config.json 读取失败")
        else:
            hxa_issues.append("hxa-connect config.json 不存在")

    if not ic:
        hxa_issues.append("instance_configs 记录不存在")
    elif not ic.get("org_id"):
        hxa_issues.append("instance_configs.org_id 为空")
    if ic and container_token and ic.get("org_token") != container_token:
        hxa_issues.append("DB org_token 与容器内 token 不一致")

    # Hub consistency check: query Hub for authoritative org_id/agent_name
    hub_org_id = ""
    hub_agent_name = ""
    if container_token:
        hub_url = (ic.get("hub_url") if ic else "") or hxa_hub_url()
        try:
            me = _hub_request(hub_url, container_token, "GET", "/api/me")
            hub_org_id = me.get("org_id", "")
            hub_agent_name = me.get("name", "")
            # Compare Hub vs DB
            if hub_org_id and ic and ic.get("org_id") and ic["org_id"] != hub_org_id:
                hxa_issues.append(f"DB org_id({ic['org_id'][:8]}…) 与 Hub({hub_org_id[:8]}…) 不一致")
            # Compare Hub vs container config
            if hub_org_id and container_org_id and container_org_id != hub_org_id:
                hxa_issues.append(f"容器 orgId({container_org_id[:8]}…) 与 Hub({hub_org_id[:8]}…) 不一致")
            # Compare agent_name
            if hub_agent_name and ic and ic.get("agent_name") and ic["agent_name"] != hub_agent_name:
                hxa_issues.append(f"DB agent_name({ic['agent_name']}) 与 Hub({hub_agent_name}) 不一致")
        except Exception:
            pass  # Hub unreachable, skip consistency check

    checks.append({
        "name": "hxa_config",
        "label": "HXA 组织配置",
        "status": "fail" if hxa_issues else "ok",
        "detail": "; ".join(hxa_issues) if hxa_issues else "配置完整，Hub 一致",
        "fixable": bool(hxa_issues) and bool(container_token),
    })

    # ── 5. HXA Connection ──────────────────────────────────────────────
    ws_connected = False
    if product == "openclaw":
        rc, logs = docker_run(["docker", "logs", "--tail", "30", container], timeout=10)
        ws_connected = "WebSocket connected" in logs
    else:
        rc, logs = docker_run(["docker", "exec", container, "tail", "-20",
                               "/home/zylos/zylos/components/hxa-connect/logs/out.log"], timeout=10)
        ws_connected = "WebSocket connected" in logs
        if not ws_connected:
            # Check if process is running
            rc2, pm2_out = docker_run(["docker", "exec", container, "pm2", "show", "zylos-hxa-connect", "--no-color"], timeout=10)
            if rc2 != 0 or "not found" in pm2_out.lower():
                ws_connected = False  # process not even running
    checks.append({
        "name": "hxa_connection",
        "label": "HXA WebSocket 连接",
        "status": "ok" if ws_connected else "fail",
        "detail": "已连接" if ws_connected else "未连接",
        "fixable": not ws_connected and bool(container_token),
    })

    # ── 6. HXA NPM Dependencies (OpenClaw only) ───────────────────────
    if product == "openclaw":
        rc, out = docker_run(["docker", "exec", container, "test", "-d",
                              "/home/node/.openclaw/extensions/openclaw-hxa-connect/node_modules/@coco-xyz"], timeout=5)
        has_deps = rc == 0
        checks.append({
            "name": "hxa_npm_deps",
            "label": "HXA 插件依赖",
            "status": "ok" if has_deps else "fail",
            "detail": "node_modules 完整" if has_deps else "缺少 @coco-xyz/hxa-connect-sdk",
            "fixable": not has_deps,
        })

    # ── 7. AI Runtime (Zylos only) ────────────────────────────────────
    if product == "zylos":
        rc, out = docker_run(["docker", "exec", container, "sh", "-lc",
                              "/home/zylos/.npm-global/bin/zylos status 2>&1 | head -5"], timeout=15)
        runtime_ok = False
        runtime_detail = "未检测到"
        if "Claude: IDLE" in out or "Claude: BUSY" in out:
            runtime_ok = True
            runtime_detail = "Claude 已认证，运行正常"
        elif "Codex: IDLE" in out or "Codex: BUSY" in out:
            runtime_ok = True
            runtime_detail = "Codex 已认证，运行正常"
        elif "NOT INSTALLED" in out:
            runtime_detail = "AI Runtime 未安装 (需要 zylos init)"
        elif "not authenticated" in out.lower():
            runtime_detail = "AI Runtime 未认证"
        checks.append({
            "name": "ai_runtime",
            "label": "AI Runtime (Claude/Codex)",
            "status": "ok" if runtime_ok else "fail",
            "detail": runtime_detail,
            "fixable": not runtime_ok and has_any_key,
        })

    return checks


@router.post("/{instance_id}/self-check")
def self_check(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Run comprehensive self-check on an instance. Returns report without modifying anything."""
    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")
    checks = _self_check_instance(instance_id, product, db, inst=inst)
    fixable_count = sum(1 for c in checks if c.get("fixable"))
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    if fail_count == 0:
        overall = "ok"
    elif fixable_count > 0:
        overall = "fixable"
    else:
        overall = "needs_attention"
    return {"checks": checks, "overall": overall, "fixable_count": fixable_count}


@router.post("/{instance_id}/self-check/repair")
def self_check_repair(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Execute auto-repair for all fixable issues found by self-check."""
    from ..database import get_setting, runtime_root, get_connection
    from ..services.docker_utils import get_container_name, docker_run
    from ..services.install_service import _safe_agent_name, _read_env_file, _write_env_file

    inst = _get_instance_or_404(instance_id, current_user["id"], db, is_admin=bool(current_user.get("is_admin")))
    product = inst.get("product", "openclaw")
    container = get_container_name(instance_id, product)
    _rt = runtime_root()
    db_runtime_dir = inst.get("runtime_dir", "")
    inst_runtime = db_runtime_dir if db_runtime_dir and os.path.isdir(db_runtime_dir) else os.path.join(_rt, instance_id)
    repairs: list[dict] = []

    # ── Fix DB metadata ────────────────────────────────────────────────
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT compose_project, runtime_dir, status, install_state FROM instances WHERE id = %s", (instance_id,))
    row = cursor.fetchone()
    cursor.close()
    if row and (not row.get("compose_project") or row.get("install_state") != "running"):
        _openclaw_home = os.getenv("OPENCLAW_HOME", "")
        host_rt = os.path.join(_openclaw_home, "runtime", instance_id) if _openclaw_home else inst_runtime
        # Find compose file
        compose_file = ""
        for candidate in ["docker-compose.instance.yml", "docker-compose.yml", "repo/docker-compose.yml", "repo/compose.yml"]:
            if os.path.exists(os.path.join(inst_runtime, candidate)):
                compose_file = os.path.join(host_rt, candidate)
                break
        project = f"hire_{instance_id}" if product == "openclaw" else f"hire_{instance_id}"
        cursor = db.cursor()
        cursor.execute(
            "UPDATE instances SET compose_project=%s, compose_file=%s, runtime_dir=%s, status='active', install_state='running', updated_at=%s WHERE id=%s",
            (project, compose_file, host_rt, _utc_now(), instance_id),
        )
        cursor.close()
        repairs.append({"name": "db_metadata", "action": "已修复 DB 元数据（status=active, install_state=running）"})

    # ── Fix API Keys ───────────────────────────────────────────────────
    db_anthropic_base = get_setting("anthropic_base_url", "")
    db_anthropic_token = get_setting("anthropic_auth_token", "")
    db_openai_base = get_setting("openai_base_url", "")
    db_openai_key = get_setting("openai_api_key", "")

    if product == "openclaw":
        oc_json_path = os.path.join(inst_runtime, "openclaw-config", "openclaw.json")
        if os.path.exists(oc_json_path):
            try:
                cfg = json.loads(open(oc_json_path).read())
                ant = cfg.setdefault("models", {}).setdefault("providers", {}).setdefault("anthropic", {})
                changed = False
                if db_anthropic_base and ant.get("baseUrl") != db_anthropic_base:
                    ant["baseUrl"] = db_anthropic_base
                    changed = True
                if db_anthropic_token and ant.get("apiKey") != db_anthropic_token:
                    ant["apiKey"] = db_anthropic_token
                    changed = True
                if changed:
                    open(oc_json_path, "w").write(json.dumps(cfg, indent=2) + "\n")
                    docker_run(["docker", "restart", container], timeout=30)
                    repairs.append({"name": "api_keys", "action": "已同步 API Key 到 openclaw.json 并重启"})
            except Exception as e:
                repairs.append({"name": "api_keys", "action": f"修复失败: {e}"})
    else:  # zylos
        env_path = os.path.join(inst_runtime, ".env")
        compose_yaml = os.path.join(inst_runtime, "docker-compose.instance.yml")
        if os.path.exists(env_path):
            env = _read_env_file(Path(env_path))
            changed = False
            for env_key, db_val in [
                ("ANTHROPIC_BASE_URL", db_anthropic_base),
                ("ANTHROPIC_AUTH_TOKEN", db_anthropic_token),
                ("ANTHROPIC_API_KEY", db_anthropic_token),
                ("OPENAI_BASE_URL", db_openai_base),
                ("OPENAI_API_KEY", db_openai_key),
                ("CODEX_API_KEY", db_openai_key),
            ]:
                if db_val and env.get(env_key) != db_val:
                    env[env_key] = db_val
                    changed = True
            if changed:
                _write_env_file(Path(env_path), env)
                # Also update zylos-data/.env
                zy_env_path = os.path.join(inst_runtime, "zylos-data", ".env")
                if os.path.exists(zy_env_path):
                    zy_env = _read_env_file(Path(zy_env_path))
                    zy_env.update({k: v for k, v in env.items() if k.startswith("ANTHROPIC") or k.startswith("OPENAI") or k.startswith("CODEX")})
                    _write_env_file(Path(zy_env_path), zy_env)
                repairs.append({"name": "api_keys", "action": "已同步 API Key 到实例 .env"})
            # Fix compose yaml stale defaults
            if os.path.exists(compose_yaml) and db_anthropic_base:
                yaml_text = open(compose_yaml).read()
                if "api.anthropic.com" in yaml_text and db_anthropic_base != "https://api.anthropic.com":
                    yaml_text = yaml_text.replace(
                        '${ANTHROPIC_BASE_URL:-https://api.anthropic.com}',
                        f'${{ANTHROPIC_BASE_URL:-{db_anthropic_base}}}'
                    )
                    open(compose_yaml, "w").write(yaml_text)
                    repairs.append({"name": "api_keys", "action": "已更新 compose yaml ANTHROPIC_BASE_URL 默认值"})
            if changed:
                # Restart container to pick up new env
                compose_file = inst.get("compose_file", "")
                project = inst.get("compose_project", "")
                if compose_file and project:
                    try:
                        _cf = compose_file
                        # Convert host path to container path if needed
                        if not os.path.exists(_cf):
                            _cf = os.path.join(inst_runtime, os.path.basename(_cf))
                        docker_run(["docker", "compose", "-f", _cf, "-p", project, "--env-file", env_path, "down"], timeout=30)
                        docker_run(["docker", "compose", "-f", _cf, "-p", project, "--env-file", env_path, "up", "-d"], timeout=60)
                        repairs.append({"name": "api_keys", "action": "已重启容器使新配置生效"})
                    except Exception:
                        pass

    # ── Fix HXA Config (Hub is authoritative → sync to container + DB) ──
    container_token = ""
    container_agent_name = ""
    container_org_id = ""
    if product == "openclaw":
        oc_json = os.path.join(inst_runtime, "openclaw-config", "openclaw.json")
        if os.path.exists(oc_json):
            try:
                cfg = json.loads(open(oc_json).read())
                hxa = cfg.get("channels", {}).get("hxa-connect", {})
                container_token = hxa.get("agentToken", "")
                container_agent_name = hxa.get("agentName", "")
                container_org_id = hxa.get("orgId", "")
            except Exception:
                pass
    else:
        zy_cfg = os.path.join(inst_runtime, "zylos-data", "components", "hxa-connect", "config.json")
        if os.path.exists(zy_cfg):
            try:
                cfg = json.loads(open(zy_cfg).read())
                org = cfg.get("orgs", {}).get("default", {})
                container_token = org.get("agent_token", "")
                container_agent_name = org.get("agent_name", "")
                container_org_id = org.get("org_id", "")
            except Exception:
                pass

    if container_token:
        # Query Hub for authoritative org_id and agent_name
        conn = get_connection()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT hub_url, org_id, org_token, agent_name FROM instance_configs WHERE instance_id = %s", (instance_id,))
            ic = cur.fetchone()

            hub_url = (ic.get("hub_url") if ic else "") or hxa_hub_url()
            auth_org_id = container_org_id
            auth_agent_name = container_agent_name
            try:
                me = _hub_request(hub_url, container_token, "GET", "/api/me")
                auth_org_id = me.get("org_id", "") or container_org_id
                auth_agent_name = me.get("name", "") or container_agent_name
            except Exception:
                pass  # Hub unreachable, fall back to container values

            # 1. Sync to runtime config file
            if auth_org_id != container_org_id or auth_agent_name != container_agent_name:
                config_updated = False
                if product == "openclaw":
                    oc_json = os.path.join(inst_runtime, "openclaw-config", "openclaw.json")
                    if os.path.exists(oc_json):
                        try:
                            oc_cfg = json.loads(open(oc_json).read())
                            hxa_sec = oc_cfg.get("channels", {}).get("hxa-connect", {})
                            if auth_org_id:
                                hxa_sec["orgId"] = auth_org_id
                            if auth_agent_name:
                                hxa_sec["agentName"] = auth_agent_name
                            open(oc_json, "w").write(json.dumps(oc_cfg, indent=2) + "\n")
                            config_updated = True
                        except Exception:
                            pass
                else:
                    zy_cfg_path = os.path.join(inst_runtime, "zylos-data", "components", "hxa-connect", "config.json")
                    if os.path.exists(zy_cfg_path):
                        try:
                            zy_cfg = json.loads(open(zy_cfg_path).read())
                            default_org = zy_cfg.get("orgs", {}).get("default", {})
                            if auth_org_id:
                                default_org["org_id"] = auth_org_id
                            if auth_agent_name:
                                default_org["agent_name"] = auth_agent_name
                            open(zy_cfg_path, "w").write(json.dumps(zy_cfg, indent=2) + "\n")
                            config_updated = True
                        except Exception:
                            pass
                if config_updated:
                    repairs.append({"name": "hxa_config", "action": f"已同步运行时配置 org_id→{auth_org_id[:8]}…"})

            # 2. Sync to DB instance_configs
            if not ic:
                cur.execute(
                    "INSERT INTO instance_configs (instance_id, hub_url, org_id, org_token, agent_name, configured_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (instance_id, hub_url, auth_org_id, container_token, auth_agent_name, _utc_now(), _utc_now()),
                )
                repairs.append({"name": "hxa_config", "action": "已创建 instance_configs 记录"})
            else:
                updates = []
                if auth_org_id and ic.get("org_id") != auth_org_id:
                    updates.append(f"org_id→{auth_org_id[:8]}…")
                if container_token and ic.get("org_token") != container_token:
                    updates.append("org_token")
                if auth_agent_name and ic.get("agent_name") != auth_agent_name:
                    updates.append(f"agent_name→{auth_agent_name}")
                if updates:
                    cur.execute(
                        "UPDATE instance_configs SET org_id=%s, org_token=%s, agent_name=%s, updated_at=%s WHERE instance_id=%s",
                        (auth_org_id or ic.get("org_id"), container_token, auth_agent_name or ic.get("agent_name"), _utc_now(), instance_id),
                    )
                    repairs.append({"name": "hxa_config", "action": f"已同步 DB: {', '.join(updates)}"})

            # 3. Sync agent_name to instances table
            if auth_agent_name:
                cur.execute("UPDATE instances SET agent_name=%s WHERE id=%s AND (agent_name IS NULL OR agent_name != %s)",
                            (auth_agent_name, instance_id, auth_agent_name))

            # 4. Clear stale admin bot tokens if org_id changed
            old_org_id = ic.get("org_id", "") if ic else ""
            if auth_org_id and old_org_id and auth_org_id != old_org_id:
                cur.execute("DELETE FROM server_settings WHERE `key` LIKE %s",
                            (f"hxa_user_bot_token%_{old_org_id[:8]}%",))
                _user_bot_cache.clear()
                repairs.append({"name": "hxa_config", "action": f"已清理旧组织({old_org_id[:8]}…)的 admin bot 缓存"})

            cur.close()
        finally:
            conn.close()

    # ── Fix HXA Connection (restart) ───────────────────────────────────
    if product == "zylos":
        rc, _ = docker_run(["docker", "exec", container, "pm2", "restart", "zylos-hxa-connect"], timeout=15)
        if rc != 0:
            eco = "/home/zylos/zylos/.claude/skills/hxa-connect/ecosystem.config.cjs"
            docker_run(["docker", "exec", container, "pm2", "start", eco], timeout=15)
        repairs.append({"name": "hxa_connection", "action": "已重启 zylos-hxa-connect"})

    # ── Fix HXA NPM deps (OpenClaw only) ───────────────────────────────
    if product == "openclaw":
        rc, _ = docker_run(["docker", "exec", container, "test", "-d",
                            "/home/node/.openclaw/extensions/openclaw-hxa-connect/node_modules/@coco-xyz"], timeout=5)
        if rc != 0:
            docker_run(["docker", "exec", container, "sh", "-c",
                        "cd /home/node/.openclaw/extensions/openclaw-hxa-connect && npm install --production"], timeout=60)
            docker_run(["docker", "restart", container], timeout=30)
            repairs.append({"name": "hxa_npm_deps", "action": "已安装依赖并重启"})

    # ── Fix AI Runtime (Zylos: zylos init) ───────────────────────────
    if product == "zylos":
        rc, out = docker_run(["docker", "exec", container, "sh", "-lc",
                              "/home/zylos/.npm-global/bin/zylos status 2>&1 | head -5"], timeout=15)
        if "NOT INSTALLED" in out or "not authenticated" in out.lower():
            db_anthropic_token_rt = get_setting("anthropic_auth_token", "")
            db_anthropic_base_rt = get_setting("anthropic_base_url", "")
            db_openai_key_rt = get_setting("openai_api_key", "")
            db_openai_base_rt = get_setting("openai_base_url", "")

            # Patch init.js to skip sk-ant- validation
            docker_run(["docker", "exec", container, "sh", "-c",
                        "INIT_JS=/home/zylos/.npm-global/lib/node_modules/zylos/cli/commands/init.js; "
                        "[ -f \"$INIT_JS\" ] && sed -i \"s|if (opts.apiKey && !opts.apiKey.startsWith('sk-ant-'))|if (false \\&\\& opts.apiKey)|\" \"$INIT_JS\" || true"
                        ], timeout=10)

            if db_anthropic_token_rt:
                base_arg = f"--base-url '{db_anthropic_base_rt}'" if db_anthropic_base_rt else ""
                docker_run(["docker", "exec", "-e", "ANTHROPIC_API_KEY=", container, "sh", "-lc",
                            f"/home/zylos/.npm-global/bin/zylos init --yes --runtime claude --api-key '{db_anthropic_token_rt}' {base_arg} --no-caddy 2>&1"
                            ], timeout=120)
                repairs.append({"name": "ai_runtime", "action": "已执行 zylos init --runtime claude"})
            elif db_openai_key_rt:
                base_arg = f"--codex-base-url '{db_openai_base_rt}'" if db_openai_base_rt else ""
                docker_run(["docker", "exec", "-e", "ANTHROPIC_API_KEY=", "-e", "ANTHROPIC_AUTH_TOKEN=", container, "sh", "-lc",
                            f"/home/zylos/.npm-global/bin/zylos init --yes --runtime codex --codex-api-key '{db_openai_key_rt}' {base_arg} --no-caddy 2>&1"
                            ], timeout=120)
                repairs.append({"name": "ai_runtime", "action": "已执行 zylos init --runtime codex"})

    return {"repairs": repairs, "count": len(repairs)}
