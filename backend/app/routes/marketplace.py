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
            # Only mark "installed" if user completed QR scan (returncode == 0)
            # Otherwise mark "failed" so user can retry
            _update_install(instance_id, item_id, "installed" if ok else "failed", log)
        elif item_id == "whisper-skill":
            ok, log = _install_whisper(container)
            _update_install(instance_id, item_id, "installed" if ok else "failed", log)
        else:
            _update_install(instance_id, item_id, "failed", f"Unknown item: {item_id}")
    except Exception as e:
        _update_install(instance_id, item_id, "failed", str(e))


def _install_weixin(container: str, instance_id: str = "", item_id: str = "") -> tuple[bool, str]:
    """Install WeChat plugin 2.0.x via manual npm pack (bypasses CLI legacy bug).

    Steps:
    1. Check OpenClaw version (must be >= 2026.3.24)
    2. Download and extract plugin 2.0.x into extensions dir
    3. Add channel config to openclaw.json
    4. Restart gateway to load plugin
    5. Run `openclaw channels login` for QR code (streamed to DB)
    """
    import time as _time
    logs: list[str] = []
    PLUGIN_VERSION = "2.0.1"
    EXT_DIR = "/home/node/.openclaw/extensions/openclaw-weixin"
    CONFIG_PATH = "/home/node/.openclaw/openclaw.json"

    def _log(msg: str):
        logs.append(msg + "\n")

    def _flush():
        if instance_id and item_id:
            _update_install(instance_id, item_id, "installing", "".join(logs))

    def _exec(cmd: list[str], timeout: int = 60, user: str = "") -> tuple[int, str]:
        full_cmd = ["docker", "exec"]
        if user:
            full_cmd += ["-u", user]
        full_cmd += [container] + cmd
        try:
            r = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            return 1, "timeout"

    # Step 1: Check OpenClaw version
    _log("=== 检查 OpenClaw 版本 ===")
    rc, ver_out = _exec(["sh", "-c", "cat /app/package.json 2>/dev/null | grep '\"version\"' | head -1"])
    _log(ver_out)
    _flush()
    if "2026.3.24" not in ver_out and "2026.3.25" not in ver_out and "2026.4" not in ver_out and "2027" not in ver_out:
        # Try to detect actual version number
        ver_match = ""
        for part in ver_out.split('"'):
            if part.startswith("2026.") or part.startswith("2027."):
                ver_match = part
                break
        if ver_match and ver_match < "2026.3.24":
            _log(f"⚠️  当前版本 {ver_match} 过低，微信插件 2.0.x 需要 >= 2026.3.24")
            _log("请先在实例详情页升级 OpenClaw 版本。")
            return False, "".join(logs)

    # Step 2: Download and extract plugin
    _log("\n=== 安装微信插件 %s ===" % PLUGIN_VERSION)
    _flush()
    rc, out = _exec(["sh", "-c", f"mkdir -p {EXT_DIR} && cd {EXT_DIR} && npm pack @tencent-weixin/openclaw-weixin@{PLUGIN_VERSION} 2>&1"], timeout=60)
    _log(out)
    _flush()
    if rc != 0 or ".tgz" not in out:
        _log("❌ 下载插件包失败")
        return False, "".join(logs)

    tgz_file = out.strip().split("\n")[-1].strip()
    rc, out = _exec(["sh", "-c", f"cd {EXT_DIR} && tar xzf {tgz_file} --strip-components=1 && rm -f {tgz_file}"])
    _log("解压完成")

    _log("安装依赖...")
    _flush()
    rc, out = _exec(["sh", "-c", f"cd {EXT_DIR} && npm install --production 2>&1 | tail -5"], timeout=120)
    _log(out)
    _flush()

    # Verify version
    rc, out = _exec(["sh", "-c", f"cat {EXT_DIR}/package.json | grep '\"version\"' | head -1"])
    _log(f"插件版本: {out.strip()}")

    # Step 3: Ensure channel config
    _log("\n=== 配置 openclaw.json ===")
    _flush()
    config_script = f"""
import json
with open("{CONFIG_PATH}") as f:
    cfg = json.load(f)
changed = False
if "channels" not in cfg:
    cfg["channels"] = {{}}
if "openclaw-weixin" not in cfg["channels"]:
    cfg["channels"]["openclaw-weixin"] = {{"enabled": True}}
    changed = True
if "plugins" not in cfg:
    cfg["plugins"] = {{}}
if "entries" not in cfg["plugins"]:
    cfg["plugins"]["entries"] = {{}}
if "openclaw-weixin" not in cfg["plugins"]["entries"]:
    cfg["plugins"]["entries"]["openclaw-weixin"] = {{"enabled": True}}
    changed = True
if changed:
    with open("{CONFIG_PATH}", "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\\n")
    print("config updated")
else:
    print("config already ok")
"""
    rc, out = _exec(["python3", "-c", config_script])
    _log(out)

    # Step 4: Restart gateway
    _log("\n=== 重启 Gateway 加载插件 ===")
    _flush()
    subprocess.run(["docker", "restart", container], capture_output=True, timeout=30)
    _time.sleep(8)
    _log("Gateway 已重启")
    _flush()

    # Check plugin loaded without errors
    rc, check_out = _exec(["sh", "-c", f"cat /tmp/openclaw/openclaw-*.log 2>/dev/null | grep -i 'weixin.*fail' | tail -3"])
    if "fail" in check_out.lower():
        _log(f"⚠️  插件加载异常: {check_out}")
        _flush()

    # Step 5: Run channels login for QR code
    _log("\n=== 启动微信扫码登录 ===")
    _log("执行 openclaw channels login --channel openclaw-weixin\n")
    _flush()

    try:
        proc = subprocess.Popen(
            ["docker", "exec", container, "stdbuf", "-oL", "openclaw", "channels", "login", "--channel", "openclaw-weixin"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        deadline = _time.time() + 600  # 10 min for user to scan QR
        last_flush_t = 0.0
        qr_found = False

        while _time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                _time.sleep(0.2)
                continue
            logs.append(line)
            now = _time.time()
            if now - last_flush_t > 1:
                _flush()
                last_flush_t = now
            # Detect QR code lines (block characters)
            if "▄" in line or "█" in line or "二维码" in line or "扫描" in line:
                qr_found = True

        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
            _log("\n[超时] 等待扫码超过10分钟，进程已终止。")

        _flush()
        success = proc.returncode == 0
        if success:
            _log("\n✅ 微信绑定成功！")
        elif qr_found:
            _log("\n⚠️  二维码已显示但未完成扫码绑定。请重新安装以获取新的二维码。")
        return success, "".join(logs)
    except Exception as e:
        _log(f"\nERROR: {e}")
        return False, "".join(logs)


def _install_whisper(container: str) -> tuple[bool, str]:
    """Install Whisper + download tiny and base models. Returns (success, log)."""
    logs = []
    ok = True

    # Step 0: ensure pip + ffmpeg are available
    try:
        r0 = subprocess.run(
            ["docker", "exec", "-u", "root", container, "sh", "-c",
             "apt-get update -qq && apt-get install -y -qq ffmpeg python3-pip 2>&1 | tail -5 && pip3 --version && ffmpeg -version | head -1"],
            capture_output=True, text=True, timeout=180,
        )
        logs.append("=== ensure pip + ffmpeg ===")
        logs.append(r0.stdout.strip()[-400:])
        if r0.returncode != 0:
            logs.append(r0.stderr[-300:])
            return False, "\n".join(logs)
    except subprocess.TimeoutExpired:
        return False, "ERROR: dependency install timed out."

    # Step 1: pip install
    try:
        r1 = subprocess.run(
            ["docker", "exec", "-u", "root", container, "pip3", "install", "-U", "--break-system-packages", "openai-whisper"],
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

    # Step 4: Write skill file so the AI agent knows about Whisper capability
    if ok:
        skill_content = r"""# Whisper 语音转文本技能

## 能力说明
你的系统已安装 OpenAI Whisper 和 FFmpeg，具备本地语音转文字能力。

## 可用模型
- **tiny** (~75MB) - 速度最快，适合简短语音
- **base** (~140MB) - 平衡速度和准确度，推荐日常使用

## 使用方法

### Python 调用
```python
import whisper

model = whisper.load_model("base")  # 或 "tiny"
result = model.transcribe("audio_file.mp3")
print(result["text"])
```

### 命令行调用
```bash
whisper audio_file.mp3 --model base --language zh
```

### 支持的音频格式
mp3, wav, m4a, ogg, flac, webm 等（FFmpeg 支持的所有格式）

### 支持的语言
中文、英文、日文等 99 种语言。可指定 `--language` 参数，或让模型自动检测。

## 注意事项
- 当用户发送音频文件时，直接用 Whisper 在本地转录，无需调用外部 API
- 优先使用 base 模型，如果速度要求高可用 tiny
- 转录完成后直接展示文字结果
"""
        # Determine skill directory based on container type
        # OpenClaw: /home/node/.openclaw/skills/
        # Zylos: /home/zylos/zylos/.claude/skills/
        for skill_dir in [
            "/home/node/.openclaw/skills/whisper-transcription",
            "/home/zylos/zylos/.claude/skills/whisper-transcription",
        ]:
            try:
                subprocess.run(
                    ["docker", "exec", container, "mkdir", "-p", skill_dir],
                    capture_output=True, timeout=10,
                )
                subprocess.run(
                    ["docker", "exec", container, "sh", "-c", f"cat > {skill_dir}/SKILL.md << 'SKILLEOF'\n{skill_content}\nSKILLEOF"],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass
        logs.append("\n=== 技能文件已写入 ===")
        logs.append("AI Agent 现在知道自己有 Whisper 语音转文字能力了。")

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
