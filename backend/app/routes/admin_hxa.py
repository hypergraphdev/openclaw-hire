from __future__ import annotations

import json
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..database import get_setting, set_setting, get_connection, site_base_url, runtime_root
from ..deps import get_current_user
from ..services.install_service import _get_hub_url
from .admin import _require_admin

router = APIRouter(prefix="/api/admin/hxa", tags=["admin-hxa"])

RUNTIME_ROOT = Path(runtime_root())


# ---------------------------------------------------------------------------
#  Hub Admin API helper
# ---------------------------------------------------------------------------

def _get_admin_secret() -> str:
    return get_setting("hxa_admin_secret", "")


def _hub_admin_request(method: str, path: str, body: dict | None = None, timeout: int = 15) -> dict | list | None:
    """Call HXA Hub API with admin secret auth."""
    hub = _get_hub_url().rstrip("/")
    secret = _get_admin_secret()
    if not secret:
        raise HTTPException(status_code=400, detail="HXA Admin Secret not configured. Set it in Admin Settings.")

    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{hub}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode() if e.fp else str(e)
        raise HTTPException(status_code=e.code, detail=f"Hub API error: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Hub request failed: {e}")


def _hub_org_admin_request(method: str, path: str, org_id: str, org_secret: str, body: dict | None = None, timeout: int = 15) -> dict | list | None:
    """Call HXA Hub API as org admin (login with org_secret, use session cookie)."""
    hub = _get_hub_url().rstrip("/")
    from urllib.parse import urlparse as _up; _ph = _up(_get_hub_url()); origin = f"{_ph.scheme}://{_ph.netloc}"

    # Login
    login_data = json.dumps({"type": "org_admin", "org_secret": org_secret, "org_id": org_id}).encode()
    login_req = urllib.request.Request(f"{hub}/api/auth/login", data=login_data,
                                       headers={"Content-Type": "application/json", "Origin": origin}, method="POST")
    try:
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Org admin login failed: {e}")

    # Execute request
    headers = {"Content-Type": "application/json", "Cookie": cookie, "Origin": origin}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{hub}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode() if e.fp else str(e)
        raise HTTPException(status_code=e.code, detail=f"Hub API error: {detail}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Hub request failed: {e}")


def _get_agents() -> list[dict]:
    agents = []
    if not RUNTIME_ROOT.exists():
        return agents

    # Get instance names + status from DB
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, product, install_state, agent_name, status FROM instances")
        rows = cursor.fetchall()
        cursor.close()
        instance_map = {r["id"]: {
            "name": r["name"], "product": r["product"],
            "install_state": r["install_state"] or "idle",
            "agent_name_db": r["agent_name"] or "",
            "status": r["status"] or "",
        } for r in rows}
    finally:
        conn.close()

    for runtime_dir in sorted(RUNTIME_ROOT.iterdir()):
        instance_id = runtime_dir.name
        instance_info = instance_map.get(instance_id, {})
        product = instance_info.get("product", "unknown")
        instance_name = instance_info.get("name", instance_id)

        agent_token = None
        agent_name = None
        agent_id = None

        # OpenClaw: openclaw-config/openclaw.json
        oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"
        if oc_cfg.exists():
            try:
                cfg = json.loads(oc_cfg.read_text())
                hxa = cfg.get("channels", {}).get("hxa-connect", {})
                agent_token = hxa.get("agentToken")
                agent_name = hxa.get("agentName")
            except Exception:
                pass

        # Zylos: zylos-data/components/hxa-connect/config.json
        if not agent_token:
            zy_cfg = runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
            if zy_cfg.exists():
                try:
                    cfg = json.loads(zy_cfg.read_text())
                    org = cfg.get("orgs", {}).get("default", {})
                    agent_token = org.get("agent_token")
                    agent_name = org.get("agent_name")
                    agent_id = org.get("agent_id")
                except Exception:
                    pass

        if agent_token or agent_name:
            agents.append({
                "instance_id": instance_id,
                "instance_name": instance_name,
                "product": product,
                "agent_name": agent_name or "",
                "agent_token_prefix": (agent_token[:12] + "...") if agent_token else "",
                "agent_token": agent_token or "",
                "agent_id": agent_id or "",
                "install_state": instance_info.get("install_state", "idle"),
                "is_configured": bool(instance_info.get("agent_name_db")),
            })

    return agents


