"""My Organization — user-facing org view + chat proxy with identity switching."""
from __future__ import annotations

import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from ..database import get_setting, get_connection
from ..deps import get_current_user, get_db
from ..services.install_service import _get_hub_url
from .admin_hxa import _get_agent_token, _hub_admin_request, _hub_org_admin_request
from .instances import _hub_request, _ensure_user_bot, _make_admin_bot_name

router = APIRouter(prefix="/api/my-org", tags=["my-org"])


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _get_user_org_info(user_id: str, db: sqlite3.Connection, target_org_id: str = "") -> dict:
    """Return user's org context: instances, org_id, etc.
    If target_org_id given, scope to that org. Otherwise pick first."""
    rows = db.execute(
        """SELECT i.id, i.name, i.product, i.agent_name, i.install_state,
                  c.org_id, c.agent_name AS cfg_agent_name
           FROM instances i
           LEFT JOIN instance_configs c ON i.id = c.instance_id
           WHERE i.owner_id = ?
           ORDER BY i.created_at DESC""",
        (user_id,),
    ).fetchall()

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

    return {"status": "ok", "org_id": org_id, "my_bots": my_bots, "all_org_ids": org_ids}


def _resolve_org_secret(org_id: str) -> str:
    default_org_id = get_setting("hxa_org_id", "")
    if org_id == default_org_id:
        return get_setting("hxa_org_secret", "")
    with get_connection() as conn:
        row = conn.execute("SELECT org_secret FROM org_secrets WHERE org_id = ?", (org_id,)).fetchone()
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
    with get_connection() as conn:
        row = conn.execute("SELECT org_name FROM org_secrets WHERE org_id = ?", (org_id,)).fetchone()
    return row["org_name"] if row else org_id[:12]


def _pick_chat_token(user_id: str, target_bot_name: str, my_bot_names: set[str], hub_url: str, db: sqlite3.Connection, org_id: str = "") -> tuple[str, str]:
    """Pick the right token for chatting.
    Returns (token, identity_type) where identity_type is 'admin' or instance_id.

    - Target is MY bot → use admin bot token (in same org)
    - Target is OTHER's bot → use my first instance bot token
    """
    if target_bot_name in my_bot_names:
        # Chat with own bot → use admin bot in the SAME org
        user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        display_name = user_row["name"] if user_row else ""
        token = _ensure_user_bot(hub_url, user_id, display_name, target_org_id=org_id or None)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to initialize admin bot.")
        return token, "admin"
    else:
        # Chat with other's bot → use my instance bot token
        # Find first instance with valid token
        rows = db.execute(
            """SELECT i.id FROM instances i
               JOIN instance_configs c ON i.id = c.instance_id
               WHERE i.owner_id = ? AND c.agent_name IS NOT NULL AND c.agent_name != ''
               ORDER BY i.created_at ASC LIMIT 1""",
            (user_id,),
        ).fetchall()
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
    db: sqlite3.Connection = Depends(get_db),
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

    my_agent_names = {b["agent_name"] for b in info["my_bots"]}

    # Filter to instance bots only
    with get_connection() as conn:
        inst_rows = conn.execute(
            "SELECT DISTINCT agent_name FROM instance_configs WHERE org_id = ? AND agent_name IS NOT NULL AND agent_name != ''",
            (active_org_id,),
        ).fetchall()
    instance_agent_names = {r["agent_name"] for r in inst_rows}

    all_bots = []
    for b in all_bots_raw:
        bot_name = b.get("name", "")
        if bot_name not in instance_agent_names:
            continue
        all_bots.append({
            "bot_id": b.get("id", ""),
            "name": bot_name,
            "online": b.get("online", False),
            "is_mine": bot_name in my_agent_names,
        })

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


