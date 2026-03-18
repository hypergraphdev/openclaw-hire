from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from ..database import get_setting
from ..deps import get_current_user
from ..database import get_connection
from .admin import _require_admin

router = APIRouter(prefix="/api/admin/hxa", tags=["admin-hxa"])

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")


def _get_agents() -> list[dict]:
    agents = []
    if not RUNTIME_ROOT.exists():
        return agents

    # Get instance names from DB
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, product FROM instances").fetchall()
        instance_map = {r["id"]: {"name": r["name"], "product": r["product"]} for r in rows}

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
            })

    return agents


@router.get("/config")
def get_hxa_config(current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    return {
        "org_id": get_setting("hxa_org_id", "123cd566-c2ea-409f-8f7e-4fa9f5296dd1"),
        "org_secret": get_setting("hxa_org_secret"),
        "hub_url": "https://www.ucai.net/connect",
    }


@router.get("/agents")
def get_hxa_agents(current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    return {"agents": _get_agents()}
