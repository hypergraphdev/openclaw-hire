from __future__ import annotations

import json
import urllib.request
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
