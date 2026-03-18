import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";

interface Settings {
  anthropic_base_url: string;
  anthropic_auth_token: string;
  hxa_org_id: string;
  hxa_org_secret: string;
}

export default function AdminSettingsPage() {
  const navigate = useNavigate();
  const [settings, setSettings] = useState<Settings>({
    anthropic_base_url: "",
    anthropic_auth_token: "",
    hxa_org_id: "",
    hxa_org_secret: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  useEffect(() => {
    api.get("/api/admin/settings")
      .then((r) => r.json())
      .then((data) => { setSettings(data); setLoading(false); })
      .catch(() => { setLoading(false); });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const r = await api.put("/api/admin/settings", settings);
      if (!r.ok) throw new Error((await r.json()).detail || "Save failed");
      setMessage({ type: "success", text: "已保存" });
    } catch (e: any) {
      setMessage({ type: "error", text: e.message });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="text-gray-400 text-sm p-6">Loading...</div>;

  const Field = ({
    label, field, type = "text", show, onToggle
  }: {
    label: string; field: keyof Settings; type?: string;
    show?: boolean; onToggle?: () => void;
  }) => (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <div className="relative">
        <input
          type={onToggle ? (show ? "text" : "password") : type}
          value={settings[field]}
          onChange={(e) => setSettings((s) => ({ ...s, [field]: e.target.value }))}
          className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-blue-500 font-mono pr-10"
        />
        {onToggle && (
          <button
            onClick={onToggle}
            className="absolute right-2 top-2 text-gray-400 hover:text-gray-200 text-xs"
          >
            {show ? "🙈" : "👁"}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="max-w-xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate("/admin")} className="text-gray-400 hover:text-gray-200 text-sm">← Back</button>
        <h1 className="text-lg font-semibold text-white">Admin Settings</h1>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
        <h2 className="text-sm font-medium text-gray-300">Anthropic / LLM</h2>
        <Field label="Base URL (ANTHROPIC_BASE_URL)" field="anthropic_base_url" />
        <Field
          label="Auth Token (ANTHROPIC_AUTH_TOKEN)"
          field="anthropic_auth_token"
          show={showToken}
          onToggle={() => setShowToken((v) => !v)}
        />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 space-y-4">
        <h2 className="text-sm font-medium text-gray-300">HXA Connect Organization</h2>
        <Field label="Org ID (HXA_CONNECT_ORG_ID)" field="hxa_org_id" />
        <Field
          label="Org Secret (HXA_CONNECT_ORG_SECRET)"
          field="hxa_org_secret"
          show={showSecret}
          onToggle={() => setShowSecret((v) => !v)}
        />
      </div>

      {message && (
        <div className={`text-sm px-3 py-2 rounded-md ${
          message.type === "success" ? "bg-green-900/40 text-green-300 border border-green-700" : "bg-red-900/40 text-red-300 border border-red-700"
        }`}>
          {message.text}
        </div>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-6 py-2 rounded-md"
      >
        {saving ? "Saving..." : "Save Settings"}
      </button>
    </div>
  );
}
