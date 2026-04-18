import { useEffect, useState } from "react";
import { api } from "../api";

interface Props {
  instanceId: string;
  agentName: string;
}

/**
 * WeChat bridge config for a Local Agent instance.
 *
 * Unlike Telegram, WeChat has no user-facing token to paste — login is
 * by scanning a QR on the user's own machine. So the only server-side
 * step is minting a bridge bot on HXA. Once that's done (a one-click
 * "生成命令" action) we hand over a ready command; the `npx` run takes
 * care of the rest (QR in terminal → personal WeChat scan).
 */
export function LocalAgentWeixinBridge({ instanceId, agentName }: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [configured, setConfigured] = useState(false);
  const [bridgeBotName, setBridgeBotName] = useState<string | null>(null);
  const [command, setCommand] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getWeixinBridge(instanceId)
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

  async function handleGenerate() {
    setSaving(true);
    setError("");
    try {
      const res = await api.configureWeixinBridge(instanceId);
      setConfigured(true);
      setBridgeBotName(res.bridge_bot_name);
      setCommand(res.command);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "生成失败");
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

  if (!configured) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-gray-500">
          把个人微信绑定到这个 Local Agent。点击下面的按钮生成一条命令，在本机运行后用微信扫码即可开始。
        </p>
        {error && <p className="text-xs text-red-400">{error}</p>}
        <button
          onClick={handleGenerate}
          disabled={saving}
          className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md"
        >
          {saving ? "生成中…" : "生成命令"}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
        已就绪 · 桥机器人: <code className="font-mono">{bridgeBotName}</code>
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
      </div>
      <div className="text-xs text-gray-500 border-t border-gray-800 pt-2 space-y-1">
        <div>首次运行命令时，终端会打印一张二维码，用个人微信扫一下就登录好了。Session 缓存在本机 <code className="font-mono">~/.hxa-channel-daemon/weixin/</code>。</div>
        <div>运行后，发到这个微信号的消息会被转发给 <code className="font-mono text-blue-300">{agentName}</code>，它的回复会原路返回（纯文本，附件暂不支持）。</div>
      </div>
    </div>
  );
}
