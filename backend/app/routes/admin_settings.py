from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..database import get_setting, set_setting
from ..deps import get_current_user
from .admin import _require_admin

router = APIRouter(prefix="/api/admin", tags=["admin-settings"])

SETTING_KEYS = [
    "anthropic_base_url", "anthropic_auth_token",
    "openai_base_url", "openai_api_key",
    "hxa_org_id", "hxa_org_secret", "hxa_admin_secret", "hxa_invite_code",
]


class SettingsResponse(BaseModel):
    anthropic_base_url: str = ""
    anthropic_auth_token: str = ""
    openai_base_url: str = ""
    openai_api_key: str = ""
    hxa_org_id: str = ""
    hxa_org_secret: str = ""
    hxa_admin_secret: str = ""
    hxa_invite_code: str = ""


class SettingsUpdateRequest(BaseModel):
    anthropic_base_url: str | None = None
    anthropic_auth_token: str | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    hxa_org_id: str | None = None
    hxa_org_secret: str | None = None
    hxa_admin_secret: str | None = None
    hxa_invite_code: str | None = None


@router.get("/settings", response_model=SettingsResponse)
def get_settings(current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    return SettingsResponse(
        anthropic_base_url=get_setting("anthropic_base_url"),
        anthropic_auth_token=get_setting("anthropic_auth_token"),
        openai_base_url=get_setting("openai_base_url"),
        openai_api_key=get_setting("openai_api_key"),
        hxa_org_id=get_setting("hxa_org_id"),
        hxa_org_secret=get_setting("hxa_org_secret"),
        hxa_admin_secret=get_setting("hxa_admin_secret"),
        hxa_invite_code=get_setting("hxa_invite_code"),
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(body: SettingsUpdateRequest, current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        if key in SETTING_KEYS:
            set_setting(key, value)
    return get_settings(current_user)
