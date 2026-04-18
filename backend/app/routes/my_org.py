"""My Organization — user-facing org view + chat proxy with identity switching."""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from ..database import get_setting, get_connection, site_base_url, runtime_root
from ..deps import get_current_user, get_db
from ..schemas import CreateTaskRequest, QCConfigRequest
from ..services.install_service import _get_hub_url
from ..services.task_protocol import format_task_assignment, format_revision_request, parse_task_completion, build_thread_context_qc
from ..services.quality_gate import evaluate_response, should_request_revision
from .admin_hxa import _get_agent_token, _hub_admin_request, _hub_org_admin_request, _cleanup_bot_and_tombstone, _write_new_token, _restart_hxa_connect
from .instances import _hub_request, _ensure_user_bot, _make_admin_bot_name

router = APIRouter(prefix="/api/my-org", tags=["my-org"])


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _get_user_org_info(user_id: str, db, target_org_id: str = "") -> dict:
    """Return user's org context: instances, org_id, etc.
    If target_org_id given, scope to that org. Otherwise pick first."""
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        """SELECT i.id, i.name, i.product, i.agent_name, i.install_state,
                  c.org_id, c.agent_name AS cfg_agent_name
           FROM instances i
           LEFT JOIN instance_configs c ON i.id = c.instance_id
           WHERE i.owner_id = %s
           ORDER BY i.created_at DESC""",
        (user_id,),
    )
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        return {"status": "no_instances"}

    # Collect all org_ids and bots per org
    orgs_seen: dict[str, list[dict]] = {}
    all_bots: list[dict] = []
    for r in rows:
        agent_name = r["cfg_agent_name"] or r["agent_name"] or ""
        oid = r["org_id"] or ""
        bot_info = {
            "instance_id": r["id"],
            "instance_name": r["name"],
            "agent_name": agent_name,
            "product": r["product"],
            "org_id": oid,
        }
        if agent_name:
            all_bots.append(bot_info)
        if oid:
            orgs_seen.setdefault(oid, [])
            if agent_name:
                orgs_seen[oid].append(bot_info)

    if not orgs_seen:
        return {"status": "no_org", "my_bots": all_bots}

    # Pick org
    if target_org_id and target_org_id in orgs_seen:
        org_id = target_org_id
    else:
        org_id = next(iter(orgs_seen))

    my_bots = orgs_seen.get(org_id, [])
    org_ids = list(orgs_seen.keys())

    # all_my_agent_names: user's bots across ALL orgs (for "is mine" checks even after org transfer)
    all_my_agent_names = {b["agent_name"] for b in all_bots if b["agent_name"]}
    return {"status": "ok", "org_id": org_id, "my_bots": my_bots, "all_org_ids": org_ids, "all_my_agent_names": all_my_agent_names}


def _resolve_org_secret(org_id: str) -> str:
    default_org_id = get_setting("hxa_org_id", "")
    if org_id == default_org_id:
        return get_setting("hxa_org_secret", "")
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT org_secret FROM org_secrets WHERE org_id = %s", (org_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    return row["org_secret"] if row else ""


def _get_org_bots(org_id: str, org_secret: str) -> list[dict]:
    """Get bot list from Hub via org admin login."""
    try:
        result = _hub_org_admin_request("GET", "/api/bots", org_id, org_secret)
        if isinstance(result, list):
            return result
        return result.get("bots", []) if isinstance(result, dict) else []
    except Exception:
        return []


def _get_org_name(org_id: str) -> str:
    """Get org name from Hub admin API."""
    try:
        orgs = _hub_admin_request("GET", "/api/orgs")
        for o in (orgs or []):
            if o.get("id") == org_id:
                return o.get("name", "")
    except Exception:
        pass
    # Fallback to local
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT org_name FROM org_secrets WHERE org_id = %s", (org_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    return row["org_name"] if row else org_id[:12]


def _pick_chat_token(
    user_id: str, target_bot_name: str, my_bot_names_in_org: set[str],
    hub_url: str, db, org_id: str = "", sender_bot: str | None = None,
) -> tuple[str, str]:
    """Pick the right token for chatting.
    Returns (token, identity_type) where identity_type is 'admin' or instance_id.

    - Target is MY bot (in CURRENT org) → use admin bot token (in same org)
    - Target is OTHER's bot → use my instance bot token in same org
    - sender_bot: if user has multiple bots in the org, specify which one sends
    """
    if target_bot_name in my_bot_names_in_org:
        # Chat with own bot → use admin bot in the SAME org
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user_row = cursor.fetchone()
        cursor.close()
        display_name = user_row["name"] if user_row else ""
        token = _ensure_user_bot(hub_url, user_id, display_name, target_org_id=org_id or None)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to initialize admin bot.")
        return token, "admin"
    else:
        # Chat with other's bot → use my instance bot in the SAME org
        cursor = db.cursor(dictionary=True)
        if sender_bot and org_id:
            # User explicitly chose which bot to send as
            cursor.execute(
                """SELECT i.id FROM instances i
                   JOIN instance_configs c ON i.id = c.instance_id
                   WHERE i.owner_id = %s AND c.org_id = %s AND c.agent_name = %s
                   LIMIT 1""",
                (user_id, org_id, sender_bot),
            )
            rows = cursor.fetchall()
        else:
            rows = []
        if not rows and org_id:
            # Find any of my bots in the same org
            cursor.execute(
                """SELECT i.id FROM instances i
                   JOIN instance_configs c ON i.id = c.instance_id
                   WHERE i.owner_id = %s AND c.org_id = %s AND c.agent_name IS NOT NULL AND c.agent_name != ''
                   ORDER BY i.created_at ASC LIMIT 1""",
                (user_id, org_id),
            )
            rows = cursor.fetchall()
        if not rows:
            # Fallback: any instance with a configured agent
            cursor.execute(
                """SELECT i.id FROM instances i
                   JOIN instance_configs c ON i.id = c.instance_id
                   WHERE i.owner_id = %s AND c.agent_name IS NOT NULL AND c.agent_name != ''
                   ORDER BY i.created_at ASC LIMIT 1""",
                (user_id,),
            )
            rows = cursor.fetchall()
        cursor.close()
        if not rows:
            raise HTTPException(status_code=400, detail="You have no configured bot to chat with.")
        instance_id = rows[0]["id"]
        token = _get_agent_token(instance_id)
        if not token:
            raise HTTPException(status_code=400, detail="Your bot token is not available.")
        return token, instance_id


