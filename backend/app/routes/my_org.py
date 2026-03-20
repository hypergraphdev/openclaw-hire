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

def _get_user_org_info(user_id: str, db: sqlite3.Connection) -> dict:
    """Return user's org context: instances, org_id, etc."""
    # Get user's instances with config
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

    # Find first org_id
    org_id = None
    my_bots = []
    for r in rows:
        agent_name = r["cfg_agent_name"] or r["agent_name"] or ""
        if r["org_id"] and not org_id:
            org_id = r["org_id"]
        if agent_name:
            my_bots.append({
                "instance_id": r["id"],
                "instance_name": r["name"],
                "agent_name": agent_name,
                "product": r["product"],
            })

    if not org_id:
        return {"status": "no_org", "my_bots": my_bots}

    return {"status": "ok", "org_id": org_id, "my_bots": my_bots}


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


def _pick_chat_token(user_id: str, target_bot_name: str, my_bot_names: set[str], hub_url: str, db: sqlite3.Connection) -> tuple[str, str]:
    """Pick the right token for chatting.
    Returns (token, identity_type) where identity_type is 'admin' or instance_id.

    - Target is MY bot → use admin bot token
    - Target is OTHER's bot → use my first instance bot token
    """
    if target_bot_name in my_bot_names:
        # Chat with own bot → use admin bot
        user_row = db.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
        display_name = user_row["name"] if user_row else ""
        token = _ensure_user_bot(hub_url, user_id, display_name)
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
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get user's organization info and bot list."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)

    if info["status"] != "ok":
        return info

    org_id = info["org_id"]
    default_org_id = get_setting("hxa_org_id", "")
    org_name = _get_org_name(org_id)

    # Get all bots in org
    org_secret = _resolve_org_secret(org_id)
    all_bots_raw = _get_org_bots(org_id, org_secret) if org_secret else []

    my_agent_names = {b["agent_name"] for b in info["my_bots"]}
    all_bots = []
    for b in all_bots_raw:
        all_bots.append({
            "bot_id": b.get("id", ""),
            "name": b.get("name", ""),
            "online": b.get("online", False),
            "is_mine": b.get("name", "") in my_agent_names,
        })

    return {
        "status": "ok",
        "org_id": org_id,
        "org_name": org_name,
        "is_default_org": org_id == default_org_id,
        "my_bots": info["my_bots"],
        "all_bots": all_bots,
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
    token, _ = _pick_chat_token(user_id, req.target_bot_name, my_agent_names, hub_url, db)

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
    token, identity = _pick_chat_token(user_id, target, my_agent_names, hub_url, db)

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
    token, _ = _pick_chat_token(user_id, target, my_agent_names, hub_url, db)

    params = f"limit={limit}"
    if before:
        params += f"&before={before}"
    result = _hub_request(hub_url, token, "GET", f"/api/channels/{channel_id}/messages?{params}")
    messages = result if isinstance(result, list) else result.get("messages", [])
    return {"messages": messages, "has_more": len(messages) >= limit}


@router.post("/chat/ws-ticket")
def org_chat_ws_ticket(
    target: str = Query(""),
    current_user: dict = Depends(get_current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """Get WebSocket ticket. Uses appropriate bot identity based on target."""
    user_id = current_user["id"]
    info = _get_user_org_info(user_id, db)
    if info["status"] != "ok":
        raise HTTPException(status_code=400, detail="Not in an organization.")

    hub_url = _get_hub_url().rstrip("/")
    my_agent_names = {b["agent_name"] for b in info["my_bots"]}

    if target:
        token, _ = _pick_chat_token(user_id, target, my_agent_names, hub_url, db)
    else:
        # Default: use admin bot
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

    # Invite participants by name
    for name in req.participant_names:
        if name in my_agent_names:
            continue  # Skip self
        try:
            _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/participants", {"name": name})
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
    """Send a message to a thread."""
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

    content = req.content
    if req.image_url:
        content = f"[image]({req.image_url})\n{content}" if content else f"[image]({req.image_url})"

    result = _hub_request(hub_url, token, "POST", f"/api/threads/{thread_id}/messages", {
        "content": content,
    })
    return result
