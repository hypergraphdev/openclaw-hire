"""Marketplace routes — plugin & skill installation into running instances."""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..database import get_connection
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


# ── Catalog (hardcoded) ──────────────────────────────────────────────────────

MARKETPLACE_ITEMS = [
    {
        "id": "weixin-plugin",
        "type": "plugin",
        "name": "WeChat Integration",
        "name_zh": "微信绑定",
        "description": "Connect your OpenClaw instance to WeChat. Scan QR code to bind your WeChat account and chat with your AI agent via WeChat.",
        "description_zh": "将 OpenClaw 实例连接微信。扫码绑定后，可通过微信与 AI Agent 对话。",
        "icon": "💬",
        "product": "openclaw",
        "tags": ["WeChat", "Messaging", "Social"],
        "version": "latest",
        "install_time": "~30s",
        "note": "Installation will output a QR code. Scan it with WeChat to complete binding.",
        "note_zh": "安装完成后会输出二维码，请用微信扫码完成绑定。",
    },
    {
        "id": "whisper-skill",
        "type": "skill",
        "name": "Speech to Text (Whisper)",
        "name_zh": "语音转文本 (Whisper)",
        "description": "Install OpenAI Whisper for speech-to-text transcription. Includes tiny (~75MB) and base (~140MB) models.",
        "description_zh": "安装 OpenAI Whisper 语音转文本模型，包含 tiny (~75MB) 和 base (~140MB) 两个模型。",
        "icon": "🎙️",
        "product": "all",
        "tags": ["AI", "Speech", "Transcription"],
        "version": "latest",
        "install_time": "~3min",
        "models": ["tiny (~75MB)", "base (~140MB)"],
    },
]

ITEM_MAP = {item["id"]: item for item in MARKETPLACE_ITEMS}


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/items")
def list_items():
    """Return all available plugins and skills."""
    return MARKETPLACE_ITEMS