@router.post("/chat/send")
def org_chat_send(
    req: OrgChatSendRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Send a message to a bot in the org. Identity depends on target."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_agent_names = {b["agent_name"] for b in info["my_bots"]}
    token, _ = _pick_chat_token(user_id, req.target_bot_name, my_agent_names, hub_url, db, org_id=info.get("org_id", ""))

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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get chat info for a target bot."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_agent_names = {b["agent_name"] for b in info["my_bots"]}
    token, identity = _pick_chat_token(user_id, target, my_agent_names, hub_url, db, org_id=info.get("org_id", ""))

    # Get my identity
    try:
        me = _hub_request(hub_url, token, "GET", "/api/me")
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to get bot identity.")

    my_bot_id = me.get("id", "")
    my_bot_name = me.get("name", "")

    # Get target bot info
    try:
        bots = _hub_request(hub_url, token, "GET", "/api/bots")
        if isinstance(bots, dict):
            bots = bots.get("bots", [])
    except Exception:
        bots = []

    target_bot = next((b for b in bots if b.get("name") == target), None)
    target_id = target_bot.get("id", "") if target_bot else ""
    target_online = target_bot.get("online", False) if target_bot else False

    # Find existing DM channel
    dm_channel_id = ""
    if target_id:
        try:
            inbox = _hub_request(hub_url, token, "GET", "/api/inbox?since=0&limit=50")
            if isinstance(inbox, list):
                for item in inbox:
                    msg = item if isinstance(item, dict) else {}
                    other = msg.get("sender_id") if msg.get("sender_id") != my_bot_id else msg.get("recipient_id", "")
                    if other == target_id:
                        dm_channel_id = msg.get("channel_id", "")
                        break
        except Exception:
            pass

    return {
        "target_name": target,
        "target_online": target_online,
        "target_id": target_id,
        "admin_bot_name": my_bot_name,
        "admin_bot_id": my_bot_id,
        "dm_channel_id": dm_channel_id,
    }


@router.get("/chat/messages")
def org_chat_messages(
    channel_id: str = Query(...),
    target: str = Query(...),
    before: str = Query(""),
    limit: int = Query(50),
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get messages for a DM channel."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_agent_names = {b["agent_name"] for b in info["my_bots"]}
    token, _ = _pick_chat_token(user_id, target, my_agent_names, hub_url, db, org_id=info.get("org_id", ""))

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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get WebSocket ticket. mode=dm uses chat identity, mode=thread uses instance bot."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_agent_names = {b["agent_name"] for b in info["my_bots"]}

    if mode == "thread":
        # Thread WS must use instance bot (thread participant)
        if info["my_bots"]:
            token = _get_agent_token(info["my_bots"][0]["instance_id"])
        else:
            token = None
        if not token:
            raise HTTPException(status_code=400, detail="No instance bot available for thread WS.")
    elif target:
        token, _ = _pick_chat_token(user_id, target, my_agent_names, hub_url, db, org_id=info.get("org_id", ""))
    else:
        user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        display_name = user_row["name"] if user_row else ""
        token = _ensure_user_bot(hub_url, user_id, display_name)
        if not token:
            raise HTTPException(status_code=500, detail="Failed to initialize admin bot.")

    result = _hub_request(hub_url, token, "POST", "/api/ws-ticket", {})
    ws_url = hub_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    return {"ticket": result.get("ticket", ""), "ws_url": ws_url}


_UPLOAD_DIR = Path("/home/wwwroot/openclaw-hire/frontend/dist/uploads")
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_SIZE = 10 * 1024 * 1024


@router.post("/chat/upload")
async def org_chat_upload(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload an image and return a public URL."""
    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported image format: {ext}")
    data = await file.read()
    if len(data) > _MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10MB)")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex[:16]}{ext}"
    (_UPLOAD_DIR / filename).write_bytes(data)
    return {"url": f"https://www.ucai.net/openclaw/uploads/{filename}", "filename": filename}


# ---------------------------------------------------------------------------
#  Thread (Group Chat) endpoints
# ---------------------------------------------------------------------------

class CreateThreadRequest(BaseModel):
    topic: str
    participant_names: list[str] = []


@router.post("/threads")
def create_thread(
    req: CreateThreadRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Create a new thread and invite participants."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    # Use admin bot to create thread (as the user's identity)
    user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    display_name = user_row["name"] if user_row else ""

    # Determine which token to use - prefer first instance bot
    my_agent_names = {b["agent_name"] for b in info["my_bots"]}
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

        for name in req.participant_names:
            if name in my_agent_names:
                continue  # Skip self
            bot_id = name_to_id.get(name, name)  # Fall back to name (resolveBot supports both)
            try:
                _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/participants", {"bot_id": bot_id})
            except Exception:
                pass  # Best effort invite

    return result


@router.get("/threads")
def list_threads(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """List threads the user's bot participates in."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")

    # Use first instance bot to list threads
    if info["my_bots"]:
        token = _get_agent_token(info["my_bots"][0]["instance_id"])
    else:
        user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        token = _ensure_user_bot(hub_url, user_id, user_row["name"] if user_row else "")
    if not token:
        return {"threads": []}

    try:
        result = _hub_request(hub_url, token, "GET", "/api/threads?status=active&limit=50")
        threads = result if isinstance(result, list) else result.get("threads", result.get("items", []))
    except Exception:
        threads = []

    return {"threads": threads}


@router.get("/threads/{thread_id}/messages")
def thread_messages(
    thread_id: str,
    before: str = Query(""),
    limit: int = Query(50),
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get messages in a thread."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    if info["my_bots"]:
        token = _get_agent_token(info["my_bots"][0]["instance_id"])
    else:
        user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        token = _ensure_user_bot(hub_url, user_id, user_row["name"] if user_row else "")
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


@router.post("/threads/{thread_id}/messages")
def thread_send(
    thread_id: str,
    req: ThreadSendRequest,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Send a message to a thread using admin bot identity.

    Uses admin bot (not instance bot) so that instance bots can detect
    the message as "from someone else" and respond to @mentions.
    Admin bot is auto-joined to the thread if not already a participant.
    """
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    org_id = info.get("org_id", "")

    # Use admin bot to send (so instance bots see it as "from others" and can reply)
    user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    display_name = user_row["name"] if user_row else ""
    token = _ensure_user_bot(hub_url, user_id, display_name, target_org_id=org_id or None)
    if not token:
        raise HTTPException(status_code=400, detail="No admin bot available.")

    # Auto-join admin bot to thread (best effort, ignore if already joined)
    try:
        me = _hub_request(hub_url, token, "GET", "/api/me")
        my_bot_id = me.get("id", "")
        _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/join")
    except Exception:
        pass  # May already be joined or join not required

    content = req.content
    if req.image_url:
        content = f"[image]({req.image_url})\n{content}" if content else f"[image]({req.image_url})"

    result = _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/messages", {
        "content": content,
    })
    return result


def _get_thread_token(user_id: str, info: dict, hub_url: str, db: sqlite3.Connection) -> str:
    """Get bot token for thread operations."""
    if info["my_bots"]:
        token = _get_agent_token(info["my_bots"][0]["instance_id"])
        if token:
            return token
    user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    return _ensure_user_bot(hub_url, user_id, user_row["name"] if user_row else "", target_org_id=info.get("org_id") or None)


@router.get("/threads/{thread_id}")
def get_thread_detail(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get thread detail with participants."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db)
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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Update thread topic or context (announcement)."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db)
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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Leave a thread. Sends DM to initiator notifying departure."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db)
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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Invite a bot to thread by name."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")
    hub_url = _get_hub_url().rstrip("/")
    token = _get_thread_token(user_id, info, hub_url, db)
    if not token:
        raise HTTPException(status_code=400, detail="No bot available.")
    # Hub requires bot_id, resolve name first
    return _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/participants", {"bot_id": req.name})


# ---------------------------------------------------------------------------
#  Message Search
# ---------------------------------------------------------------------------

@router.post("/search/sync")
def search_sync(
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Trigger message sync for search index."""
    from ..message_index import sync_messages

    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
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
    user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Search indexed messages."""
    from ..message_index import search_messages

    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    org_id = info["org_id"]
    results = search_messages(org_id, query=q, in_channel=in_channel, from_sender=from_sender, to_name=to_name, limit=limit)
    return {"results": results, "total": len(results)}
