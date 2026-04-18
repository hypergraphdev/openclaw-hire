import { useEffect, useState } from "react";
import { api } from "../api";

interface Props {
  instanceId: string;
  agentName: string;
}

/**
 * Telegram bridge config for a Local Agent instance.
 *
 * The server-side companion (POST /api/instances/:id/telegram-bridge) creates
 * a dedicated "bridge bot" in the HXA org and returns a copy-paste command
 * the user runs on their own machine via `hxa-channel-daemon`. No container
 * is touched — this is pure local daemon territory.
 */
export function LocalAgentTelegramBridge({ instanceId, agentName }: Props) {
  const [tgToken, setTgToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [configured, setConfigured] = useState(false);
  const [bridgeBotName, setBridgeBotName] = useState<string | null>(null);
  const [command, setCommand] = useState("");
  const [copied, setCopied] = useState(false);
  const [reconfigure, setReconfigure] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getTelegramBridge(instanceId)
      .then((res) => {
        if (cancelled) return;
        setConfigured(res.configured);
        setBridgeBotName(res.bridge_bot_name);
        setCommand(res.command || "");
      })
      .catch(() => { /* not fatal — show the empty form */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [instanceId]);

  async function handleSave() {
    const trimmed = tgToken.trim();
    if (!trimmed) { setError("请填写 Telegram bot token"); return; }
    setSaving(true);
    setError("");
    try {
      const res = await api.configureTelegramBridge(instanceId, trimmed);
      setConfigured(true);
      setBridgeBotName(res.bridge_bot_name);
      setCommand(res.command);
      setReconfigure(false);
      setTgToken("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "配置失败");
    } finally {
      setSaving(false);
    }
  }

  async function copyCmd() {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  }

  if (loading) {
    return <div className="text-xs text-gray-500">加载中…</div>;
  }

  // ─── Configured view: show the command + reconfigure button ───────
  if (configured && !reconfigure) {
    return (
      <div className="space-y-3">
        <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
          已配置 · 桥机器人: <code className="font-mono">{bridgeBotName}</code>
        </div>
        <div className="text-xs text-gray-400">
          在本机 <code className="font-mono text-gray-300">hxa-channel-daemon</code> 项目目录下运行：
        </div>
        <div className="bg-black/60 border border-gray-800 rounded px-3 py-3 font-mono text-xs text-gray-200 overflow-x-auto whitespace-pre-wrap break-all">
          {command}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={copyCmd}
            className="px-3 py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white"
          >
            {copied ? "已复制" : "复制命令"}
          </button>
          <button
            onClick={() => setReconfigure(true)}
            className="px-3 py-1.5 text-xs rounded bg-gray-800 hover:bg-gray-700 text-gray-300"
          >
            重新配置 / 更换 Token
          </button>
        </div>
        <div className="text-xs text-gray-500 border-t border-gray-800 pt-2 space-y-1">
          <div>运行命令后，将此 Telegram 机器人发消息会被转发给 <code className="font-mono text-blue-300">{agentName}</code>，它的回复会原路返回。</div>
          <div>桥身份与本机 @slock-ai/daemon 无关，可各自独立重启。</div>
        </div>
      </div>
    );
  }

  // ─── Form view: ask for a TG bot token ────────────────────────────
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        把 Telegram 机器人绑定到这个 Local Agent。我们会在 HXA 里为你自动创建一个独立的"桥"机器人身份，返回一条命令让你在本机运行。
      </p>
      <input
        type="text"
        value={tgToken}
        onChange={(e) => setTgToken(e.target.value)}
        placeholder="Bot Token（例如 123456:ABC…）"
        className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500"
        disabled={saving}
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={!tgToken.trim() || saving}
          className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md"
        >
          {saving ? "配置中…" : "生成命令"}
        </button>
        {reconfigure && (
          <button
            onClick={() => { setReconfigure(false); setError(""); setTgToken(""); }}
            disabled={saving}
            className="px-4 py-2 text-sm rounded-md bg-gray-800 hover:bg-gray-700 text-gray-300"
          >
            取消
          </button>
        )}
      </div>
    </div>
  );
}