# ---------------------------------------------------------------------------
#  Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def get_my_org(
    org_id: str = Query("", alias="org"),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get user's organization info and bot list. Supports multi-org via ?org=id."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org_id)

    if info["status"] != "ok":
        return info

    active_org_id = info["org_id"]
    default_org_id = get_setting("hxa_org_id", "")
    org_name = _get_org_name(active_org_id)

    # Build orgs list with names
    all_org_ids = info.get("all_org_ids", [active_org_id])
    orgs_list = []
    for oid in all_org_ids:
        orgs_list.append({
            "org_id": oid,
            "org_name": _get_org_name(oid),
            "is_default": oid == default_org_id,
            "is_active": oid == active_org_id,
        })

    # Get all bots in active org
    org_secret = _resolve_org_secret(active_org_id)
    all_bots_raw = _get_org_bots(active_org_id, org_secret) if org_secret else []

    my_agent_names = info.get("all_my_agent_names", {b["agent_name"] for b in info["my_bots"]})

    # Filter to instance bots only — exclude admin/user bots
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT DISTINCT c.agent_name FROM instance_configs c
               JOIN instances i ON c.instance_id = i.id
               WHERE c.agent_name IS NOT NULL AND c.agent_name != ''""",
        )
        inst_rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    instance_agent_names = {r["agent_name"] for r in inst_rows}

    # Auto-generated instance bot names start with the agent prefix (default "hire_")
    import os
    agent_prefix = os.getenv("HXA_CONNECT_AGENT_PREFIX", "hire") + "_"

    # Get the admin panel bot name to exclude it
    admin_bot_name = get_setting("hxa_admin_bot_name", "hire_admin_panel")

    def _is_instance_bot(name: str) -> bool:
        """Check if a bot is an instance bot (not an admin/user bot)."""
        if name == admin_bot_name:
            return False
        return name in instance_agent_names or name.startswith(agent_prefix)

    all_bots = []
    # Sync DB org_id with Hub reality (Hub is source of truth)
    hub_bot_names_in_org = set()
    for b in all_bots_raw:
        bot_name = b.get("name", "")
        hub_bot_names_in_org.add(bot_name)
        if not _is_instance_bot(bot_name):
            continue
        all_bots.append({
            "bot_id": b.get("id", ""),
            "name": bot_name,
            "online": b.get("online", False),
            "is_mine": bot_name in my_agent_names,
            "avatar_url": b.get("avatar_url"),
        })

    # Fix stale org_id in DB: if a bot appears in this Hub org but DB says different org, update DB
    if hub_bot_names_in_org and my_agent_names:
        my_bots_in_hub = hub_bot_names_in_org & my_agent_names
        if my_bots_in_hub:
            try:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    for name in my_bots_in_hub:
                        cursor.execute(
                            """UPDATE instance_configs SET org_id = %s
                               WHERE agent_name = %s AND (org_id IS NULL OR org_id != %s)""",
                            (active_org_id, name, active_org_id),
                        )
                    cursor.close()
                finally:
                    conn.close()
            except Exception:
                pass  # Best effort sync

    # Fix orphaned bots: DB says bot is in this org, but Hub doesn't have it.
    # This can happen when a transfer's delete step succeeded but registration failed.
    if org_secret and my_agent_names:
        # Find bots whose DB org_id matches active_org_id but are missing from Hub
        db_bots_for_org = {b["agent_name"] for b in info["my_bots"]
                          if b.get("org_id") == active_org_id and b.get("agent_name")}
        orphaned = db_bots_for_org - hub_bot_names_in_org
        hub = _get_hub_url().rstrip("/")
        repaired = 0
        for orphan_name in orphaned:
            if repaired >= 2:
                break  # Limit to avoid slow page loads
            try:
                # Find instance_id for this bot
                conn = get_connection()
                try:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute(
                        "SELECT instance_id FROM instance_configs WHERE agent_name = %s AND org_id = %s",
                        (orphan_name, active_org_id),
                    )
                    orphan_row = cursor.fetchone()
                    cursor.close()
                finally:
                    conn.close()
                if not orphan_row:
                    continue
                orphan_instance_id = orphan_row["instance_id"]

                # Cleanup tombstone + re-register
                _cleanup_bot_and_tombstone(hub, active_org_id, org_secret, orphan_name)
                ticket_result = _hub_org_admin_request(
                    "POST", "/api/org/tickets", active_org_id, org_secret,
                    {"reusable": False, "skip_approval": True},
                )
                ticket_secret = ticket_result.get("ticket", "") if ticket_result else ""
                if not ticket_secret:
                    continue

                reg_data = json.dumps({"org_id": active_org_id, "ticket": ticket_secret, "name": orphan_name}).encode()
                reg_req = urllib.request.Request(
                    f"{hub}/api/auth/register", data=reg_data,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(reg_req, timeout=15) as resp:
                    reg_result = json.loads(resp.read().decode())
                new_token = reg_result.get("token", "")
                if new_token:
                    # Update DB token
                    conn = get_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE instance_configs SET org_token = %s WHERE instance_id = %s",
                            (new_token, orphan_instance_id),
                        )
                        cursor.close()
                    finally:
                        conn.close()
                    # Update container config + restart
                    _write_new_token(orphan_instance_id, new_token, orphan_name, active_org_id)
                    _restart_hxa_connect(orphan_instance_id)
                    # Add repaired bot to response
                    all_bots.append({
                        "bot_id": reg_result.get("bot_id", ""),
                        "name": orphan_name,
                        "online": False,
                        "is_mine": True,
                        "avatar_url": None,
                    })
                    repaired += 1
            except Exception:
                pass  # Best effort — skip this orphan

    return {
        "status": "ok",
        "org_id": active_org_id,
        "org_name": org_name,
        "is_default_org": active_org_id == default_org_id,
        "my_bots": info["my_bots"],
        "all_bots": all_bots,
        "orgs": orgs_list,
    }


class OrgChatSendRequest(BaseModel):
    target_bot_name: str
    content: str
    image_url: str | None = None
    org_id: str | None = None
    sender_bot: str | None = None  # When user has multiple bots in org, specify which one sends


@router.post("/chat/send")
def org_chat_send(
    req: OrgChatSendRequest,
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Send a message to a bot in the org. Identity depends on target."""
    user_id = current_user["id"]
    # Use the org_id from the request (current page), not auto-detected
    active_org_id = req.org_id or ""
    info = _get_user_org_info(user_id, db, target_org_id=active_org_id or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    org_id = info.get("org_id", "")
    hub_url = _get_hub_url().rstrip("/")
    # Only check bots in the CURRENT org for "is mine" detection
    my_bot_names_in_org = {b["agent_name"] for b in info["my_bots"] if b.get("agent_name")}
    token, _ = _pick_chat_token(
        user_id, req.target_bot_name, my_bot_names_in_org, hub_url, db,
        org_id=org_id, sender_bot=req.sender_bot,
    )

    content = req.content
    if req.image_url:
        content = f"[image]({req.image_url})\n{content}" if content else f"[image]({req.image_url})"

    result = _hub_request(hub_url, token, "POST", "/api/send", {
        "to": req.target_bot_name,
        "content": content,
    })
    return result


@router.get("/chat/info")
def org_chat_info(
    target: str = Query(...),
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get chat info for a target bot.

    Uses instance bot token to query org info (no admin bot needed).
    Admin bot identity is only resolved when target is user's own bot (for DM).
    """
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    # Only check bots in the CURRENT org
    my_agent_names_in_org = {b["agent_name"] for b in info["my_bots"] if b.get("agent_name")}

    # Use first instance bot to query org info (always available, no admin bot needed)
    query_token = None
    if info["my_bots"]:
        query_token = _get_agent_token(info["my_bots"][0]["instance_id"])
    if not query_token:
        raise HTTPException(status_code=400, detail="No bot available in this organization.")

    try:
        me = _hub_request(hub_url, query_token, "GET", "/api/me")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to get bot identity.")

    # Determine the actual chat identity (admin bot for own bot DM, instance bot otherwise)
    is_own_bot = target in my_agent_names_in_org
    if is_own_bot:
        org_id = info.get("org_id", "")
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user_row = _cur.fetchone()
        _cur.close()
        display_name = user_row["name"] if user_row else ""
        admin_token = _ensure_user_bot(hub_url, user_id, display_name, target_org_id=org_id or None)
        if admin_token:
            try:
                admin_me = _hub_request(hub_url, admin_token, "GET", "/api/me")
                my_bot_id = admin_me.get("id", "")
                my_bot_name = admin_me.get("name", "")
            except Exception:
                my_bot_id = me.get("id", "")
                my_bot_name = me.get("name", "")
        else:
            my_bot_id = me.get("id", "")
            my_bot_name = me.get("name", "")
    else:
        admin_token = None
        my_bot_id = me.get("id", "")
        my_bot_name = me.get("name", "")

    # Get target bot info
    try:
        bots = _hub_request(hub_url, query_token, "GET", "/api/bots")
        if isinstance(bots, dict):
            bots = bots.get("bots", [])
    except Exception:
        bots = []

    target_bot = next((b for b in bots if b.get("name") == target), None)
    target_id = target_bot.get("id", "") if target_bot else ""
    target_online = target_bot.get("online", False) if target_bot else False

    # Find existing DM channel — use the identity token (admin_token for own bot, query_token for others)
    chat_token = admin_token if (is_own_bot and admin_token) else query_token
    dm_channel_id = ""
    try:
        inbox = _hub_request(hub_url, chat_token, "GET", "/api/inbox?since=0&limit=100")
        if isinstance(inbox, list):
            for item in inbox:
                msg = item if isinstance(item, dict) else {}
                # Match by sender id/name OR recipient id/name
                if msg.get("sender_id") == target_id or msg.get("sender_name") == target:
                    dm_channel_id = msg.get("channel_id", "")
                    break
                if msg.get("recipient_id") == target_id or msg.get("recipient_name") == target:
                    dm_channel_id = msg.get("channel_id", "")
                    break
    except Exception:
        pass

    # Instance bot identity (first instance bot in this org)
    instance_bot_id = me.get("id", "")
    instance_bot_name = me.get("name", "")

    return {
        "target_name": target,
        "target_online": target_online,
        "target_id": target_id,
        "admin_bot_name": my_bot_name,
        "admin_bot_id": my_bot_id,
        "instance_bot_name": instance_bot_name,
        "instance_bot_id": instance_bot_id,
        "dm_channel_id": dm_channel_id,
    }


@router.get("/chat/messages")
def org_chat_messages(
    channel_id: str = Query(...),
    target: str = Query(...),
    before: str = Query(""),
    limit: int = Query(50),
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get messages for a DM channel."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_bot_names_in_org = {b["agent_name"] for b in info["my_bots"] if b.get("agent_name")}
    token, _ = _pick_chat_token(user_id, target, my_bot_names_in_org, hub_url, db, org_id=info.get("org_id", ""))

    params = f"limit={limit}"
    if before:
        params += f"&before={before}"
    result = _hub_request(hub_url, token, "GET", f"/api/channels/{channel_id}/messages?{params}")
    messages = result if isinstance(result, list) else result.get("messages", [])
    return {"messages": messages, "has_more": len(messages) >= limit}


@router.post("/chat/ws-ticket")
def org_chat_ws_ticket(
    target: str = Query(""),
    mode: str = Query("dm"),
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get WebSocket ticket. mode=dm uses chat identity, mode=thread uses instance bot."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_bot_names_in_org = {b["agent_name"] for b in info["my_bots"] if b.get("agent_name")}

    if mode == "thread":
        # Thread WS must use instance bot (thread participant)
        if info["my_bots"]:
            token = _get_agent_token(info["my_bots"][0]["instance_id"])
        else:
            token = None
        if not token:
            raise HTTPException(status_code=400, detail="No instance bot available for thread WS.")
    elif target:
        token, _ = _pick_chat_token(user_id, target, my_bot_names_in_org, hub_url, db, org_id=info.get("org_id", ""))
    else:
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user_row = _cur.fetchone()
        _cur.close()
        display_name = user_row["name"] if user_row else ""
        token = _ensure_user_bot(hub_url, user_id, display_name)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to initialize admin bot.")

    result = _hub_request(hub_url, token, "POST", "/api/ws-ticket", {})
    ws_url = hub_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    return {"ticket": result.get("ticket", ""), "ws_url": ws_url}


_UPLOAD_DIR = Path(runtime_root()).parent / "frontend" / "dist" / "uploads"
_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_ALLOWED_FILE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".csv", ".zip", ".tar", ".gz", ".json", ".xml", ".mp3", ".mp4", ".wav"}
_MAX_IMAGE_SIZE = 10 * 1024 * 1024
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB for general files


@router.post("/chat/upload")
async def org_chat_upload(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload an image and return a public URL."""
    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}")
    data = await file.read()
    if len(data) > _MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex[:16]}{ext}"
    (_UPLOAD_DIR / filename).write_bytes(data)
    return {"url": f"{site_base_url()}/uploads/{filename}", "filename": filename}


