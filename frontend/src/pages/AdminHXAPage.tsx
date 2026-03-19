import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

interface HXAConfig {
  org_id: string;
  org_secret: string;
  hub_url: string;
}

interface Agent {
  instance_id: string;
  instance_name: string;
  product: string;
  agent_name: string;
  agent_token_prefix: string;
  agent_token: string;
  agent_id: string;
}

export default function AdminHXAPage() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<HXAConfig | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSecret, setShowSecret] = useState(false);
  const [revealedTokens, setRevealedTokens] = useState<Set<string>>(new Set());

  // Hub URL editing
  const [editingHubUrl, setEditingHubUrl] = useState(false);
  const [hubUrlDraft, setHubUrlDraft] = useState("");
  const [hubUrlSaving, setHubUrlSaving] = useState(false);

  // Agent name editing
  const [editingAgentId, setEditingAgentId] = useState<string>("");
  const [agentNameDraft, setAgentNameDraft] = useState("");
  const [agentNameSaving, setAgentNameSaving] = useState(false);

  useEffect(() => {
    Promise.all([
      api.get("/api/admin/hxa/config").then((r) => r.json()),
      api.get("/api/admin/hxa/agents").then((r) => r.json()),
    ]).then(([cfg, agentsData]) => {
      setConfig(cfg);
      setAgents(agentsData.agents || []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const toggleToken = (id: string) => {
    setRevealedTokens((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const copy = (text: string) => navigator.clipboard?.writeText(text);

  async function saveHubUrl() {
    const url = hubUrlDraft.trim().replace(/\/+$/, "");
    if (!url) return;
    setHubUrlSaving(true);
    try {
      await api.put("/api/admin/hxa/config/hub-url", { hub_url: url });
      setConfig((prev) => prev ? { ...prev, hub_url: url } : prev);
      setEditingHubUrl(false);
    } finally {
      setHubUrlSaving(false);
    }
  }

  async function saveAgentName(instanceId: string) {
    const name = agentNameDraft.trim();
    if (!name) return;
    setAgentNameSaving(true);
    try {
      await api.put(`/api/admin/hxa/agents/${instanceId}/name`, { agent_name: name });
      setAgents((prev) => prev.map((a) => a.instance_id === instanceId ? { ...a, agent_name: name } : a));
      setEditingAgentId("");
    } finally {
      setAgentNameSaving(false);
    }
  }

  if (loading) return <div className="text-gray-400 text-sm p-6">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate("/admin")} className="text-gray-400 hover:text-gray-200 text-sm">← Back</button>
        <h1 className="text-lg font-semibold text-white">HXA Organization</h1>
      </div>

      {/* Org Config */}
      {config && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-3">
          <h2 className="text-sm font-medium text-gray-300">Organization Config</h2>

          {/* Hub URL - editable */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-20">Hub URL</span>
            {editingHubUrl ? (
              <>
                <input
                  type="text"
                  value={hubUrlDraft}
                  onChange={(e) => setHubUrlDraft(e.target.value)}
                  className="text-xs font-mono text-gray-200 bg-gray-800 border border-gray-700 px-2 py-1 rounded flex-1 focus:outline-none focus:border-gray-500"
                  onKeyDown={(e) => e.key === "Enter" && saveHubUrl()}
                />
                <button onClick={saveHubUrl} disabled={hubUrlSaving} className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50">
                  {hubUrlSaving ? "..." : "Save"}
                </button>
                <button onClick={() => setEditingHubUrl(false)} className="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
              </>
            ) : (
              <>
                <code className="text-xs font-mono text-gray-200 bg-gray-800 px-2 py-1 rounded flex-1">{config.hub_url}</code>
                <button onClick={() => { setHubUrlDraft(config.hub_url); setEditingHubUrl(true); }} className="text-xs text-gray-500 hover:text-gray-300">Edit</button>
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-20">Org ID</span>
            <code className="text-xs font-mono text-gray-200 bg-gray-800 px-2 py-1 rounded flex-1">{config.org_id}</code>
            <button onClick={() => copy(config.org_id)} className="text-xs text-gray-500 hover:text-gray-300">Copy</button>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-20">Org Secret</span>
            <code className="text-xs font-mono text-gray-200 bg-gray-800 px-2 py-1 rounded flex-1">
              {showSecret ? config.org_secret : "••••••••••••••••"}
            </code>
            <button onClick={() => setShowSecret((v) => !v)} className="text-xs text-gray-500 hover:text-gray-300">
              {showSecret ? "Hide" : "Show"}
            </button>
            {showSecret && (
              <button onClick={() => copy(config.org_secret)} className="text-xs text-gray-500 hover:text-gray-300">Copy</button>
            )}
          </div>
        </div>
      )}

      {/* Agent Tokens */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-300 mb-3">Agent Tokens ({agents.length})</h2>
        {agents.length === 0 ? (
          <p className="text-gray-500 text-sm">No agents found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 pr-4">Instance</th>
                  <th className="text-left py-2 pr-4">Product</th>
                  <th className="text-left py-2 pr-4">Agent Name</th>
                  <th className="text-left py-2 pr-4">Token</th>
                  <th className="text-left py-2"></th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a.instance_id} className="border-b border-gray-800/50">
                    <td className="py-2 pr-4 text-gray-300">{a.instance_name}</td>
                    <td className="py-2 pr-4 text-gray-400 capitalize">{a.product}</td>
                    <td className="py-2 pr-4 text-gray-300 font-mono">
                      {editingAgentId === a.instance_id ? (
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            value={agentNameDraft}
                            onChange={(e) => setAgentNameDraft(e.target.value)}
                            className="text-xs font-mono text-gray-200 bg-gray-800 border border-gray-700 px-1 py-0.5 rounded w-36 focus:outline-none focus:border-gray-500"
                            onKeyDown={(e) => e.key === "Enter" && saveAgentName(a.instance_id)}
                          />
                          <button onClick={() => saveAgentName(a.instance_id)} disabled={agentNameSaving} className="text-blue-400 hover:text-blue-300 disabled:opacity-50">
                            {agentNameSaving ? "..." : "OK"}
                          </button>
                          <button onClick={() => setEditingAgentId("")} className="text-gray-500 hover:text-gray-300">X</button>
                        </div>
                      ) : (
                        <span className="group">
                          {a.agent_name || "-"}
                          <button
                            onClick={() => { setAgentNameDraft(a.agent_name); setEditingAgentId(a.instance_id); }}
                            className="ml-2 text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            Edit
                          </button>
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4 font-mono text-gray-400">
                      {revealedTokens.has(a.instance_id) ? a.agent_token : a.agent_token_prefix || "-"}
                    </td>
                    <td className="py-2 flex gap-2">
                      {a.agent_token && (
                        <>
                          <button onClick={() => toggleToken(a.instance_id)} className="text-gray-500 hover:text-gray-300">
                            {revealedTokens.has(a.instance_id) ? "Hide" : "Show"}
                          </button>
                          {revealedTokens.has(a.instance_id) && (
                            <button onClick={() => copy(a.agent_token)} className="text-gray-500 hover:text-gray-300">Copy</button>
                          )}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
