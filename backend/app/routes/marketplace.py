"""Marketplace routes — plugin & skill installation into running instances."""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..database import get_connection, get_config
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
        "tags": ["微信", "聊天", "社交"],
        "version": "latest",
        "install_time": "~30s",
        "note": "Installation will output a QR code. Scan it with WeChat to complete binding.",
        "note_zh": "安装完成后会输出二维码，请用微信扫码完成绑定。",
    },
    {
        "id": "whisper-skill",
        "type": "skill",
        "name": "Speech to Text",
        "name_zh": "语音转文本",
        "description": "Enable your AI agent to transcribe audio files into text. Supports 99 languages with automatic detection.",
        "description_zh": "让你的 AI Agent 能听懂语音，将音频文件自动转录为文字。支持 99 种语言，自动识别。",
        "icon": "🎙️",
        "product": "all",
        "tags": ["语音", "转录", "多语言"],
        "version": "latest",
        "install_time": "~5s",
    },
    {
        "id": "weixin-zylos-plugin",
        "type": "plugin",
        "name": "WeChat Integration (Zylos)",
        "name_zh": "微信插件 Zylos版",
        "description": "Connect your Zylos instance to WeChat. QR code login, long-poll messaging, media support.",
        "description_zh": "将 Zylos 实例连接微信。支持扫码登录、长轮询收消息、图片/文件/语音。",
        "icon": "💬",
        "product": "zylos",
        "tags": ["微信", "聊天", "社交"],
        "version": "1.0.0",
        "install_time": "~30s",
        "note": "After install, the plugin will display a QR code. Scan it with WeChat to complete binding.",
        "note_zh": "安装后插件会输出二维码，请用微信扫码完成绑定。可在日志中查看扫码链接。",
    },
    {
        "id": "edge-tts-skill",
        "type": "skill",
        "name": "Text to Speech",
        "name_zh": "文本转语音",
        "description": "Enable your AI agent to speak — convert text into natural-sounding audio. 300+ voices, 40+ languages.",
        "description_zh": "让你的 AI Agent 能开口说话，将文字转换为自然语音。300+ 种声音，40+ 种语言。",
        "icon": "🔊",
        "product": "all",
        "tags": ["语音", "朗读", "多语言"],
        "version": "latest",
        "install_time": "~30s",
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
        elif item_id == "weixin-zylos-plugin":
            ok, log = _install_weixin_zylos(container, instance_id, item_id)
            _update_install(instance_id, item_id, "installed" if ok else "failed", log)
        elif item_id == "edge-tts-skill":
            ok, log = _install_edge_tts(container)
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

    # Step 1: Check OpenClaw version (use `openclaw --version`, not package.json)
    _log("=== 检查 OpenClaw 版本 ===")
    rc, ver_out = _exec(["openclaw", "--version"])
    _log(ver_out)
    _flush()
    # Parse version from "OpenClaw 2026.3.24 (cff6dc9)" format
    ver_match = ""
    for word in ver_out.split():
        if word.startswith("2026.") or word.startswith("2027."):
            ver_match = word
            break
    if ver_match and ver_match < "2026.3.24":
        _log(f"⚠️  当前版本 {ver_match} 过低，微信插件 2.0.x 需要 >= 2026.3.24")
        _log("请先在实例详情页升级 OpenClaw 版本。")
        return False, "".join(logs)

    # Step 1.5: Fix npm cache permissions (may be root-owned after upgrade)
    _exec(["chown", "-R", "1000:1000", "/home/node/.npm"], user="root", timeout=15)

    # Step 2: Download and extract plugin
    _log("\n=== 安装微信插件 %s ===" % PLUGIN_VERSION)
    _flush()
    rc, out = _exec(["sh", "-c", f"mkdir -p {EXT_DIR} && cd {EXT_DIR} && npm pack @tencent-weixin/openclaw-weixin@{PLUGIN_VERSION} 2>&1"], timeout=60)
    _log(out)
    _flush()
    if rc != 0 or ".tgz" not in out:
        _log("❌ 下载插件包失败")
        return False, "".join(logs)

    tgz_file = ""
    for line in out.strip().split("\n"):
        line = line.strip()
        if line.endswith(".tgz") and not line.startswith("npm"):
            tgz_file = line
            break
    if not tgz_file:
        _log("❌ 未找到 tgz 文件名，npm pack 输出:\n" + out)
        return False, "".join(logs)

    rc, out = _exec(["sh", "-c", f"cd {EXT_DIR} && tar xzf {tgz_file} --strip-components=1 && rm -f {tgz_file}"])
    if rc != 0:
        _log(f"❌ 解压失败: {out}")
        return False, "".join(logs)
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
import json, datetime
with open("{CONFIG_PATH}") as f:
    cfg = json.load(f)
if "channels" not in cfg:
    cfg["channels"] = {{}}
cfg["channels"]["openclaw-weixin"] = {{"enabled": True}}
if "plugins" not in cfg:
    cfg["plugins"] = {{}}
if "entries" not in cfg["plugins"]:
    cfg["plugins"]["entries"] = {{}}
cfg["plugins"]["entries"]["openclaw-weixin"] = {{"enabled": True}}
# Must have installs record — OpenClaw 3.24+ validates channel id against installed plugins
if "installs" not in cfg["plugins"]:
    cfg["plugins"]["installs"] = {{}}
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
cfg["plugins"]["installs"]["openclaw-weixin"] = {{
    "source": "npm",
    "spec": "@tencent-weixin/openclaw-weixin@{PLUGIN_VERSION}",
    "installPath": "{EXT_DIR}",
    "version": "{PLUGIN_VERSION}",
    "resolvedName": "@tencent-weixin/openclaw-weixin",
    "resolvedVersion": "{PLUGIN_VERSION}",
    "resolvedSpec": "@tencent-weixin/openclaw-weixin@{PLUGIN_VERSION}",
    "resolvedAt": now,
    "installedAt": now,
}}
with open("{CONFIG_PATH}", "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\\n")
print("config updated")
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
        # Write output to a file inside the container (volume-mapped to host).
        # Read directly from host filesystem — zero buffering, no pipe issues.
        container_log = "/home/node/.openclaw/weixin-login.log"
        # Volume: container /home/node/.openclaw ↔ host runtime/{id}/openclaw-config
        from ..database import get_connection as _gc
        _conn = _gc()
        _cur = _conn.cursor(dictionary=True)
        _cur.execute("SELECT runtime_dir FROM instances WHERE id=%s", (instance_id,))
        _row = _cur.fetchone()
        _cur.close()
        _conn.close()
        host_log = os.path.join(_row["runtime_dir"], "openclaw-config", "weixin-login.log") if _row else ""

        # Clear any previous log
        subprocess.run(["docker", "exec", container, "sh", "-c", f"rm -f {container_log}; touch {container_log}"],
                        capture_output=True, timeout=10)

        # Start login process in background, writing to the log file via script (PTY for unbuffered)
        proc = subprocess.Popen(
            ["docker", "exec", container, "script", "-qc",
             f"openclaw channels login --channel openclaw-weixin 2>&1 | tee {container_log}",
             "/dev/null"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )

        deadline = _time.time() + 600  # 10 min for user to scan QR
        last_flush_t = 0.0
        qr_found = False
        last_size = 0

        while _time.time() < deadline:
            _time.sleep(0.5)
            # Read new content from host file
            try:
                with open(host_log, "r", errors="replace") as f:
                    content = f.read()
            except FileNotFoundError:
                if proc.poll() is not None:
                    break
                continue

            if len(content) > last_size:
                new_text = content[last_size:]
                last_size = len(content)
                # Clean TTY artifacts
                new_text = new_text.replace("\r\n", "\n").replace("\r", "")
                logs.append(new_text)
                if "▄" in new_text or "█" in new_text or "二维码" in new_text:
                    qr_found = True
                now = _time.time()
                if now - last_flush_t > 0.3:
                    _flush()
                    last_flush_t = now

            if proc.poll() is not None:
                # Process exited — read final content
                _time.sleep(0.5)
                try:
                    with open(host_log, "r", errors="replace") as f:
                        final = f.read()
                    if len(final) > last_size:
                        logs.append(final[last_size:].replace("\r\n", "\n").replace("\r", ""))
                except FileNotFoundError:
                    pass
                break

        # Cleanup log file
        try:
            os.unlink(host_log)
        except OSError:
            pass

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
    """Write Whisper skill file to container. No software install needed —
    the shared Whisper Web Service on the host handles all transcription."""
    import tempfile

    logs: list[str] = []

    # Step 1: Verify host Whisper service is reachable from container
    whisper_url = get_config("whisper_service_url", "http://172.17.0.1:8019")
    logs.append("=== 检查 Whisper 服务连通性 ===")
    try:
        r = subprocess.run(
            ["docker", "exec", container, "node", "-e",
             f'fetch("{whisper_url}/health").then(r=>r.json()).then(d=>{{console.log("OK model="+d.default_model+" loaded="+d.loaded_models.join(","))}}).catch(e=>console.log("FAIL:"+e.message))'],
            capture_output=True, text=True, timeout=15,
        )
        output = r.stdout.strip()
        logs.append(output)
        if "FAIL" in output or r.returncode != 0:
            logs.append(f"\n⚠️  容器无法访问宿主机 Whisper 服务 ({whisper_url})")
            logs.append("请确认 whisper.service 已启动: systemctl status whisper")
            return False, "\n".join(logs)
    except subprocess.TimeoutExpired:
        logs.append("连接超时")
        return False, "\n".join(logs)

    # Step 2: Write skill file
    logs.append("\n=== 写入技能文件 ===")
    skill_content = f"""# Whisper 语音转文本技能

## 能力说明
宿主机运行了共享的 Whisper 转录服务，通过 HTTP API 调用，模型常驻内存，响应快速。

## 使用方式
**不要在本地运行 whisper 命令**，通过 HTTP API 调用宿主机服务：

```bash
curl -s -X POST {whisper_url}/transcribe \\
  -F "file=@音频文件路径" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['text'])"
```

## 语言检测规则
- **默认不指定 language 参数**，让 Whisper 自动检测语言
- 只有用户明确要求特定语言输出时，才加 `-F "language=zh"` 或 `-F "language=en"`
- 输出语言与音频语言一致（英文音频输出英文，中文音频输出中文）

## 可用参数
- `file` (必须) — 音频文件
- `language` (可选) — zh/en/ja 等，默认自动检测
- `model` (可选) — tiny/base/small，默认 small

## 支持的音频格式
mp3, wav, m4a, ogg, flac, webm, mp4, aac 等

## 注意事项
- 当用户发送音频文件时，先下载到本地，再通过 API 转录
- 转录完成后直接展示文字结果
- 如需更快速度，指定 model=tiny
"""
    skill_written = False
    for skill_dir in [
        "/home/node/.openclaw/skills/whisper-transcription",
        "/home/zylos/zylos/.claude/skills/whisper-transcription",
    ]:
        try:
            subprocess.run(
                ["docker", "exec", container, "mkdir", "-p", skill_dir],
                capture_output=True, timeout=10,
            )
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(skill_content)
                tmp_path = f.name
            r = subprocess.run(
                ["docker", "cp", tmp_path, f"{container}:{skill_dir}/SKILL.md"],
                capture_output=True, text=True, timeout=10,
            )
            os.unlink(tmp_path)
            if r.returncode == 0:
                logs.append(f"✅ 技能文件已写入 {skill_dir}/SKILL.md")
                skill_written = True
        except Exception as e:
            logs.append(f"写入异常: {e}")

    if skill_written:
        logs.append("\n✅ 安装完成！AI Agent 现在可以通过 Whisper 服务转录语音了。")
        logs.append("无需安装任何软件，所有转录由宿主机共享服务处理。")
        return True, "\n".join(logs)
    else:
        logs.append("\n❌ 技能文件写入失败")
        return False, "\n".join(logs)


def _update_install(instance_id: str, item_id: str, status: str, log: str):
    """Update marketplace_installs record."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE marketplace_installs SET status=%s, install_log=%s WHERE instance_id=%s AND item_id=%s",
            (status, log[-50000:], instance_id, item_id),
        )
        cursor.close()
    finally:
        conn.close()


def _install_edge_tts(container: str) -> tuple[bool, str]:
    """Install edge-tts in container + write skill file."""
    import tempfile

    logs: list[str] = []

    # Step 1: pip install edge-tts
    logs.append("=== pip install edge-tts ===")
    try:
        r = subprocess.run(
            ["docker", "exec", "-u", "root", container, "sh", "-c",
             "pip3 install -U --break-system-packages edge-tts 2>&1 || "
             "pip install -U --break-system-packages edge-tts 2>&1 || "
             "(apt-get update -qq && apt-get install -y -qq python3-pip && pip3 install -U --break-system-packages edge-tts) 2>&1"],
            capture_output=True, text=True, timeout=120,
        )
        output = r.stdout.strip()
        logs.append(output[-500:] if len(output) > 500 else output)
        if r.returncode != 0:
            logs.append(r.stderr[-300:] if r.stderr else "")
            return False, "\n".join(logs)
    except subprocess.TimeoutExpired:
        return False, "ERROR: pip install timed out."

    # Step 2: Verify install
    logs.append("\n=== 验证安装 ===")
    try:
        r2 = subprocess.run(
            ["docker", "exec", container, "python3", "-c", "import edge_tts; print('edge-tts OK, version:', edge_tts.__version__)"],
            capture_output=True, text=True, timeout=15,
        )
        logs.append(r2.stdout.strip())
        if r2.returncode != 0:
            logs.append(r2.stderr[-200:])
            return False, "\n".join(logs)
    except Exception as e:
        logs.append(f"验证失败: {e}")
        return False, "\n".join(logs)

    # Step 3: Write skill file
    logs.append("\n=== 写入技能文件 ===")
    skill_content = """# Edge TTS 文本转语音技能

## 能力说明
本系统已安装 edge-tts，可以将文本转换为高质量语音。
使用微软 Edge 在线 TTS 服务，支持 300+ 种声音、40+ 种语言。

## 使用方法

### 命令行（推荐，最简单）
```bash
# 自动检测语言，使用默认声音
edge-tts --text "要转换的文本" --write-media output.mp3

# 指定中文声音
edge-tts --text "你好世界" --voice zh-CN-XiaoxiaoNeural --write-media output.mp3

# 指定英文声音
edge-tts --text "Hello world" --voice en-US-AriaNeural --write-media output.mp3

# 指定日文声音
edge-tts --text "こんにちは" --voice ja-JP-NanamiNeural --write-media output.mp3
```

### Python 调用
```python
import asyncio
import edge_tts

async def tts(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

# 中文
asyncio.run(tts("你好世界", "zh-CN-XiaoxiaoNeural", "output.mp3"))
# 英文
asyncio.run(tts("Hello world", "en-US-AriaNeural", "output.mp3"))
```

### 列出所有可用声音
```bash
edge-tts --list-voices | head -50
```

## 语言检测与声音选择规则
- **根据文本语言自动选择对应语言的声音**
- 中文文本 → zh-CN-XiaoxiaoNeural（女）或 zh-CN-YunxiNeural（男）
- 英文文本 → en-US-AriaNeural（女）或 en-US-GuyNeural（男）
- 日文文本 → ja-JP-NanamiNeural（女）
- 韩文文本 → ko-KR-SunHiNeural（女）
- 默认使用女声，用户要求男声时切换

## 常用声音列表
| 语言 | 女声 | 男声 |
|------|------|------|
| 中文 | zh-CN-XiaoxiaoNeural | zh-CN-YunxiNeural |
| 英文 | en-US-AriaNeural | en-US-GuyNeural |
| 日文 | ja-JP-NanamiNeural | ja-JP-KeitaNeural |
| 韩文 | ko-KR-SunHiNeural | ko-KR-InJoonNeural |
| 法语 | fr-FR-DeniseNeural | fr-FR-HenriNeural |
| 德语 | de-DE-KatjaNeural | de-DE-ConradNeural |

## 注意事项
- 当用户要求朗读文本、生成语音时，直接使用 edge-tts
- 生成后将 mp3 文件发送给用户
- 需要网络连接（调用微软在线服务）
- 完全免费，无需 API Key
"""
    skill_written = False
    for skill_dir in [
        "/home/node/.openclaw/skills/edge-tts",
        "/home/zylos/zylos/.claude/skills/edge-tts",
    ]:
        try:
            subprocess.run(
                ["docker", "exec", container, "mkdir", "-p", skill_dir],
                capture_output=True, timeout=10,
            )
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(skill_content)
                tmp_path = f.name
            r = subprocess.run(
                ["docker", "cp", tmp_path, f"{container}:{skill_dir}/SKILL.md"],
                capture_output=True, text=True, timeout=10,
            )
            os.unlink(tmp_path)
            if r.returncode == 0:
                logs.append(f"✅ 技能文件已写入 {skill_dir}/SKILL.md")
                skill_written = True
        except Exception as e:
            logs.append(f"写入异常: {e}")

    if skill_written:
        logs.append("\n✅ 安装完成！AI Agent 现在可以将文本转换为语音了。")
        return True, "\n".join(logs)
    else:
        logs.append("\n❌ 技能文件写入失败")
        return False, "\n".join(logs)


# ── Zylos WeChat Plugin ──────────────────────────────────────────────────────

def _install_weixin_zylos(container: str, instance_id: str = "", item_id: str = "") -> tuple[bool, str]:
    """Install WeChat plugin for Zylos via tarball + PM2."""
    import time as _time
    logs: list[str] = []
    SKILL_DIR = "/home/zylos/zylos/.claude/skills/weixin"
    DATA_DIR = "/home/zylos/zylos/components/weixin"
    TARBALL_HOST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "zylos-weixin.tgz")

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

    # Step 1: Copy tarball into container
    _log("=== 安装微信插件 Zylos版 ===")
    _flush()

    if not os.path.exists(TARBALL_HOST):
        _log(f"❌ 找不到安装包: {TARBALL_HOST}")
        return False, "".join(logs)

    rc = subprocess.run(
        ["docker", "cp", TARBALL_HOST, f"{container}:/tmp/zylos-weixin.tgz"],
        capture_output=True, text=True, timeout=30,
    ).returncode
    if rc != 0:
        _log("❌ 拷贝安装包到容器失败")
        return False, "".join(logs)
    _log("安装包已拷入容器")

    # Step 2: Extract
    _log("\n=== 解压插件 ===")
    _flush()
    rc, out = _exec(["sh", "-c", f"mkdir -p {SKILL_DIR} && cd {SKILL_DIR} && tar xzf /tmp/zylos-weixin.tgz --strip-components=1 --no-same-owner --touch"])
    if rc != 0:
        _log(f"❌ 解压失败: {out}")
        return False, "".join(logs)
    _log("解压完成")

    # Clean up tarball and fix ownership (docker cp + tar may create root-owned files)
    _exec(["rm", "-f", "/tmp/zylos-weixin.tgz"], user="root", timeout=10)
    _exec(["chown", "-R", "zylos:zylos", SKILL_DIR], user="root", timeout=10)

    # Step 3: Create data directories
    rc, out = _exec(["sh", "-c", f"mkdir -p {DATA_DIR}/logs {DATA_DIR}/accounts {DATA_DIR}/sync-buffers"])
    _log("数据目录已创建")

    # Step 4: Install dependencies
    _log("\n=== 安装依赖 ===")
    _flush()
    rc, out = _exec(["sh", "-c", f"cd {SKILL_DIR} && npm install --production 2>&1 | tail -5"], timeout=120)
    _log(out)
    if rc != 0:
        _log("❌ npm install 失败")
        return False, "".join(logs)

    # Ensure C4 send adapter exists (package should include scripts/send.js,
    # but create fallback if missing for older tgz versions)
    rc, _ = _exec(["test", "-f", f"{SKILL_DIR}/scripts/send.js"], timeout=5)
    if rc != 0:
        _exec(["sh", "-c", f"""mkdir -p {SKILL_DIR}/scripts && cat > {SKILL_DIR}/scripts/send.js << 'WRAPPER'
#!/usr/bin/env node
// ESM adapter: package has "type":"module"
import {{ execFileSync }} from "node:child_process";
import path from "node:path";
import {{ fileURLToPath }} from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
if (args.length < 2) {{ console.error("Usage: send.js <endpoint> <message>"); process.exit(1); }}
try {{
  execFileSync("node", [
    path.join(__dirname, "..", "dist", "scripts", "send.js"),
    "--channel", "weixin",
    "--endpoint", args[0],
    "--content", args[1]
  ], {{ stdio: "inherit" }});
}} catch (e) {{ process.exit(e.status || 1); }}
WRAPPER"""], timeout=10)
        _log("C4 send adapter 已创建（fallback）")
    else:
        _log("C4 send adapter 已就绪")

    # Step 5: Start PM2 process
    _log("\n=== 启动插件 ===")
    _flush()
    # Try restart first (if already in PM2), otherwise start
    rc, out = _exec(["pm2", "restart", "zylos-weixin"], timeout=15)
    if rc != 0:
        rc, out = _exec(["sh", "-c", f"cd {SKILL_DIR} && pm2 start ecosystem.config.cjs"], timeout=15)
    if rc != 0:
        _log(f"❌ PM2 启动失败: {out}")
        return False, "".join(logs)
    _log("PM2 进程已启动")

    # Setup cleanup cron for stale send.js processes
    # (send.js imports bot.js which starts a long-poll loop, causing zombie processes)
    cleanup_script = "/home/zylos/zylos/cleanup-stale-sends.sh"
    _exec(["sh", "-c", f"""cat > {cleanup_script} << 'CLEANUP'
#!/bin/sh
ps -eo pid,etimes,cmd | grep "dist/scripts/send.js" | grep -v grep | while read pid etime cmd; do
  if [ "$etime" -gt 30 ] 2>/dev/null; then kill "$pid" 2>/dev/null; fi
done
CLEANUP
chmod +x {cleanup_script}"""], timeout=10)
    _exec(["sh", "-c", f"pm2 delete cleanup-sends 2>/dev/null; pm2 start {cleanup_script} --name cleanup-sends --cron-restart '* * * * *' --no-autorestart 2>/dev/null"], timeout=10)

    # Save PM2 state
    _exec(["pm2", "save"], timeout=10)

    # Step 6: Wait a moment and check logs for QR code
    _log("\n=== 等待初始化 ===")
    _flush()
    _time.sleep(5)
    rc, out = _exec(["sh", "-c", f"tail -30 {DATA_DIR}/logs/out.log 2>/dev/null"])
    if out:
        _log(out)
    _flush()

    # Check PM2 status
    rc, out = _exec(["pm2", "show", "zylos-weixin", "--no-color"], timeout=10)
    if "online" in out.lower():
        _log("\n✅ 微信插件已安装并启动。请查看日志中的二维码链接完成绑定。")
        return True, "".join(logs)
    else:
        _log(f"\n⚠️ 插件已安装但状态异常:\n{out}")
        return False, "".join(logs)
