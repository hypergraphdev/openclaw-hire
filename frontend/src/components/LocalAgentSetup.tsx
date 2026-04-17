import { useEffect, useState } from "react";
import { api } from "../api";

interface Props {
  instanceId: string;
}

export function LocalAgentSetup({ instanceId }: Props) {
  const [command, setCommand] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [agentName, setAgentName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.daemonCommand(instanceId)
      .then((res) => {
        setCommand(res.command);
        setServerUrl(res.server_url);
        setApiKey(res.api_key);
        setAgentName(res.agent_name);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [instanceId]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const maskedKey = apiKey ? apiKey.slice(0, 6) + "…" + apiKey.slice(-4) : "";

  if (loading) {
    return <div className="text-sm text-gray-500 py-6">Loading daemon credentials…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-400 py-6">Failed to load daemon info: {error}</div>;
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
      <div>
        <div className="text-lg font-semibold text-gray-100 mb-1">Run your Local Agent</div>
        <div className="text-sm text-gray-400">
          Paste the command below into a terminal on your own machine. It will connect your local
          Claude Code (or other supported CLI) to this chat as bot{" "}
          <code className="text-blue-300">{agentName}</code>.
        </div>
      </div>

      <div className="bg-black/60 border border-gray-800 rounded px-3 py-3 font-mono text-xs text-gray-200 overflow-x-auto whitespace-pre-wrap break-all">
        {command}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={copy}
          className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-500 text-white"
        >
          {copied ? "Copied!" : "Copy command"}
        </button>
        <button
          onClick={() => setShowKey((v) => !v)}
          className="px-3 py-1.5 text-sm rounded bg-gray-800 hover:bg-gray-700 text-gray-200"
        >
          {showKey ? "Hide" : "Show"} API key
        </button>
      </div>

      {showKey && (
        <div className="text-xs text-gray-400 font-mono break-all">
          <div>server_url: <span className="text-gray-200">{serverUrl}</span></div>
          <div>api_key: <span className="text-gray-200">{apiKey}</span></div>
        </div>
      )}
      {!showKey && apiKey && (
        <div className="text-xs text-gray-500">API key: <span className="font-mono">{maskedKey}</span></div>
      )}

      <div className="text-xs text-gray-500 border-t border-gray-800 pt-3 space-y-1">
        <div>Requirements on your machine:</div>
        <ul className="list-disc list-inside space-y-0.5">
          <li>Node.js 18+</li>
          <li>Claude Code CLI (<code>claude</code>) already installed and authenticated</li>
          <li>The terminal running <code>npx ...</code> must stay open</li>
        </ul>
        <div className="pt-1">When you're connected, open the Chat tab to talk to your local agent.</div>
      </div>
    </div>
  );
}
