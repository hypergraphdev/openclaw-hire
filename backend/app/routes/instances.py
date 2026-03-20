from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import urllib.request
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
    _get_hub_url,
    _ORG_ID,
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
    # Convert raw token fields to safe boolean - never expose token values
    d["is_telegram_configured"] = bool(d.pop("telegram_bot_token", None))
    d.pop("org_token", None)  # remove sensitive field entirely
    return InstanceResponse(**d)


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


def _merge_instance_config_fields(inst: dict, db: sqlite3.Connection) -> dict:
    """Backfill list/detail fields from instance_configs when legacy rows are partially empty."""
    cfg = db.execute(
        "SELECT telegram_bot_token, org_token, agent_name FROM instance_configs WHERE instance_id = ?",
        (inst["id"],),
    ).fetchone()
    if cfg:
        c = dict(cfg)
        if not inst.get("telegram_bot_token") and c.get("telegram_bot_token"):
            inst["telegram_bot_token"] = c.get("telegram_bot_token")
        if not inst.get("org_token") and c.get("org_token"):
            inst["org_token"] = c.get("org_token")
        if not inst.get("agent_name") and c.get("agent_name"):
            inst["agent_name"] = c.get("agent_name")
    return inst


@router.post("", response_model=InstanceResponse, status_code=status.HTTP_201_CREATED)
def create_instance(
    payload: CreateInstanceRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> InstanceResponse:
    product = PRODUCT_MAP[payload.product]
    if not bool(current_user.get("is_admin", 0)):
        cnt = db.execute("SELECT COUNT(*) AS c FROM instances WHERE owner_id = ?", (current_user["id"],)).fetchone()["c"]
        if cnt >= 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Regular users can only create one instance. Contact admin for quota increase.",
            )

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
    merged = [_merge_instance_config_fields(dict(row), db) for row in rows]
    # Convert to response: drop sensitive fields, add bool flag
    results = []
    for m in merged:
        m["is_telegram_configured"] = bool(m.pop("telegram_bot_token", None))
        m.pop("org_token", None)
        results.append(InstanceResponse(**m))
    return results


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

    inst = _merge_instance_config_fields(inst, db)

    events = db.execute(
        "SELECT * FROM install_events WHERE instance_id = ? ORDER BY id ASC",
        (instance_id,),
    ).fetchall()
    cfg = db.execute(
        "SELECT plugin_name, hub_url, org_id, org_token, agent_name, allow_group, allow_dm, configured_at FROM instance_configs WHERE instance_id = ?",
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
            agent_name=c.get("agent_name"),
            allow_group=bool(c.get("allow_group", 1)),
            allow_dm=bool(c.get("allow_dm", 1)),
            configured_at=c.get("configured_at"),
        )

    return InstanceDetailResponse(
        instance=_row_to_instance(inst),
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
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
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
    db.execute(
        "UPDATE instances SET telegram_bot_token=?, updated_at=? WHERE id=?",
        (payload.telegram_bot_token, now, instance_id),
    )
    db.execute(
        """
        INSERT INTO instance_configs (instance_id, telegram_bot_token, plugin_name, allow_group, allow_dm, configured_at, updated_at)
        VALUES (?, ?, ?, 1, 1, ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
          telegram_bot_token=excluded.telegram_bot_token,
          plugin_name=excluded.plugin_name,
          allow_group=1, allow_dm=1,
          configured_at=excluded.configured_at,
          updated_at=excluded.updated_at
        """,
        (instance_id, payload.telegram_bot_token, plugin_name, now, now),
    )
    db.commit()
    return {"ok": True, "message": message, "is_telegram_configured": True}


@router.post("/{instance_id}/configure-hxa")
async def configure_hxa_endpoint(
    instance_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    inst = _get_instance_or_404(instance_id, current_user["id"], db)
    compose_file, project, runtime_dir = _require_compose(inst)

    # Run blocking docker/compose/registration ops in thread pool so other requests aren't blocked
    import asyncio
    loop = asyncio.get_event_loop()
    ok, message, real_token = await loop.run_in_executor(
        None,
        lambda: configure_hxa_only(
            instance_id, runtime_dir, project,
            product=inst["product"], compose_file=compose_file,
        ),
    )
    if not ok:
        raise HTTPException(status_code=500, detail=message)

    now = _utc_now()
    agent_name = f"hire_{instance_id.replace('-', '')}"[:20]
    plugin_name = "openclaw-hxa-connect" if inst["product"] == "openclaw" else "hxa-connect"
    db.execute(
        "UPDATE instances SET agent_name=?, updated_at=? WHERE id=?",
        (agent_name, now, instance_id),
    )
    db.execute(
        """
        INSERT INTO instance_configs (instance_id, agent_name, plugin_name, hub_url, org_id, org_token, configured_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
          agent_name=excluded.agent_name,
          plugin_name=excluded.plugin_name,
          hub_url=excluded.hub_url,
          org_id=excluded.org_id,
          org_token=COALESCE(excluded.org_token, instance_configs.org_token),
          updated_at=excluded.updated_at
        """,
        (instance_id, agent_name, plugin_name, _get_hub_url(), _ORG_ID, real_token or None, now, now),
    )
    db.commit()
    return {"ok": True, "message": message, "agent_name": agent_name}


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


# ─── Chat proxy helpers ─────────────────────────────────────────────

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")


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


def _get_chat_config(instance_id: str, owner_id: str, db: sqlite3.Connection):
    """Return (hub_url, admin_bot_token, target_agent_name) for chatting WITH an instance bot.

    Uses a dedicated admin bot identity so the user chats with (not as) the instance bot.
    Reads agent_name from runtime config (source of truth) rather than DB which may be stale.
    """
    inst = db.execute(
        "SELECT id, agent_name FROM instances WHERE id = ? AND owner_id = ?",
        (instance_id, owner_id),
    ).fetchone()
    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found.")
    cfg = db.execute(
        "SELECT hub_url, agent_name FROM instance_configs WHERE instance_id = ?",
        (instance_id,),
    ).fetchone()
    if not cfg or not cfg["hub_url"]:
        raise HTTPException(status_code=400, detail="Instance not configured for HXA.")

    hub_url = cfg["hub_url"].rstrip("/")

    # Read agent_name from runtime config (source of truth)
    target_agent_name = _read_runtime_agent_name(instance_id)
    # Fall back to DB if runtime read fails
    if not target_agent_name:
        target_agent_name = cfg["agent_name"] or inst["agent_name"] or ""
    if not target_agent_name:
        raise HTTPException(status_code=400, detail="Instance has no agent name.")

    # Get or register admin bot
    admin_token = _ensure_admin_bot(hub_url)
    if not admin_token:
        raise HTTPException(status_code=500, detail="Failed to initialize admin bot for chat.")
    return hub_url, admin_token, target_agent_name


def _ensure_admin_bot(hub_url: str) -> str:
    """Return admin bot token, registering one if needed. Cached in DB settings."""
    from ..database import get_setting, set_setting
    from ..services.install_service import _get_org_id, _get_org_secret

    token = get_setting("hxa_admin_bot_token", "")
    if token:
        # Verify token is still valid by calling /api/me (lightweight check)
        try:
            req = urllib.request.Request(
                f"{hub_url}/api/bots?limit=1",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
            return token
        except Exception:
            # Token invalid, re-register
            pass

    # Register a new admin bot
    org_secret = _get_org_secret()
    org_id = _get_org_id()
    if not org_secret:
        return ""

    origin = "https://www.ucai.net"
    admin_name = "hire_admin_panel"

    try:
        # Step 1: Admin login
        login_data = json.dumps({"type": "org_admin", "org_secret": org_secret, "org_id": org_id}).encode()
        login_req = urllib.request.Request(
            f"{hub_url}/api/auth/login", data=login_data,
            headers={"Content-Type": "application/json", "Origin": origin}, method="POST",
        )
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]

        # Step 2: Cleanup existing bot with same name (best effort)
        try:
            bots_req = urllib.request.Request(
                f"{hub_url}/api/bots?limit=200",
                headers={"Cookie": cookie, "Origin": origin},
            )
            with urllib.request.urlopen(bots_req, timeout=10) as resp:
                bots = json.loads(resp.read().decode())
            items = bots if isinstance(bots, list) else bots.get("items", [])
            for b in items:
                if b.get("name") == admin_name:
                    del_req = urllib.request.Request(
                        f"{hub_url}/api/bots/{b['id']}",
                        headers={"Cookie": cookie, "Origin": origin},
                        method="DELETE",
                    )
                    urllib.request.urlopen(del_req, timeout=10)
                    break
        except Exception:
            pass

        # Step 3: Create ticket
        ticket_data = json.dumps({"reusable": False}).encode()
        ticket_req = urllib.request.Request(
            f"{hub_url}/api/org/tickets", data=ticket_data,
            headers={"Content-Type": "application/json", "Cookie": cookie, "Origin": origin},
            method="POST",
        )
        with urllib.request.urlopen(ticket_req, timeout=10) as resp:
            ticket_result = json.loads(resp.read().decode())
        ticket_secret = ticket_result.get("secret") or ticket_result.get("ticket") or ""
        if not ticket_secret:
            return ""

        # Step 4: Register admin bot
        reg_data = json.dumps({"org_id": org_id, "ticket": ticket_secret, "name": admin_name}).encode()
        reg_req = urllib.request.Request(
            f"{hub_url}/api/auth/register", data=reg_data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(reg_req, timeout=15) as resp:
            result = json.loads(resp.read().decode())

        new_token = result.get("token", "")
        if new_token:
            set_setting("hxa_admin_bot_token", new_token)
            set_setting("hxa_admin_bot_name", admin_name)
            return new_token
    except Exception:
        pass
    return ""


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
            "Origin": "https://www.ucai.net",
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
    db: sqlite3.Connection = Depends(get_db),
):
    """Return chat info: target bot status and admin bot name."""
    from ..database import get_setting
    hub_url, admin_token, target_name = _get_chat_config(instance_id, current_user["id"], db)
    admin_bot_name = get_setting("hxa_admin_bot_name", "MW_OpenClaw")
    # Check if target bot is online
    result = _hub_request(hub_url, admin_token, "GET", "/api/bots?limit=100")
    bots = result if isinstance(result, list) else result.get("items", [])
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
        "dm_channel_id": dm_channel_id,
    }


from pydantic import BaseModel as _BaseModel


class _ChatSendRequest(_BaseModel):
    content: str


@router.post("/{instance_id}/chat/send")
def chat_send(
    instance_id: str,
    req: _ChatSendRequest,
    current_user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Send a DM to the instance bot via admin bot."""
    hub_url, admin_token, target_name = _get_chat_config(instance_id, current_user["id"], db)
    result = _hub_request(hub_url, admin_token, "POST", "/api/send", {"to": target_name, "content": req.content})
    return result


@router.get("/{instance_id}/chat/messages")
def chat_messages(
    instance_id: str,
    channel_id: str,
    before: str | None = None,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get messages from a DM channel."""
    hub_url, admin_token, _ = _get_chat_config(instance_id, current_user["id"], db)
    params = [f"limit={min(limit, 200)}"]
    if before:
        params.append(f"before={before}")
    qs = "&".join(params)
    result = _hub_request(hub_url, admin_token, "GET", f"/api/channels/{channel_id}/messages?{qs}")
    return result


@router.post("/{instance_id}/chat/ws-ticket")
def chat_ws_ticket(
    instance_id: str,
    current_user=Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get a WebSocket ticket for real-time chat (using admin bot identity)."""
    hub_url, admin_token, _ = _get_chat_config(instance_id, current_user["id"], db)
    result = _hub_request(hub_url, admin_token, "POST", "/api/ws-ticket", {})
    ws_url = hub_url.replace("https://", "wss://").replace("http://", "ws://")
    if not ws_url.endswith("/ws"):
        ws_url = ws_url.rstrip("/") + "/ws"
    return {"ticket": result["ticket"], "ws_url": ws_url}