@router.get("/installed")
def list_installed(
    instance_id: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Return installed plugins/skills for an instance."""
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT item_id, item_type, status, install_log, installed_at FROM marketplace_installs WHERE instance_id = %s",
        (instance_id,),
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


class InstallRequest(BaseModel):
    instance_id: str
    item_id: str


@router.post("/install")
def install_item(
    req: InstallRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Install a plugin or skill into an instance."""
    item = ITEM_MAP.get(req.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    # Verify instance ownership + running state
    user_id = current_user["id"]
    is_admin = bool(current_user.get("is_admin"))
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM instances WHERE id = %s", (req.instance_id,))
    inst = cursor.fetchone()
    cursor.close()

    if not inst:
        raise HTTPException(status_code=404, detail="Instance not found.")
    if inst["owner_id"] != user_id and not is_admin:
        raise HTTPException(status_code=403, detail="Not your instance.")
    if inst.get("status") not in ("running", "active"):
        raise HTTPException(status_code=409, detail="Instance must be running to install.")

    # Check product compatibility
    if item["product"] != "all" and inst["product"] != item["product"]:
        raise HTTPException(status_code=400, detail=f"This item is only for {item['product']} instances.")

    # Resolve container name
    container = _get_container_name(inst)
    if not container:
        raise HTTPException(status_code=409, detail="Cannot determine container name.")

    # Check not already installed
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT status FROM marketplace_installs WHERE instance_id = %s AND item_id = %s",
        (req.instance_id, req.item_id),
    )
    existing = cursor.fetchone()
    cursor.close()
    if existing and existing["status"] == "installed":
        raise HTTPException(status_code=409, detail="Already installed.")

    # Upsert install record as 'installing'
    now = datetime.now(timezone.utc).isoformat()
    cursor = db.cursor()
    cursor.execute(
        """INSERT INTO marketplace_installs (instance_id, item_id, item_type, status, install_log, installed_at)
           VALUES (%s, %s, %s, 'installing', '', %s)
           ON DUPLICATE KEY UPDATE status='installing', install_log='', installed_at=VALUES(installed_at)""",
        (req.instance_id, req.item_id, item["type"], now),
    )
    cursor.close()

    # Run installation in background thread (can take minutes for Whisper)
    thread = threading.Thread(
        target=_run_install,
        args=(req.instance_id, req.item_id, container),
        daemon=True,
    )
    thread.start()

    return {"ok": True, "status": "installing", "message": "Installation started. Poll /installed to check progress."}


@router.get("/install-log")
def get_install_log(
    instance_id: str = Query(...),
    item_id: str = Query(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get the installation log (useful for QR code display)."""
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT status, install_log, installed_at FROM marketplace_installs WHERE instance_id = %s AND item_id = %s",
        (instance_id, item_id),
    )
    row = cursor.fetchone()
    cursor.close()
    if not row:
        raise HTTPException(status_code=404, detail="No install record found.")
    return row


# ── Install logic ────────────────────────────────────────────────────────────


def _get_container_name(inst: dict) -> str:
    """Resolve the main container name for an instance."""
    product = inst.get("product", "")
    inst_id = inst["id"]
    project = inst.get("compose_project", "")

    if product == "zylos":
        return f"zylos_{inst_id}"
    elif product == "openclaw" and project:
        return f"{project}-openclaw-gateway-1"
    return ""


def _run_install(instance_id: str, item_id: str, container: str):
    """Execute installation commands in the container. Updates DB with results."""
    try:
        if item_id == "weixin-plugin":
            ok, log = _install_weixin(container, instance_id, item_id)
        elif item_id == "whisper-skill":
            ok, log = _install_whisper(container)
        else:
            _update_install(instance_id, item_id, "failed", f"Unknown item: {item_id}")
            return

        _update_install(instance_id, item_id, "installed" if ok else "failed", log)
    except Exception as e:
        _update_install(instance_id, item_id, "failed", str(e))


def _install_weixin(container: str, instance_id: str = "", item_id: str = "") -> tuple[bool, str]:
    """Install WeChat plugin via npx. Returns (success, output).

    The CLI installs the plugin, shows a QR code, waits for user to scan,
    then completes the callback. We let it run until it exits naturally
    (up to 10 minutes for user to scan QR). Output is streamed to DB
    so the frontend can poll and display QR code in real-time.
    """
    try:
        proc = subprocess.Popen(
            ["docker", "exec", container, "npx", "-y", "@tencent-weixin/openclaw-weixin-cli@latest", "install"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        import time as _time
        output_lines: list[str] = []
        deadline = _time.time() + 600  # 10 min for user to scan QR
        last_flush = 0.0

        while _time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                _time.sleep(0.2)
                continue
            output_lines.append(line)
            # Flush to DB every 2 seconds so frontend can poll live
            now = _time.time()
            if instance_id and item_id and now - last_flush > 2:
                _update_install(instance_id, item_id, "installing", "".join(output_lines))
                last_flush = now

        if proc.poll() is None:
            # Still running after 10 min — kill
            proc.kill()
            proc.wait(timeout=5)
            output_lines.append("\n[超时] 等待扫码超过10分钟，进程已终止。\n")

        output = "".join(output_lines)
        success = proc.returncode == 0
        # Also consider success if key installation steps completed
        if not success and ("就绪" in output or "already at" in output):
            success = True

        return success, output
    except Exception as e:
        return False, f"ERROR: {e}"


def _install_whisper(container: str) -> tuple[bool, str]:
    """Install Whisper + download tiny and base models. Returns (success, log)."""
    logs = []
    ok = True

    # Step 1: pip install
    try:
        r1 = subprocess.run(
            ["docker", "exec", container, "pip", "install", "-U", "openai-whisper"],
            capture_output=True, text=True, timeout=300,
        )
        logs.append("=== pip install openai-whisper ===")
        logs.append(r1.stdout[-500:] if len(r1.stdout) > 500 else r1.stdout)
        if r1.returncode != 0:
            logs.append(r1.stderr[-500:])
            return False, "\n".join(logs)
    except subprocess.TimeoutExpired:
        return False, "ERROR: pip install timed out."

    # Step 2: Download tiny model
    try:
        r2 = subprocess.run(
            ["docker", "exec", container, "python3", "-c", "import whisper; whisper.load_model('tiny'); print('tiny model OK')"],
            capture_output=True, text=True, timeout=180,
        )
        logs.append("\n=== Download tiny model ===")
        logs.append(r2.stdout.strip())
        if r2.returncode != 0:
            logs.append(r2.stderr[-300:])
            ok = False
    except subprocess.TimeoutExpired:
        logs.append("\nWARNING: tiny model download timed out.")
        ok = False

    # Step 3: Download base model
    try:
        r3 = subprocess.run(
            ["docker", "exec", container, "python3", "-c", "import whisper; whisper.load_model('base'); print('base model OK')"],
            capture_output=True, text=True, timeout=300,
        )
        logs.append("\n=== Download base model ===")
        logs.append(r3.stdout.strip())
        if r3.returncode != 0:
            logs.append(r3.stderr[-300:])
            ok = False
    except subprocess.TimeoutExpired:
        logs.append("\nWARNING: base model download timed out.")
        ok = False

    return ok, "\n".join(logs)


def _update_install(instance_id: str, item_id: str, status: str, log: str):
    """Update marketplace_installs record."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE marketplace_installs SET status=%s, install_log=%s WHERE instance_id=%s AND item_id=%s",
            (status, log[:10000], instance_id, item_id),
        )
        cursor.close()
    finally:
        conn.close()