@router.post("/file/upload")
async def org_file_upload(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload any file and return a public URL + metadata."""
    original_name = file.filename or "file"
    ext = Path(original_name).suffix.lower()
    if ext not in _ALLOWED_FILE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    data = await file.read()
    if len(data) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid4().hex[:12]}_{Path(original_name).stem[:30]}{ext}"
    (_UPLOAD_DIR / safe_name).write_bytes(data)
    size_kb = round(len(data) / 1024, 1)
    return {
        "url": f"{site_base_url()}/uploads/{safe_name}",
        "filename": original_name,
        "size_kb": size_kb,
    }


# ---------------------------------------------------------------------------
#  Thread (Group Chat) endpoints
# ---------------------------------------------------------------------------

class CreateThreadRequest(BaseModel):
    topic: str
    participant_names: list[str] = []


@router.post("/threads")
def create_thread(
    req: CreateThreadRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Create a new thread and invite participants."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    # Use admin bot to create thread (as the user's identity)
    _cur = db.cursor(dictionary=True)
    _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
    user_row = _cur.fetchone()
    _cur.close()
    display_name = user_row["name"] if user_row else ""

    # Determine which token to use - prefer first instance bot
    my_agent_names = info.get("all_my_agent_names", {b["agent_name"] for b in info["my_bots"]})
    if info["my_bots"]:
        token = _get_agent_token(info["my_bots"][0]["instance_id"])
    else:
        token = _ensure_user_bot(hub_url, user_id, display_name)
    if not token:
        raise HTTPException(status_code=500, detail="No bot available to create thread.")

    # Create thread
    result = _hub_request(hub_url, token, "POST", "/api/threads", {
        "topic": req.topic,
    })
    thread_id = result.get("id", "")
    if not thread_id:
        raise HTTPException(status_code=502, detail="Thread creation failed.")

    # Invite participants by name — Hub requires bot_id, so resolve name→id first
    if req.participant_names:
        try:
            bots_result = _hub_request(hub_url, token, "GET", "/api/bots")
            bots_list = bots_result if isinstance(bots_result, list) else bots_result.get("bots", bots_result.get("items", []))
            name_to_id = {b.get("name", ""): b.get("id", "") for b in bots_list}
        except Exception:
            name_to_id = {}

        # The creator bot is auto-joined, skip only that one
        creator_name = info["my_bots"][0]["agent_name"] if info["my_bots"] else ""
        for name in req.participant_names:
            if name == creator_name:
                continue  # Skip creator (already joined)
            bot_id = name_to_id.get(name, name)  # Fall back to name (resolveBot supports both)
            try:
                _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/participants", {"bot_id": bot_id})
            except Exception:
                pass  # Best effort invite

    return result


@router.get("/threads")
def list_threads(
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """List threads the user's bots participate in (current org only)."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    current_org_id = info.get("org_id", "")

    # Query threads from ALL user's bots in this org, merge & dedup
    seen_ids: set[str] = set()
    all_threads: list[dict] = []
    tokens: list[str] = []
    for bot in info.get("my_bots", []):
        t = _get_agent_token(bot["instance_id"])
        if t:
            tokens.append(t)
    if not tokens:
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user_row = _cur.fetchone()
        _cur.close()
        t = _ensure_user_bot(hub_url, user_id, user_row["name"] if user_row else "")
        if t:
            tokens.append(t)
    for token in tokens:
        try:
            result = _hub_request(hub_url, token, "GET", "/api/threads?status=active&limit=50")
            items = result if isinstance(result, list) else result.get("threads", result.get("items", []))
            for th in items:
                tid = th.get("id", "")
                # Filter: only threads belonging to current org
                if tid and tid not in seen_ids and th.get("org_id", "") == current_org_id:
                    seen_ids.add(tid)
                    all_threads.append(th)
        except Exception:
            pass

    return {"threads": all_threads}


@router.get("/threads/{thread_id}/messages")
def thread_messages(
    thread_id: str,
    before: str = Query(""),
    limit: int = Query(50),
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get messages in a thread."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")

    params = f"limit={limit}"
    if before:
        params += f"&before={before}"
    result = _hub_request(hub_url, token, "GET", f"/api/threads/{thread_id}/messages?{params}")
    messages = result if isinstance(result, list) else result.get("messages", result.get("items", []))
    return {"messages": messages, "has_more": len(messages) >= limit}


class ThreadSendRequest(BaseModel):
    content: str
    image_url: str | None = None
    bot_instance_id: str | None = None  # which bot to send as (for multi-bot users)
    task_id: str | None = None          # link message to existing task
    as_task: CreateTaskRequest | None = None  # create a new task inline


@router.post("/threads/{thread_id}/messages")
def thread_send(
    thread_id: str,
    req: ThreadSendRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Send a message to a thread using instance bot identity."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")

    # Use specified bot or first instance bot to send in threads
    chosen_id = req.bot_instance_id
    if chosen_id and any(b["instance_id"] == chosen_id for b in info["my_bots"]):
        token = _get_agent_token(chosen_id)
    elif info["my_bots"]:
        token = _get_agent_token(info["my_bots"][0]["instance_id"])
    else:
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user_row = _cur.fetchone()
        _cur.close()
        token = _ensure_user_bot(hub_url, user_id, user_row["name"] if user_row else "")
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")

    content = req.content
    if req.image_url:
        content = f"[image]({req.image_url})\n{content}" if content else f"[image]({req.image_url})"

    # ── Task Protocol: 包装结构化任务 ──
    task_record = None
    if req.as_task:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task_id = str(uuid4())[:12]
        org_id = info.get("org_id", "")

        # 获取发送者 bot name
        sender_name = ""
        try:
            me = _hub_request(hub_url, token, "GET", "/api/me")
            sender_name = me.get("name", "")
        except Exception:
            pass

        criteria_json = json.dumps(req.as_task.acceptance_criteria, ensure_ascii=False)
        task_record = {
            "id": task_id,
            "thread_id": thread_id,
            "org_id": org_id,
            "assigned_to": req.as_task.assigned_to or "",
            "assigned_by": sender_name,
            "title": req.as_task.title,
            "description": req.as_task.description or content,
            "acceptance_criteria": criteria_json,
            "depth": req.as_task.depth,
            "status": "in_progress",
            "revision_count": 0,
            "max_revisions": 2,
            "created_at": now,
            "updated_at": now,
        }

        # 写入数据库
        cursor = db.cursor()
        cursor.execute(
            """INSERT INTO thread_tasks
               (id, thread_id, org_id, assigned_to, assigned_by, title, description,
                acceptance_criteria, depth, status, revision_count, max_revisions, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (task_id, thread_id, org_id, task_record["assigned_to"], sender_name,
             req.as_task.title, task_record["description"], criteria_json,
             req.as_task.depth, "in_progress", 0, 2, now, now),
        )
        cursor.close()

        # 用 task protocol 包装消息
        content = format_task_assignment(task_record, content)

    result = _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/messages", {
        "content": content,
    })

    # 如果创建了任务，返回任务信息
    if task_record:
        result = result if isinstance(result, dict) else {}
        result["task"] = task_record

    return result


def _get_thread_token(
    user_id: str,
    info: dict,
    hub_url: str,
    db,
    thread_id: str | None = None,
) -> str:
    """Get a bot token for thread operations.

    If ``thread_id`` is given, probe each candidate token against
    GET /api/threads/{id} and return the first one whose bot is actually
    a participant — this avoids "Not a participant of this thread" 403s
    when a user has multiple bots and the current top-of-list one isn't
    in the thread yet (common after creating a new Local Agent).
    """
    candidates: list[str] = []
    for b in info.get("my_bots", []) or []:
        tok = _get_agent_token(b["instance_id"])
        if tok and tok not in candidates:
            candidates.append(tok)
    # Admin bot is the universal fallback — the hub user's personal bot.
    try:
        _cur = db.cursor(dictionary=True)
        _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user_row = _cur.fetchone()
        _cur.close()
        admin = _ensure_user_bot(
            hub_url,
            user_id,
            user_row["name"] if user_row else "",
            target_org_id=info.get("org_id") or None,
        )
        if admin and admin not in candidates:
            candidates.append(admin)
    except Exception:
        pass

    if not candidates:
        return ""
    if not thread_id:
        return candidates[0]

    # Pick the first candidate that's a participant of this thread.
    for tok in candidates:
        try:
            probe = urllib.request.Request(
                f"{hub_url}/api/threads/{thread_id}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            with urllib.request.urlopen(probe, timeout=5) as _resp:
                _resp.read()
            return tok
        except urllib.error.HTTPError as e:
            # 403/404 → not a participant; try next. Other errors → give up
            # and return the first so the caller surfaces a real error.
            if e.code in (403, 404):
                continue
            return candidates[0]
        except Exception:
            continue
    # Nothing is a participant — return first so caller can propagate the
    # actual hub error verbatim (likely 403 NOT_PARTICIPANT).
    return candidates[0]


@router.get("/threads/{thread_id}")
def get_thread_detail(
    thread_id: str,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Get thread detail with participants."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")
    return _hub_request(hub_url, token, "GET", f"/api/threads/{thread_id}")


class UpdateThreadRequest(BaseModel):
    topic: str | None = None
    context: dict | None = None


@router.patch("/threads/{thread_id}")
def update_thread(
    thread_id: str,
    req: UpdateThreadRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Update thread topic or context (announcement)."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")

    body: dict = {}
    if req.topic is not None:
        body["topic"] = req.topic
    if req.context is not None:
        body["context"] = json.dumps(req.context)
    if not body:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    return _hub_request(hub_url, token, "PATCH", f"/api/threads/{thread_id}", body)


@router.post("/threads/{thread_id}/leave")
def leave_thread(
    thread_id: str,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Leave a thread. Sends DM to initiator notifying departure."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")

    # Get thread detail to find initiator
    thread = _hub_request(hub_url, token, "GET", f"/api/threads/{thread_id}")
    initiator_id = thread.get("initiator_id", "")
    thread_topic = thread.get("topic", "")

    # Get my bot info
    me = _hub_request(hub_url, token, "GET", "/api/me")
    my_bot_id = me.get("id", "")
    my_bot_name = me.get("name", "")

    # Leave thread
    _hub_request(hub_url, token, "DELETE", f"/api/threads/{thread_id}/participants/{my_bot_id}")

    # Notify initiator via DM
    if initiator_id and initiator_id != my_bot_id:
        try:
            # Find initiator name
            participants = thread.get("participants", [])
            initiator_name = ""
            for p in participants:
                if p.get("bot_id") == initiator_id:
                    initiator_name = p.get("name", "")
                    break
            if initiator_name:
                _hub_request(hub_url, token, "POST", "/api/send", {
                    "to": initiator_name,
                    "content": f"[通知] {my_bot_name} 已退出群聊「{thread_topic}」",
                })
        except Exception:
            pass  # Best effort notification

    return {"ok": True}


class InviteRequest(BaseModel):
    name: str


@router.post("/threads/{thread_id}/invite")
def invite_to_thread(
    thread_id: str,
    req: InviteRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Invite a bot to thread by name."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")
    # Hub requires bot_id, resolve name first
    return _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/participants", {"bot_id": req.name})


class KickRequest(BaseModel):
    bot_id: str


@router.post("/threads/{thread_id}/kick")
def kick_from_thread(
    thread_id: str,
    req: KickRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Remove a bot from thread (creator only)."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")
    try:
        _hub_request(hub_url, token, "DELETE", f"/api/threads/{thread_id}/participants/{req.bot_id}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
#  Message Search
# ---------------------------------------------------------------------------

@router.post("/search/sync")
def search_sync(
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Trigger message sync for search index."""
    from ..message_index import sync_messages

    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    org_id = info["org_id"]

    # Collect all tokens (instance bots + admin bot)
    tokens: list[tuple[str, str]] = []
    for bot in info["my_bots"]:
        t = _get_agent_token(bot["instance_id"])
        if t:
            tokens.append((t, bot["agent_name"]))

    # Also add admin bot
    _cur = db.cursor(dictionary=True)
    _cur.execute("SELECT name FROM users WHERE id = %s", (user_id,))
    user_row = _cur.fetchone()
    _cur.close()
    display_name = user_row["name"] if user_row else ""
    admin_token = _ensure_user_bot(hub_url, user_id, display_name, target_org_id=org_id or None)
    if admin_token:
        bot_name = _make_admin_bot_name(display_name, user_id)
        tokens.append((admin_token, bot_name))

    count = sync_messages(user_id, org_id, tokens, hub_url)
    return {"ok": True, "new_messages": count}


@router.get("/search")
def search_messages_endpoint(
    q: str = Query(""),
    in_channel: str = Query("", alias="in"),
    from_sender: str = Query("", alias="from"),
    to_name: str = Query("", alias="to"),
    limit: int = Query(50),
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db = Depends(get_db),
):
    """Search indexed messages."""
    from ..message_index import search_messages

    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    org_id = info["org_id"]
    results = search_messages(org_id, query=q, in_channel=in_channel, from_sender=from_sender, to_name=to_name, limit=limit)
    return {"results": results, "total": len(results)}


# ---------------------------------------------------------------------------
#  Thread Quality Control (QC)
# ---------------------------------------------------------------------------

@router.post("/threads/{thread_id}/qc")
def enable_thread_qc(
    thread_id: str,
    req: QCConfigRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Enable quality control for a thread."""
    import datetime
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    org_id = info.get("org_id", "")

    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO thread_qc_config
           (thread_id, org_id, enabled, min_quality_score, auto_revision, max_revisions, evaluator_api_key, created_at, updated_at)
           VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE
           enabled=1, min_quality_score=VALUES(min_quality_score),
           auto_revision=VALUES(auto_revision), max_revisions=VALUES(max_revisions),
           evaluator_api_key=COALESCE(VALUES(evaluator_api_key), evaluator_api_key),
           updated_at=VALUES(updated_at)""",
        (thread_id, org_id, req.min_quality_score, int(req.auto_revision),
         req.max_revisions, req.evaluator_api_key, now, now),
    )
    cursor.close()
    return {"ok": True, "thread_id": thread_id, "enabled": True}


@router.get("/threads/{thread_id}/qc")
def get_thread_qc(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get QC config for a thread."""
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM thread_qc_config WHERE thread_id = %s", (thread_id,))
    row = cursor.fetchone()
    cursor.close()
    if not row:
        return {"enabled": False, "thread_id": thread_id}
    return {
        "thread_id": thread_id,
        "enabled": bool(row["enabled"]),
        "min_quality_score": row["min_quality_score"],
        "auto_revision": bool(row["auto_revision"]),
        "max_revisions": row["max_revisions"],
        "has_api_key": bool(row.get("evaluator_api_key")),
    }


@router.delete("/threads/{thread_id}/qc")
def disable_thread_qc(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Disable QC for a thread."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE thread_qc_config SET enabled=0, updated_at=%s WHERE thread_id=%s",
        (now, thread_id),
    )
    cursor.close()
    return {"ok": True, "thread_id": thread_id, "enabled": False}


# ---------------------------------------------------------------------------
#  Thread Tasks
# ---------------------------------------------------------------------------

@router.post("/threads/{thread_id}/tasks")
def create_thread_task(
    thread_id: str,
    req: CreateTaskRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Create a task in a thread (without sending a message)."""
    import datetime
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    task_id = str(uuid4())[:12]
    org_id = info.get("org_id", "")
    criteria_json = json.dumps(req.acceptance_criteria, ensure_ascii=False)

    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO thread_tasks
           (id, thread_id, org_id, assigned_to, assigned_by, title, description,
            acceptance_criteria, depth, status, revision_count, max_revisions, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (task_id, thread_id, org_id, req.assigned_to or "", "",
         req.title, req.description or "", criteria_json,
         req.depth, "pending", 0, 2, now, now),
    )
    cursor.close()

    return {
        "id": task_id,
        "thread_id": thread_id,
        "title": req.title,
        "status": "pending",
        "depth": req.depth,
        "assigned_to": req.assigned_to,
    }


@router.get("/threads/{thread_id}/tasks")
def list_thread_tasks(
    thread_id: str,
    status: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """List tasks in a thread."""
    cursor = db.cursor(dictionary=True)
    if status:
        cursor.execute(
            "SELECT * FROM thread_tasks WHERE thread_id=%s AND status=%s ORDER BY created_at DESC",
            (thread_id, status),
        )
    else:
        cursor.execute(
            "SELECT * FROM thread_tasks WHERE thread_id=%s ORDER BY created_at DESC",
            (thread_id,),
        )
    rows = cursor.fetchall()
    cursor.close()

    tasks = []
    for r in rows:
        criteria = r.get("acceptance_criteria", "[]")
        try:
            criteria = json.loads(criteria)
        except (json.JSONDecodeError, TypeError):
            criteria = []
        tasks.append({
            "id": r["id"],
            "thread_id": r["thread_id"],
            "title": r["title"],
            "description": r.get("description", ""),
            "assigned_to": r.get("assigned_to", ""),
            "assigned_by": r.get("assigned_by", ""),
            "status": r["status"],
            "depth": r.get("depth", "thorough"),
            "acceptance_criteria": criteria,
            "quality_score": r.get("quality_score"),
            "quality_feedback": r.get("quality_feedback"),
            "revision_count": r.get("revision_count", 0),
            "max_revisions": r.get("max_revisions", 2),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return {"tasks": tasks}


@router.get("/threads/{thread_id}/tasks/{task_id}")
def get_thread_task(
    thread_id: str,
    task_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get a single task detail."""
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM thread_tasks WHERE id=%s AND thread_id=%s", (task_id, thread_id))
    r = cursor.fetchone()
    cursor.close()
    if not r:
        raise HTTPException(status_code=404, detail="Task not found.")

    criteria = r.get("acceptance_criteria", "[]")
    try:
        criteria = json.loads(criteria)
    except (json.JSONDecodeError, TypeError):
        criteria = []

    return {
        "id": r["id"],
        "thread_id": r["thread_id"],
        "title": r["title"],
        "description": r.get("description", ""),
        "assigned_to": r.get("assigned_to", ""),
        "assigned_by": r.get("assigned_by", ""),
        "status": r["status"],
        "depth": r.get("depth", "thorough"),
        "acceptance_criteria": criteria,
        "quality_score": r.get("quality_score"),
        "quality_feedback": r.get("quality_feedback"),
        "revision_count": r.get("revision_count", 0),
        "max_revisions": r.get("max_revisions", 2),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


class EvaluateTaskRequest(BaseModel):
    response_content: str


@router.post("/threads/{thread_id}/tasks/{task_id}/evaluate")
def evaluate_thread_task(
    thread_id: str,
    task_id: str,
    req: EvaluateTaskRequest,
    org: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Evaluate a bot's response for a task. Auto-sends revision request if needed."""
    import datetime

    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db, target_org_id=org or None)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    # 读取任务
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM thread_tasks WHERE id=%s AND thread_id=%s", (task_id, thread_id))
    task = cursor.fetchone()
    cursor.close()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    # 获取 QC 配置
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM thread_qc_config WHERE thread_id=%s", (thread_id,))
    qc_config = cursor.fetchone()
    cursor.close()

    # 获取 API key: 优先用 QC 配置的，然后用全局设置
    api_key = ""
    if qc_config and qc_config.get("evaluator_api_key"):
        api_key = qc_config["evaluator_api_key"]
    else:
        api_key = get_setting("anthropic_api_key", "")

    if not api_key:
        raise HTTPException(status_code=400, detail="No evaluator API key configured.")

    # 执行评估
    evaluation = evaluate_response(task, req.response_content, api_key)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    score = evaluation.get("overall_score", 0.0)
    verdict = evaluation.get("verdict", "FAIL")
    feedback = evaluation.get("feedback", "")

    # 更新任务
    new_status = "completed" if verdict == "PASS" else ("revision" if verdict == "REVISE" else "failed")
    cursor = db.cursor()
    cursor.execute(
        """UPDATE thread_tasks SET quality_score=%s, quality_feedback=%s,
           status=%s, updated_at=%s WHERE id=%s""",
        (score, json.dumps(evaluation, ensure_ascii=False), new_status, now, task_id),
    )
    cursor.close()

    # 自动发送修改请求
    revision_sent = False
    min_score = qc_config["min_quality_score"] if qc_config else 0.6
    auto_rev = qc_config["auto_revision"] if qc_config else True

    if auto_rev and should_request_revision(task, evaluation, min_score):
        hub_url = _get_hub_url().rstrip("/")
        token = _get_thread_token(user_id, info, hub_url, db, thread_id=thread_id)
        if token:
            revision_msg = format_revision_request({**task, "quality_score": score}, feedback)
            try:
                _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/messages", {
                    "content": revision_msg,
                })
                # 更新修改计数
                cursor = db.cursor()
                cursor.execute(
                    "UPDATE thread_tasks SET revision_count=revision_count+1, status='revision', updated_at=%s WHERE id=%s",
                    (now, task_id),
                )
                cursor.close()
                revision_sent = True
            except Exception:
                pass  # best effort

    return {
        "task_id": task_id,
        "evaluation": evaluation,
        "new_status": new_status,
        "revision_sent": revision_sent,
    }