@router.get("/config")
def get_hxa_config(current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    return {
        "org_id": get_setting("hxa_org_id"),
        "org_secret": get_setting("hxa_org_secret"),
        "hub_url": get_setting("hxa_hub_url", "https://www.ucai.net/connect"),
    }


class UpdateHubUrlRequest(BaseModel):
    hub_url: str


@router.put("/config/hub-url")
def update_hub_url(payload: UpdateHubUrlRequest, current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    url = payload.hub_url.strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=400, detail="Hub URL cannot be empty.")
    set_setting("hxa_hub_url", url)
    return {"ok": True, "hub_url": url}


class UpdateAgentNameRequest(BaseModel):
    agent_name: str


@router.put("/agents/{instance_id}/name")
def update_agent_name(instance_id: str, payload: UpdateAgentNameRequest, current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    new_name = payload.agent_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Agent name cannot be empty.")

    # Auto-append _Bot if not already ending with _Bot or _bot
    if not new_name.lower().endswith("_bot"):
        new_name = f"{new_name}_Bot"

    # Check duplicate name across all agents in org
    existing_agents = _get_agents()
    for a in existing_agents:
        if a["agent_name"] == new_name and a["instance_id"] != instance_id:
            raise HTTPException(status_code=409, detail=f"名字 '{new_name}' 已被实例 {a['instance_name']} 使用。")

    # Read bot token from runtime config to call HXA rename API
    agent_token = _get_agent_token(instance_id)
    if not agent_token:
        raise HTTPException(status_code=409, detail="Cannot find agent token for this instance. Configure HXA first.")

    # Call HXA Connect PATCH /api/me/name with bot token
    hub = _get_hub_url().rstrip("/")
    try:
        rename_data = json.dumps({"name": new_name}).encode()
        req = urllib.request.Request(
            f"{hub}/api/me/name",
            data=rename_data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {agent_token}"},
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise HTTPException(status_code=e.code, detail=f"HXA rename failed: {body}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HXA rename request failed: {e}")

    # Update local DB
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE instances SET agent_name = %s WHERE id = %s", (new_name, instance_id))
        cursor.execute("UPDATE instance_configs SET agent_name = %s WHERE instance_id = %s", (new_name, instance_id))
        cursor.close()
    finally:
        conn.close()

    # Update runtime config files
    _update_agent_name_in_config(instance_id, new_name)

    return {"ok": True, "agent_name": new_name}


def _get_agent_token(instance_id: str) -> str:
    """Read agent token from runtime config files."""
    runtime_dir = RUNTIME_ROOT / instance_id

    # OpenClaw
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"
    if oc_cfg.exists():
        try:
            cfg = json.loads(oc_cfg.read_text())
            return cfg.get("channels", {}).get("hxa-connect", {}).get("agentToken", "")
        except Exception:
            pass

    # Zylos
    zy_cfg = runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
    if zy_cfg.exists():
        try:
            cfg = json.loads(zy_cfg.read_text())
            return cfg.get("orgs", {}).get("default", {}).get("agent_token", "")
        except Exception:
            pass

    return ""


def _update_agent_name_in_config(instance_id: str, new_name: str) -> None:
    """Update agent name in runtime config files (best effort)."""
    runtime_dir = RUNTIME_ROOT / instance_id

    # OpenClaw: openclaw.json
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"
    if oc_cfg.exists():
        try:
            cfg = json.loads(oc_cfg.read_text())
            hxa = cfg.get("channels", {}).get("hxa-connect", {})
            if hxa:
                hxa["agentName"] = new_name
                oc_cfg.write_text(json.dumps(cfg, indent=2) + "\n")
        except Exception:
            pass

    # Zylos: config.json
    zy_cfg = runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
    if zy_cfg.exists():
        try:
            cfg = json.loads(zy_cfg.read_text())
            org = cfg.get("orgs", {}).get("default", {})
            if org:
                org["agent_name"] = new_name
                zy_cfg.write_text(json.dumps(cfg, indent=2) + "\n")
        except Exception:
            pass

    # .env files
    env_path = runtime_dir / ".env"
    if env_path.exists():
        try:
            content = env_path.read_text()
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("HXA_CONNECT_AGENT_NAME="):
                    new_lines.append(f"HXA_CONNECT_AGENT_NAME={new_name}")
                else:
                    new_lines.append(line)
            env_path.write_text("\n".join(new_lines) + "\n")
        except Exception:
            pass


@router.get("/agents")
def get_hxa_agents(current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    return {"agents": _get_agents()}


# ---------------------------------------------------------------------------
#  Organization CRUD
# ---------------------------------------------------------------------------

@router.get("/orgs")
def list_orgs(current_user: dict = Depends(get_current_user)):
    """List organizations. Uses Hub admin API if available, otherwise local org_secrets table."""
    _require_admin(current_user)
    default_org_id = get_setting("hxa_org_id", "")

    # Try Hub admin API first (lists all orgs)
    admin_secret = _get_admin_secret()
    if admin_secret:
        orgs = _hub_admin_request("GET", "/api/orgs")
        result = []
        for o in (orgs or []):
            result.append({
                "id": o.get("id", ""),
                "name": o.get("name", ""),
                "status": o.get("status", "active"),
                "bot_count": o.get("bot_count", 0),
                "created_at": o.get("created_at", 0),
                "is_default": o.get("id") == default_org_id,
            })
        return {"orgs": result}

    # Fallback: list from local org_secrets table (orgs created via invite code)
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT org_id, org_name, created_at FROM org_secrets ORDER BY created_at DESC")
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    result = []
    for r in rows:
        result.append({
            "id": r["org_id"],
            "name": r.get("org_name", ""),
            "status": "active",
            "bot_count": 0,
            "created_at": r.get("created_at", ""),
            "is_default": r["org_id"] == default_org_id,
        })
    return {"orgs": result}


class CreateOrgRequest(BaseModel):
    name: str


@router.post("/orgs")
def create_org(payload: CreateOrgRequest, current_user: dict = Depends(get_current_user)):
    """Create a new organization."""
    _require_admin(current_user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Organization name is required.")
    result = _hub_admin_request("POST", "/api/orgs", {"name": name})
    # Store org_secret locally for future operations (only returned once by Hub)
    if result and result.get("org_secret") and result.get("id"):
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "REPLACE INTO org_secrets (org_id, org_secret, org_name, created_at) VALUES (%s, %s, %s, %s)",
                (result["id"], result["org_secret"], name, now),
            )
            cursor.close()
        finally:
            conn.close()
    return result


class UpdateOrgRequest(BaseModel):
    name: str


@router.patch("/orgs/{org_id}")
def update_org(org_id: str, payload: UpdateOrgRequest, current_user: dict = Depends(get_current_user)):
    """Update organization name."""
    _require_admin(current_user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty.")
    result = _hub_admin_request("PATCH", f"/api/orgs/{org_id}", {"name": name})
    return result


@router.delete("/orgs/{org_id}")
def delete_org(org_id: str, current_user: dict = Depends(get_current_user)):
    """Delete an organization (irreversible)."""
    _require_admin(current_user)
    default_org_id = get_setting("hxa_org_id", "")
    if org_id == default_org_id:
        raise HTTPException(status_code=400, detail="Cannot delete the default organization.")
    _hub_admin_request("DELETE", f"/api/orgs/{org_id}")
    return {"ok": True}


@router.post("/orgs/{org_id}/rotate-secret")
def rotate_org_secret(org_id: str, current_user: dict = Depends(get_current_user)):
    """Rotate organization secret."""
    _require_admin(current_user)
    result = _hub_admin_request("POST", f"/api/orgs/{org_id}/rotate-secret")
    # Update local settings if this is the default org
    default_org_id = get_setting("hxa_org_id", "")
    if org_id == default_org_id and result and result.get("org_secret"):
        set_setting("hxa_org_secret", result["org_secret"])
    return result


@router.post("/orgs/{org_id}/set-default")
def set_default_org(org_id: str, current_user: dict = Depends(get_current_user)):
    """Set an organization as the default for new instances."""
    _require_admin(current_user)
    # Verify org exists
    orgs = _hub_admin_request("GET", "/api/orgs")
    org = next((o for o in (orgs or []) if o.get("id") == org_id), None)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    set_setting("hxa_org_id", org_id)
    return {"ok": True, "org_id": org_id}


@router.get("/orgs/{org_id}/agents")
def list_org_agents(org_id: str, current_user: dict = Depends(get_current_user)):
    """List agents (bots) in a specific organization."""
    _require_admin(current_user)

    # Get all local agents and match with this org
    local_agents = _get_agents()

    # Try org admin login to get bot list
    default_org_id = get_setting("hxa_org_id", "")
    org_secret = None
    if org_id == default_org_id:
        org_secret = get_setting("hxa_org_secret", "")
    else:
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT org_secret FROM org_secrets WHERE org_id = %s", (org_id,))
            row = cursor.fetchone()
            cursor.close()
        finally:
            conn.close()
        if row:
            org_secret = row["org_secret"]

    bots = []
    if org_secret:
        try:
            result = _hub_org_admin_request("GET", "/api/bots", org_id, org_secret)
            if isinstance(result, dict):
                bots = result.get("bots", [])
            elif isinstance(result, list):
                bots = result
        except Exception:
            pass

    # Build instance owner map for enrichment
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT i.id, i.name AS inst_name, i.product, u.name AS owner_name, u.email AS owner_email
            FROM instances i JOIN users u ON i.owner_id = u.id
        """)
        owner_rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    owner_map = {}
    for r in owner_rows:
        owner_map[r["id"]] = {
            "inst_name": r["inst_name"], "product": r["product"],
            "owner_name": r["owner_name"], "owner_email": r["owner_email"],
        }

    # Enrich with local instance info (match by agent_name since Hub doesn't return token)
    enriched = []
    for bot in bots:
        bot_name = bot.get("name", "")
        local = next((a for a in local_agents if a.get("agent_name") == bot_name), None)
        inst_id = local["instance_id"] if local else None
        owner_info = owner_map.get(inst_id, {}) if inst_id else {}
        enriched.append({
            "bot_id": bot.get("id", ""),
            "name": bot_name,
            "online": bot.get("online", False),
            "auth_role": bot.get("auth_role", "member"),
            "token_prefix": (local["agent_token"][:12] + "...") if local and local.get("agent_token") else "",
            "instance_id": inst_id,
            "instance_name": local["instance_name"] if local else None,
            "product": local["product"] if local else None,
            "owner_name": owner_info.get("owner_name"),
            "owner_email": owner_info.get("owner_email"),
        })
    # Auto-sync DB org_id with Hub reality (Hub is source of truth)
    try:
        hub_bot_names = {bot.get("name", "") for bot in bots}
        conn = get_connection()
        try:
            cursor = conn.cursor()
            for name in hub_bot_names:
                cursor.execute(
                    "UPDATE instance_configs SET org_id = %s WHERE agent_name = %s AND (org_id IS NULL OR org_id != %s)",
                    (org_id, name, org_id),
                )
            cursor.close()
        finally:
            conn.close()
    except Exception:
        pass  # Best effort

    # Get org name from local DB
    org_name = ""
    conn3 = get_connection()
    try:
        cur3 = conn3.cursor(dictionary=True)
        cur3.execute("SELECT org_name FROM org_secrets WHERE org_id = %s", (org_id,))
        r3 = cur3.fetchone()
        if r3:
            org_name = r3["org_name"] or ""
        cur3.close()
    finally:
        conn3.close()
    return {"agents": enriched, "org_name": org_name}


# ---------------------------------------------------------------------------
#  Delete bot from org
# ---------------------------------------------------------------------------

@router.delete("/orgs/{org_id}/bots/{bot_id}")
def delete_org_bot(org_id: str, bot_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a bot from an org (admin only, for orphan cleanup)."""
    _require_admin(current_user)
    hub = get_setting("hxa_hub_url", "https://www.ucai.net/connect").rstrip("/")
    org_secret = _get_org_secret_for(org_id)
    if not org_secret:
        raise HTTPException(status_code=400, detail="Org secret not found.")

    # Login as org admin
    from urllib.parse import urlparse as _up; _ph = _up(_get_hub_url()); origin = f"{_ph.scheme}://{_ph.netloc}"
    login_data = json.dumps({"type": "org_admin", "org_secret": org_secret, "org_id": org_id}).encode()
    try:
        login_req = urllib.request.Request(f"{hub}/api/auth/login", data=login_data,
            headers={"Content-Type": "application/json", "Origin": origin}, method="POST")
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Admin login failed: {e}")

    # Delete bot
    try:
        del_req = urllib.request.Request(f"{hub}/api/bots/{bot_id}",
            headers={"Cookie": cookie, "Origin": origin}, method="DELETE")
        urllib.request.urlopen(del_req, timeout=10)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise HTTPException(status_code=e.code, detail=f"Hub error: {body}")

    return {"ok": True}


def _get_org_secret_for(org_id: str) -> str:
    """Get org secret for a specific org."""
    # Check if it's the default org
    default_id = get_setting("hxa_org_id", "")
    if org_id == default_id:
        return get_setting("hxa_org_secret", "")
    # Check local org_secrets table
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT org_secret FROM org_secrets WHERE org_id = %s", (org_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    return row["org_secret"] if row else ""


# ---------------------------------------------------------------------------
#  Bot Transfer
# ---------------------------------------------------------------------------

def _cleanup_bot_and_tombstone(hub_url: str, org_id: str, org_secret: str, bot_name: str) -> None:
    """Delete existing bot with same name + tombstone in an org. Best-effort."""
    from urllib.parse import urlparse as _up; _ph = _up(_get_hub_url()); origin = f"{_ph.scheme}://{_ph.netloc}"
    try:
        login_data = json.dumps({"type": "org_admin", "org_secret": org_secret, "org_id": org_id}).encode()
        login_req = urllib.request.Request(
            f"{hub_url}/api/auth/login", data=login_data,
            headers={"Content-Type": "application/json", "Origin": origin}, method="POST",
        )
        with urllib.request.urlopen(login_req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]

        # Delete existing bot with same name
        try:
            bots_req = urllib.request.Request(
                f"{hub_url}/api/bots?limit=200",
                headers={"Cookie": cookie, "Origin": origin},
            )
            with urllib.request.urlopen(bots_req, timeout=10) as resp:
                bots_raw = json.loads(resp.read().decode())
            items = bots_raw if isinstance(bots_raw, list) else bots_raw.get("bots", bots_raw.get("items", []))
            for b in items:
                if b.get("name") == bot_name:
                    urllib.request.urlopen(urllib.request.Request(
                        f"{hub_url}/api/bots/{b['id']}",
                        headers={"Cookie": cookie, "Origin": origin}, method="DELETE",
                    ), timeout=10)
                    break
        except Exception:
            pass

        # Delete tombstone
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{hub_url}/api/orgs/{org_id}/tombstones/{bot_name}",
                headers={"Cookie": cookie, "Origin": origin}, method="DELETE",
            ), timeout=10)
        except Exception:
            pass
    except Exception:
        pass

class TransferBotRequest(BaseModel):
    target_org_id: str


@router.post("/bots/{instance_id}/transfer")
def transfer_bot(instance_id: str, payload: TransferBotRequest, current_user: dict = Depends(get_current_user)):
    """Transfer a bot from its current org to a different org."""
    _require_admin(current_user)
    target_org_id = payload.target_org_id.strip()
    if not target_org_id:
        raise HTTPException(status_code=400, detail="Target org ID is required.")

    # 1. Read current bot info — try token first, fall back to DB
    hub = _get_hub_url().rstrip("/")
    agent_token = _get_agent_token(instance_id)
    bot_id = ""
    agent_name = ""
    current_org_id = ""

    if agent_token:
        try:
            me_req = urllib.request.Request(
                f"{hub}/api/me",
                headers={"Authorization": f"Bearer {agent_token}"},
                method="GET",
            )
            with urllib.request.urlopen(me_req, timeout=10) as resp:
                bot_info = json.loads(resp.read().decode())
            bot_id = bot_info.get("id", "")
            agent_name = bot_info.get("name", "")
            current_org_id = bot_info.get("org_id", "")
        except Exception:
            pass  # Token invalid/expired, fall back to DB

    # Fall back to DB if token didn't work
    if not agent_name:
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT agent_name, org_id FROM instance_configs WHERE instance_id = %s",
                (instance_id,),
            )
            row = cursor.fetchone()
            cursor.execute("SELECT agent_name FROM instances WHERE id = %s", (instance_id,))
            inst_row = cursor.fetchone()
            cursor.close()
        finally:
            conn.close()
        agent_name = (row["agent_name"] if row and row["agent_name"] else None) or \
                     (inst_row["agent_name"] if inst_row and inst_row["agent_name"] else "")
        current_org_id = row["org_id"] if row and row["org_id"] else ""

    if not agent_name:
        raise HTTPException(status_code=400, detail="Cannot determine agent name for this instance.")

    if current_org_id == target_org_id:
        raise HTTPException(status_code=400, detail="Bot is already in the target organization.")

    # Helper: get org_secret for an org_id
    def _resolve_org_secret(oid: str) -> str:
        default_oid = get_setting("hxa_org_id", "")
        if oid == default_oid:
            return get_setting("hxa_org_secret", "")
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT org_secret FROM org_secrets WHERE org_id = %s", (oid,))
            row = cursor.fetchone()
            cursor.close()
        finally:
            conn.close()
        return row["org_secret"] if row else ""

    # 2. Try to delete bot from old org (best effort - skip on failure)
    current_org_secret = _resolve_org_secret(current_org_id)
    if current_org_secret:
        try:
            _hub_org_admin_request("DELETE", f"/api/bots/{bot_id}", current_org_id, current_org_secret)
        except Exception:
            pass  # Bot may not exist in old org anymore, continue with registration

    # 3. Get target org secret
    target_org_secret = _resolve_org_secret(target_org_id)
    if not target_org_secret:
        raise HTTPException(status_code=400, detail="Target org secret not available.")

    if not target_org_secret:
        raise HTTPException(status_code=400, detail="Target org secret is empty.")

    # 3.5 Cleanup: delete existing bot with same name + tombstone in target org
    _cleanup_bot_and_tombstone(hub, target_org_id, target_org_secret, agent_name)

    # 4. Login to target org, create ticket, register bot
    try:
        ticket_result = _hub_org_admin_request("POST", "/api/org/tickets", target_org_id, target_org_secret,
                                                {"reusable": False, "skip_approval": True})
        ticket_secret = ticket_result.get("ticket", "") if ticket_result else ""
        if not ticket_secret:
            raise Exception("No ticket returned")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to create ticket in target org: {e}")

    # Register bot
    try:
        reg_data = json.dumps({"org_id": target_org_id, "ticket": ticket_secret, "name": agent_name}).encode()
        reg_req = urllib.request.Request(
            f"{hub}/api/auth/register",
            data=reg_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(reg_req, timeout=15) as resp:
            reg_result = json.loads(resp.read().decode())
    except Exception as e:
        # Registration failed — try to rollback: re-register in old org to avoid orphaning
        if current_org_secret and current_org_id:
            try:
                _cleanup_bot_and_tombstone(hub, current_org_id, current_org_secret, agent_name)
                old_ticket = _hub_org_admin_request("POST", "/api/org/tickets", current_org_id, current_org_secret,
                                                     {"reusable": False, "skip_approval": True})
                old_ticket_secret = old_ticket.get("ticket", "") if old_ticket else ""
                if old_ticket_secret:
                    rb_data = json.dumps({"org_id": current_org_id, "ticket": old_ticket_secret, "name": agent_name}).encode()
                    rb_req = urllib.request.Request(
                        f"{hub}/api/auth/register", data=rb_data,
                        headers={"Content-Type": "application/json"}, method="POST",
                    )
                    with urllib.request.urlopen(rb_req, timeout=15) as resp:
                        rb_result = json.loads(resp.read().decode())
                    rb_token = rb_result.get("token", "")
                    if rb_token:
                        _write_new_token(instance_id, rb_token, agent_name, current_org_id)
                        conn = get_connection()
                        try:
                            cursor = conn.cursor()
                            cursor.execute(
                                "UPDATE instance_configs SET org_token = %s WHERE instance_id = %s",
                                (rb_token, instance_id),
                            )
                            cursor.close()
                        finally:
                            conn.close()
                        _restart_hxa_connect(instance_id)
            except Exception:
                pass  # Rollback also failed — bot is orphaned, MyOrg auto-repair will handle
        raise HTTPException(status_code=502, detail=f"Failed to register bot in target org: {e}")

    new_token = reg_result.get("token", "")
    new_bot_id = reg_result.get("bot_id", "")
    if not new_token:
        raise HTTPException(status_code=502, detail="Registration returned no token.")

    # 5. Write new token to container config
    _write_new_token(instance_id, new_token, agent_name, target_org_id)

    # 6. Restart hxa-connect in container
    _restart_hxa_connect(instance_id)

    # 7. Update local DB
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE instance_configs SET org_id = %s, org_token = %s WHERE instance_id = %s",
            (target_org_id, new_token, instance_id),
        )
        # Clear cached admin bot tokens for the OLD org (they're now invalid)
        if current_org_id and current_org_id != target_org_id:
            cursor.execute(
                "DELETE FROM server_settings WHERE `key` LIKE %s",
                (f"hxa_user_bot_token%_{current_org_id[:8]}%",),
            )
        cursor.close()
    finally:
        conn.close()

    # Clear in-memory admin bot cache so stale tokens aren't reused
    from .instances import _user_bot_cache
    _user_bot_cache.clear()

    # 8. Verify: call Hub /api/me with new token to confirm org_id matches
    warnings: list[str] = []
    try:
        me_req = urllib.request.Request(
            f"{hub}/api/me",
            headers={"Authorization": f"Bearer {new_token}"},
            method="GET",
        )
        with urllib.request.urlopen(me_req, timeout=10) as resp:
            me_info = json.loads(resp.read().decode())
        hub_org_id = me_info.get("org_id", "")
        hub_name = me_info.get("name", "")
        if hub_org_id != target_org_id:
            warnings.append(f"Hub org_id({hub_org_id[:8]}…) 与目标({target_org_id[:8]}…)不一致，请检查")
        if hub_name != agent_name:
            warnings.append(f"Hub agent_name({hub_name}) 与本地({agent_name})不一致")
    except Exception as e:
        warnings.append(f"Hub 验证失败: {e}")

    # Also verify runtime config was written correctly
    try:
        from ..database import runtime_root as _runtime_root
        _conn2 = get_connection()
        _cur2 = _conn2.cursor(dictionary=True)
        _cur2.execute("SELECT runtime_dir FROM instances WHERE id = %s", (instance_id,))
        _irow = _cur2.fetchone()
        _cur2.close()
        _conn2.close()
        _db_rt = (_irow or {}).get("runtime_dir", "")
        _rt = _runtime_root()
        rt_dir = Path(_db_rt) if _db_rt and Path(_db_rt).is_dir() else _rt / instance_id if _rt else None
        if rt_dir:
            oc_cfg = rt_dir / "openclaw-config" / "openclaw.json"
            zy_cfg = rt_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
            cfg_org_id = ""
            if oc_cfg.exists():
                cfg = json.loads(oc_cfg.read_text())
                cfg_org_id = cfg.get("channels", {}).get("hxa-connect", {}).get("orgId", "")
            elif zy_cfg.exists():
                cfg = json.loads(zy_cfg.read_text())
                cfg_org_id = cfg.get("orgs", {}).get("default", {}).get("org_id", "")
            if cfg_org_id and cfg_org_id != target_org_id:
                warnings.append(f"容器配置 org_id({cfg_org_id[:8]}…) 未更新到目标组织")
    except Exception:
        pass

    result = {"ok": True, "new_org_id": target_org_id, "agent_name": agent_name}
    if warnings:
        result["warnings"] = warnings
    return result


def _write_new_token(instance_id: str, new_token: str, agent_name: str, org_id: str) -> None:
    """Write new bot token to container runtime config."""
    runtime_dir = RUNTIME_ROOT / instance_id

    # OpenClaw
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"
    if oc_cfg.exists():
        try:
            cfg = json.loads(oc_cfg.read_text())
            hxa = cfg.get("channels", {}).get("hxa-connect", {})
            if hxa:
                hxa["agentToken"] = new_token
                hxa["agentName"] = agent_name
                hxa["orgId"] = org_id
                oc_cfg.write_text(json.dumps(cfg, indent=2) + "\n")
        except Exception:
            pass

    # Zylos
    zy_cfg = runtime_dir / "zylos-data" / "components" / "hxa-connect" / "config.json"
    if zy_cfg.exists():
        try:
            cfg = json.loads(zy_cfg.read_text())
            org = cfg.get("orgs", {}).get("default", {})
            if org:
                org["agent_token"] = new_token
                org["agent_name"] = agent_name
                org["org_id"] = org_id
                zy_cfg.write_text(json.dumps(cfg, indent=2) + "\n")
        except Exception:
            pass


def _restart_hxa_connect(instance_id: str) -> None:
    """Restart hxa-connect process in container."""
    runtime_dir = RUNTIME_ROOT / instance_id
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"

    if oc_cfg.exists():
        # OpenClaw: no pm2 — hxa-connect is embedded in gateway, restart the container
        container_name = f"hire_{instance_id}-openclaw-gateway-1"
        subprocess.run(
            ["docker", "restart", container_name],
            capture_output=True, timeout=60,
        )
    else:
        # Zylos: has pm2 managing hxa-connect as a separate process
        container_name = f"zylos_{instance_id}"
        subprocess.run(
            ["docker", "exec", container_name, "pm2", "restart", "zylos-hxa-connect"],
            capture_output=True, timeout=30,
        )
