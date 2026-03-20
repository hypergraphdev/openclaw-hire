from __future__ import annotations

import json
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..database import get_setting, set_setting
from ..deps import get_current_user
from ..database import get_connection
from ..services.install_service import _get_hub_url
from .admin import _require_admin

router = APIRouter(prefix="/api/admin/hxa", tags=["admin-hxa"])

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")


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
    origin = "https://www.ucai.net"

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
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, product, install_state, agent_name, status FROM instances").fetchall()
        instance_map = {r["id"]: {
            "name": r["name"], "product": r["product"],
            "install_state": r["install_state"] or "idle",
            "agent_name_db": r["agent_name"] or "",
            "status": r["status"] or "",
        } for r in rows}

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
        "org_id": get_setting("hxa_org_id", "123cd566-c2ea-409f-8f7e-4fa9f5296dd1"),
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
    with get_connection() as conn:
        conn.execute("UPDATE instances SET agent_name = ? WHERE id = ?", (new_name, instance_id))
        conn.execute("UPDATE instance_configs SET agent_name = ? WHERE instance_id = ?", (new_name, instance_id))
        conn.commit()

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
    """List all organizations from HXA Hub."""
    _require_admin(current_user)
    orgs = _hub_admin_request("GET", "/api/orgs")
    default_org_id = get_setting("hxa_org_id", "")
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
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO org_secrets (org_id, org_secret, org_name, created_at) VALUES (?, ?, ?, ?)",
                (result["id"], result["org_secret"], name, now),
            )
            conn.commit()
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
    # Need org_secret to login as org admin and list bots
    # For default org, use stored secret; for others, we need admin API
    # Use admin secret to get bots via admin API
    orgs = _hub_admin_request("GET", "/api/orgs")
    org = next((o for o in (orgs or []) if o.get("id") == org_id), None)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    # Get all local agents and match with this org
    local_agents = _get_agents()

    # Try org admin login to get bot list
    default_org_id = get_setting("hxa_org_id", "")
    org_secret = None
    if org_id == default_org_id:
        org_secret = get_setting("hxa_org_secret", "")
    else:
        with get_connection() as conn:
            row = conn.execute("SELECT org_secret FROM org_secrets WHERE org_id = ?", (org_id,)).fetchone()
        if row:
            org_secret = row["org_secret"]

    bots = []
    if org_secret:
        try:
            result = _hub_org_admin_request("GET", "/api/bots?limit=200", org_id, org_secret)
            if isinstance(result, dict):
                bots = result.get("bots", [])
            elif isinstance(result, list):
                bots = result
        except Exception:
            pass

    # Enrich with local instance info
    enriched = []
    for bot in bots:
        bot_token = bot.get("token", "")
        local = next((a for a in local_agents if a.get("agent_token") == bot_token), None)
        enriched.append({
            "bot_id": bot.get("id", ""),
            "name": bot.get("name", ""),
            "online": bot.get("online", False),
            "auth_role": bot.get("auth_role", "member"),
            "token_prefix": (bot_token[:12] + "...") if bot_token else "",
            "instance_id": local["instance_id"] if local else None,
            "instance_name": local["instance_name"] if local else None,
            "product": local["product"] if local else None,
        })
    return {"agents": enriched, "org_name": org.get("name", "")}


# ---------------------------------------------------------------------------
#  Bot Transfer
# ---------------------------------------------------------------------------

class TransferBotRequest(BaseModel):
    target_org_id: str


@router.post("/bots/{instance_id}/transfer")
def transfer_bot(instance_id: str, payload: TransferBotRequest, current_user: dict = Depends(get_current_user)):
    """Transfer a bot from its current org to a different org."""
    _require_admin(current_user)
    target_org_id = payload.target_org_id.strip()
    if not target_org_id:
        raise HTTPException(status_code=400, detail="Target org ID is required.")

    # 1. Read current bot info
    agent_token = _get_agent_token(instance_id)
    if not agent_token:
        raise HTTPException(status_code=400, detail="No agent token found for this instance.")

    # Get current bot info via token
    hub = _get_hub_url().rstrip("/")
    try:
        me_req = urllib.request.Request(
            f"{hub}/api/me",
            headers={"Authorization": f"Bearer {agent_token}"},
            method="GET",
        )
        with urllib.request.urlopen(me_req, timeout=10) as resp:
            bot_info = json.loads(resp.read().decode())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to get bot info: {e}")

    bot_id = bot_info.get("id", "")
    agent_name = bot_info.get("name", "")
    current_org_id = bot_info.get("org_id", "")

    if current_org_id == target_org_id:
        raise HTTPException(status_code=400, detail="Bot is already in the target organization.")

    # 2. Delete bot from old org using admin secret
    try:
        _hub_admin_request("DELETE", f"/api/bots/{bot_id}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete bot from old org: {e}")

    # 3. Get target org secret - for default org use stored, otherwise need admin rotate
    # For now, we need the org_secret to register a new bot via ticket
    # We'll use admin API to create a ticket directly
    # Actually, we need to login as org admin to create ticket. We need org_secret.
    # Strategy: if target is default org, use stored secret. Otherwise, error for now.
    default_org_id = get_setting("hxa_org_id", "")
    if target_org_id == default_org_id:
        target_org_secret = get_setting("hxa_org_secret", "")
    else:
        # For non-default orgs, we need to store their secrets
        # For now, try to get from local org_secrets table
        with get_connection() as conn:
            row = conn.execute("SELECT org_secret FROM org_secrets WHERE org_id = ?", (target_org_id,)).fetchone()
        if row:
            target_org_secret = row["org_secret"]
        else:
            raise HTTPException(status_code=400, detail="Target org secret not available. Only default org or orgs with stored secrets are supported.")

    if not target_org_secret:
        raise HTTPException(status_code=400, detail="Target org secret is empty.")

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
    with get_connection() as conn:
        conn.execute(
            "UPDATE instance_configs SET org_id = ?, org_token = ? WHERE instance_id = ?",
            (target_org_id, new_token, instance_id),
        )
        conn.commit()

    return {"ok": True, "new_org_id": target_org_id, "agent_name": agent_name}


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
    container_name = f"hire_{instance_id}"
    # Check product type
    runtime_dir = RUNTIME_ROOT / instance_id
    oc_cfg = runtime_dir / "openclaw-config" / "openclaw.json"

    if oc_cfg.exists():
        # OpenClaw: restart the main process
        subprocess.run(
            ["docker", "exec", container_name, "pm2", "restart", "all"],
            capture_output=True, timeout=30,
        )
    else:
        # Zylos: restart hxa-connect component
        subprocess.run(
            ["docker", "exec", container_name, "pm2", "restart", "zylos-hxa-connect"],
            capture_output=True, timeout=30,
        )
