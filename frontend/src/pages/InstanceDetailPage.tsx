import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ChatPanel } from "../components/ChatPanel";
import { InstallTimeline } from "../components/InstallTimeline";
import { LocalAgentSetup } from "../components/LocalAgentSetup";
import { MonitorTab } from "../components/MonitorTab";
import { StatusPill } from "../components/StatusPill";
import { useAuth } from "../contexts/AuthContext";
import { useT } from "../contexts/LanguageContext";
import type { InstanceDetail, TelegramConfigResponse } from "../types";

const PRODUCT_LABELS: Record<string, string> = {
  openclaw: "OpenClaw",
  zylos: "Zylos",
  hermes: "Hermes Agent",
  local_agent: "Local Agent",
};

const PRODUCT_REPOS: Record<string, string> = {
  openclaw: "https://github.com/openclaw/openclaw",
  zylos: "https://github.com/zylos-ai/zylos-core",
  hermes: "https://github.com/NousResearch/hermes-agent",
  local_agent: "https://www.npmjs.com/package/@slock-ai/daemon",
};

// ── User Settings Card (per-user API keys) ──
function UserSettingsCard({ product }: { product: string }) {
  const t = useT();
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const isHermes = product === "hermes";

  useEffect(() => {
    api.getUserSettings().then(setSettings).catch(() => {});
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      await api.updateUserSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch { /* */ }
    finally { setSaving(false); }
  }

  const inputCls = "w-full bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-100 font-mono";

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <h2 className="text-sm font-medium text-gray-300">{t("userSettings.title")}</h2>
        <span className="text-xs text-gray-500">{expanded ? "▼" : "▶"}</span>
      </div>
      {expanded && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-gray-500">{t("userSettings.hint")}</p>

          {/* Anthropic fields — OpenClaw / Zylos only */}
          {!isHermes && (<>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Anthropic Base URL</label>
              <input value={settings.anthropic_base_url || ""} onChange={e => setSettings(s => ({ ...s, anthropic_base_url: e.target.value }))}
                className={inputCls} placeholder="https://api.anthropic.com" />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Anthropic Auth Token</label>
              <input type="password" value={settings.anthropic_auth_token || ""} onChange={e => setSettings(s => ({ ...s, anthropic_auth_token: e.target.value }))}
                className={inputCls} placeholder="sk-..." />
            </div>
          </>)}

          {/* OpenAI / OpenRouter fields — all products, label differs */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">{isHermes ? "OpenRouter Base URL" : "OpenAI Base URL"}</label>
            <input value={settings.openai_base_url || ""} onChange={e => setSettings(s => ({ ...s, openai_base_url: e.target.value }))}
              className={inputCls} placeholder={isHermes ? "https://openrouter.ai/api/v1" : "https://api.openai.com/v1"} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">{isHermes ? "OpenRouter API Key" : "OpenAI API Key"}</label>
            <input type="password" value={settings.openai_api_key || ""} onChange={e => setSettings(s => ({ ...s, openai_api_key: e.target.value }))}
              className={inputCls} placeholder="sk-..." />
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">{t("userSettings.defaultModel")}</label>
            <input value={settings.default_model || ""} onChange={e => setSettings(s => ({ ...s, default_model: e.target.value }))}
              className={inputCls} placeholder={isHermes ? "anthropic/claude-sonnet-4-5" : "claude-sonnet-4-5"} />
          </div>
          <button onClick={handleSave} disabled={saving}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md transition-colors">
            {saving ? t("common.loading") : saved ? t("adminSettings.saved") : t("common.save")}
          </button>
        </div>
      )}
    </div>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** localStorage key for install-progress collapsed state per instance */
function timelineCollapseKey(id: string) {
  return `hire_timeline_collapsed_${id}`;
}

export function InstanceDetailPage() {
  const { instanceId } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const t = useT();
  const [detail, setDetail] = useState<InstanceDetail | null>(null);
  const isOwner = !detail || detail.instance?.owner_id === user?.id;
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "stop" | "restart" | "uninstall" | "logs" | "upgrade">("");
  const [logs, setLogs] = useState("");
  const [error, setError] = useState("");
  const [upgradeResult, setUpgradeResult] = useState<{ ok: boolean; output: string } | null>(null);
  const [botToken, setBotToken] = useState("");
  const [configuring, setConfiguring] = useState(false);
  const [configResult, setConfigResult] = useState<TelegramConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");
  const [showTelegramReconfig, setShowTelegramReconfig] = useState(false);
  const [showTelegramHelp, setShowTelegramHelp] = useState(false);
  const [hxaConfiguring, setHxaConfiguring] = useState(false);
  const [hxaResult, setHxaResult] = useState<{ ok: boolean; message: string; agent_name?: string } | null>(null);
  const [hxaError, setHxaError] = useState("");
  // Self-check state
  type CheckItem = { name: string; label: string; status: string; detail: string; fixable: boolean };
  const [selfCheckResult, setSelfCheckResult] = useState<{ checks: CheckItem[]; overall: string; fixable_count: number } | null>(null);
  const [selfCheckLoading, setSelfCheckLoading] = useState(false);
  const [repairLoading, setRepairLoading] = useState(false);
  const [repairResult, setRepairResult] = useState<{ repairs: { name: string; action: string }[]; count: number } | null>(null);

  const [pluginRestarting, setPluginRestarting] = useState(false);
  const [pluginRestartMsg, setPluginRestartMsg] = useState("");
  const [weixinRestarting, setWeixinRestarting] = useState(false);
  const [weixinRestartMsg, setWeixinRestartMsg] = useState("");
  const [weixinLogging, setWeixinLogging] = useState(false);
  const [weixinLog, setWeixinLog] = useState("");
  const [weixinLogStatus, setWeixinLogStatus] = useState("");
  const weixinPollRef = useRef<number>(0);
  const [activeTab, setActiveTab] = useState<"info" | "chat" | "files" | "monitor">(() => {
    const hash = window.location.hash.replace("#", "");
    if (hash === "chat" || hash === "files" || hash === "monitor") return hash;
    return "info";
  });
  const [chatExpanded, setChatExpanded] = useState(() => localStorage.getItem("chat_expanded") === "1");
  const [monitorExpanded, setMonitorExpanded] = useState(() => localStorage.getItem("monitor_expanded") === "1");

  // File browser state
  type FileEntry = { name: string; type: "file" | "dir"; size: number | null; modified: string };
  const [filePath, setFilePath] = useState("/");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState("");

  // Sync hash with tab
  function switchTab(tab: "info" | "chat" | "files" | "monitor") {
    setActiveTab(tab);
    window.location.hash = tab === "info" ? "" : tab;
  }
  // Load files when tab is active or path changes
  useEffect(() => {
    if (activeTab !== "files" || !instanceId) return;
    setFilesLoading(true);
    setFilesError("");
    api.instanceFiles(instanceId, filePath)
      .then((res) => setFiles(res.files))
      .catch((err: unknown) => setFilesError(err instanceof Error ? err.message : "Failed to load files"))
      .finally(() => setFilesLoading(false));
  }, [activeTab, filePath, instanceId]);

  const [timelineCollapsed, setTimelineCollapsed] = useState(() => {
    if (!instanceId) return false;
    return localStorage.getItem(timelineCollapseKey(instanceId)) === "1";
  });

  const toggleTimeline = () => {
    setTimelineCollapsed((prev) => {
      const next = !prev;
      if (instanceId) localStorage.setItem(timelineCollapseKey(instanceId), next ? "1" : "0");
      return next;
    });
  };

  const fetchDetail = useCallback(() => {
    if (!instanceId) return Promise.resolve();
    return api.getInstance(instanceId).then(setDetail);
  }, [instanceId]);

  useEffect(() => {
    fetchDetail().finally(() => setLoading(false));

    const interval = setInterval(fetchDetail, 5_000);
    return () => clearInterval(interval);
  }, [fetchDetail]);

  useEffect(() => {
    if (detail?.instance?.is_telegram_configured) {
      setShowTelegramReconfig(false);
    }
  }, [detail?.instance?.is_telegram_configured]);

  async function handleInstall() {
    if (!instanceId) return;
    setError("");
    setInstalling(true);
    try {
      await api.startInstall(instanceId);
      await fetchDetail();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("detail.installFailed"));
    } finally {
      setInstalling(false);
    }
  }

  async function handleAction(action: "stop" | "restart" | "uninstall" | "logs" | "upgrade") {
    if (!instanceId) return;
    setError("");
    setActionLoading(action);
    try {
      if (action === "stop") await api.stopInstance(instanceId);
      if (action === "restart") await api.restartInstance(instanceId);
      if (action === "uninstall") await api.uninstallInstance(instanceId);
      if (action === "logs") {
        const res = await api.instanceLogs(instanceId, 300);
        setLogs(res.logs || "(no logs)");
      }
      if (action === "upgrade") {
        const res = await api.upgradeInstance(instanceId);
        setUpgradeResult(res);
      }
      await fetchDetail();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("detail.actionFailed", { action }));
    } finally {
      setActionLoading("");
    }
  }

  async function handleConfigure() {
    if (!instanceId || !botToken.trim()) return;
    setConfigError("");
    setConfiguring(true);
    try {
      const result = await api.configureTelegram(instanceId, botToken.trim());
      setConfigResult(result as unknown as TelegramConfigResponse);
      setBotToken("");
      setShowTelegramReconfig(false);
      await fetchDetail();
    } catch (err: unknown) {
      setConfigError(err instanceof Error ? err.message : t("telegram.configFailed"));
    } finally {
      setConfiguring(false);
    }
  }

  async function handleWeixinRestart() {
    if (!instanceId) return;
    setWeixinRestarting(true);
    setWeixinRestartMsg("");
    try {
      // Restart the container to reload weixin plugin
      await api.restartInstance(instanceId);
      setWeixinRestartMsg(t("weixin.restarted"));
      setTimeout(() => fetchDetail(), 3000);
    } catch (err: unknown) {
      setWeixinRestartMsg(`${err instanceof Error ? err.message : t("weixin.restartFailed")}`);
    }
    setWeixinRestarting(false);
  }

  async function handleWeixinLogin() {
    if (!instanceId) return;
    setWeixinLogging(true);
    setWeixinLog("");
    setWeixinLogStatus("");
    try {
      await api.weixinLogin(instanceId);
      // Poll log for QR code
      const poll = async () => {
        try {
          const data = await api.weixinLoginLog(instanceId);
          setWeixinLog(data.log);
          setWeixinLogStatus(data.status);
          if (data.status === "waiting" || data.status === "qr_ready") {
            weixinPollRef.current = window.setTimeout(poll, 1000);
          }
        } catch { /* */ }
      };
      poll();
    } catch (err: unknown) {
      setWeixinLog(`ERROR: ${err instanceof Error ? err.message : "Failed"}`);
      setWeixinLogStatus("failed");
    }
  }

  function closeWeixinLog() {
    clearTimeout(weixinPollRef.current);
    setWeixinLogging(false);
    setWeixinLog("");
    setWeixinLogStatus("");
  }

  async function handleJoinOrg() {
    if (!instanceId) return;
    setHxaError("");
    setHxaConfiguring(true);
    try {
      const result = await api.configureHxa(instanceId);
      setHxaResult(result);
      await fetchDetail();
    } catch (err: unknown) {
      setHxaError(err instanceof Error ? err.message : t("org.configFailed"));
    } finally {
      setHxaConfiguring(false);
    }
  }

  if (loading) {
    return <div className="text-gray-500 text-sm">{t("detail.loading")}</div>;
  }

  if (!detail) {
    return (
      <div className="text-gray-500 text-sm">
        {t("detail.notFound")} <Link to="/instances" className="text-blue-400">{t("detail.backToInstances")}</Link>
      </div>
    );
  }

  const { instance, install_timeline, config } = detail;
  const apiKeyConfigured = (detail as Record<string, unknown>).api_key_configured !== false;
  const containerRunning = (detail as Record<string, unknown>).container_running === true;
  const isInstalling = ["pulling", "configuring", "starting"].includes(instance.install_state);
  const canInstall = instance.install_state === "idle" || (instance.install_state === "failed" && !containerRunning);
  const canSelfCheck = !!instance.compose_project;

  return (
    <div>
      {/* Breadcrumb */}
      <div className="text-xs text-gray-500 mb-5">
        <Link to="/instances" className="hover:text-gray-300">{t("nav.instances")}</Link>
        <span className="mx-2">›</span>
        <span className="text-gray-300">{instance.name}</span>
      </div>

      {/* Header */}
      <div className="mb-6 space-y-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold text-white">{instance.name}</h1>
            <StatusPill state={instance.install_state} size="md" />
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {PRODUCT_LABELS[instance.product] ?? instance.product} ·{" "}
            <span className="font-mono text-xs">{instance.id}</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canInstall && (
            <button
              onClick={handleInstall}
              disabled={installing}
              className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md transition-colors"
            >
              {installing ? t("detail.starting") : instance.install_state === "failed" ? t("detail.retryInstall") : t("detail.install")}
            </button>
          )}
          {canSelfCheck && (
            <button
              onClick={async () => {
                setSelfCheckLoading(true);
                setRepairResult(null);
                try {
                  const res = await api.selfCheck(instanceId!);
                  setSelfCheckResult(res);
                } catch (err: unknown) {
                  setError(err instanceof Error ? err.message : "Self-check failed");
                } finally {
                  setSelfCheckLoading(false);
                }
              }}
              disabled={selfCheckLoading}
              className="bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md transition-colors"
            >
              {selfCheckLoading ? t("detail.checking") : t("detail.selfCheck")}
            </button>
          )}
          <button onClick={() => handleAction("logs")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.logs")}</button>
          <button onClick={() => handleAction("stop")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.stop")}</button>
          <button onClick={() => handleAction("restart")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.restart")}</button>
          <button onClick={() => handleAction("uninstall")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.uninstall")}</button>
          {instance.product === "openclaw" && (
            <button onClick={() => handleAction("upgrade")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">
              {actionLoading === "upgrade" ? t("detail.upgrading") : t("detail.upgrade")}
            </button>
          )}
        </div>

        {upgradeResult && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setUpgradeResult(null)}>
            <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-2xl mx-4 max-h-[70vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold text-white">{t("detail.upgrade")}</h3>
                <span className={`text-xs px-2 py-1 rounded-full ${upgradeResult.ok ? "bg-green-900/40 text-green-400" : "bg-red-900/40 text-red-400"}`}>
                  {upgradeResult.ok ? "Success" : "Failed"}
                </span>
              </div>
              <pre className="flex-1 overflow-auto bg-gray-950 rounded-lg p-4 text-xs text-green-400 font-mono whitespace-pre-wrap">{upgradeResult.output}</pre>
              <button onClick={() => setUpgradeResult(null)} className="mt-3 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm py-2 rounded-lg">Close</button>
            </div>
          </div>
        )}

        {/* Self-check result modal */}
        {selfCheckResult && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => { setSelfCheckResult(null); setRepairResult(null); }}>
            <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-xl mx-4 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">{t("detail.selfCheckTitle")}</h3>
                <span className={`text-xs px-2 py-1 rounded-full ${
                  selfCheckResult.overall === "ok" ? "bg-green-900/40 text-green-400" :
                  selfCheckResult.overall === "fixable" ? "bg-yellow-900/40 text-yellow-400" :
                  "bg-red-900/40 text-red-400"
                }`}>
                  {selfCheckResult.overall === "ok" ? t("detail.allGood") :
                   selfCheckResult.overall === "fixable" ? t("detail.fixable", { count: selfCheckResult.fixable_count }) :
                   t("detail.needsAttention")}
                </span>
              </div>
              <div className="flex-1 overflow-auto space-y-2">
                {selfCheckResult.checks.map((c) => (
                  <div key={c.name} className="flex items-start gap-2 text-sm bg-gray-800/50 rounded-lg px-3 py-2">
                    <span className="mt-0.5 text-base">
                      {c.status === "ok" ? "✅" : c.fixable ? "🔧" : "❌"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-gray-200 font-medium">{c.label}</div>
                      <div className="text-gray-400 text-xs break-words">{c.detail}</div>
                    </div>
                  </div>
                ))}
              </div>
              {repairResult && (
                <div className="mt-3 p-3 bg-green-900/20 border border-green-700 rounded-lg text-xs text-green-300 space-y-1">
                  <div className="font-medium">✅ {t("detail.repairDone", { count: repairResult.count })}</div>
                  {repairResult.repairs.map((r, i) => (
                    <div key={i}>• {r.action}</div>
                  ))}
                </div>
              )}
              <div className="flex gap-2 mt-4">
                {selfCheckResult.fixable_count > 0 && !repairResult && (
                  <button
                    onClick={async () => {
                      setRepairLoading(true);
                      try {
                        const res = await api.selfCheckRepair(instanceId!);
                        setRepairResult(res);
                        // Re-run check to show updated status
                        const check2 = await api.selfCheck(instanceId!);
                        setSelfCheckResult(check2);
                        await fetchDetail();
                      } catch (err: unknown) {
                        setError(err instanceof Error ? err.message : "Repair failed");
                      } finally {
                        setRepairLoading(false);
                      }
                    }}
                    disabled={repairLoading}
                    className="flex-1 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white text-sm py-2 rounded-lg"
                  >
                    {repairLoading ? t("detail.repairing") : t("detail.repairAll")}
                  </button>
                )}
                <button onClick={() => { setSelfCheckResult(null); setRepairResult(null); fetchDetail(); }} className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm py-2 rounded-lg">
                  {t("common.close")}
                </button>
              </div>
            </div>
          </div>
        )}

        {isInstalling && (
          <div className="flex items-center gap-2 text-blue-400 text-sm">
            <span className="inline-block h-2 w-2 rounded-full bg-blue-400 animate-pulse" />
            {t("detail.installing")}
          </div>
        )}

        {instance.install_state === "running" && (
          <div className="flex items-center gap-2 text-green-400 text-sm font-medium">
            <span className="inline-block h-2 w-2 rounded-full bg-green-400" />
            {t("detail.runningStatus")}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-5 p-3 bg-red-900/40 border border-red-700 rounded-md text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className={`grid grid-cols-1 gap-5 ${chatExpanded || monitorExpanded ? "" : "lg:grid-cols-3"}`}>
        {/* Left panel: Install timeline + Docker logs */}
        {!chatExpanded && (
          <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-5">
            {/* Collapsible install progress */}
            <button
              onClick={toggleTimeline}
              className="w-full flex items-center justify-between mb-4 group"
            >
              <h2 className="text-sm font-medium text-gray-300">{t("detail.installProgress")}</h2>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className={`h-4 w-4 text-gray-500 group-hover:text-gray-300 transition-transform ${timelineCollapsed ? "-rotate-90" : ""}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {!timelineCollapsed && <InstallTimeline events={install_timeline} />}

            <div className={timelineCollapsed ? "" : "mt-6"}>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-medium text-gray-300">{t("detail.dockerLogs")}</h3>
                {actionLoading === "logs" ? <span className="text-xs text-gray-500">{t("detail.loadingLogs")}</span> : null}
              </div>
              <pre className="bg-gray-950 border border-gray-800 rounded-md p-3 text-xs text-gray-300 overflow-auto max-h-80 whitespace-pre-wrap">
                {logs || t("detail.logsPlaceholder")}
              </pre>
            </div>
          </div>
        )}

        {/* Right column: tabs + content */}
        <div className={`space-y-4 ${chatExpanded || monitorExpanded ? "col-span-full" : ""}`}>
          {/* Tab bar */}
          {detail?.config?.agent_name && (
            <div className="flex border-b border-gray-700">
              <button
                onClick={() => switchTab("info")}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === "info"
                    ? "text-blue-400 border-b-2 border-blue-400"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {t("chat.infoTab")}
              </button>
              <button
                onClick={() => switchTab("chat")}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === "chat"
                    ? "text-blue-400 border-b-2 border-blue-400"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {t("chat.tab")}
              </button>
              <button
                onClick={() => { switchTab("files"); setFilePath("/"); }}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === "files"
                    ? "text-blue-400 border-b-2 border-blue-400"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {t("files.tab")}
              </button>
              <button
                onClick={() => switchTab("monitor")}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activeTab === "monitor"
                    ? "text-blue-400 border-b-2 border-blue-400"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                监控
              </button>
            </div>
          )}

          {/* Chat Panel */}
          {activeTab === "chat" && instanceId && (
            isOwner && detail?.config?.agent_name ? (
              <>
                {!apiKeyConfigured && (
                  <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg px-4 py-3 mb-3 text-sm text-yellow-300">
                    ⚠️ {t("chat.noApiKey")}
                    <button onClick={() => navigate("/admin#settings")} className="ml-2 text-blue-400 hover:text-blue-300 underline">{t("chat.goSettings")}</button>
                  </div>
                )}
                <ChatPanel
                  instanceId={instanceId}
                  agentName={detail.config.agent_name}
                  expanded={chatExpanded}
                  onToggleExpand={() => setChatExpanded((v) => { const n = !v; localStorage.setItem("chat_expanded", n ? "1" : "0"); return n; })}
                />
              </>
            ) : (
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-10 text-center">
                <div className="text-gray-600 text-3xl mb-3">💬</div>
                <div className="text-gray-400 text-sm">{isOwner ? "请先配置 HXA 组织后再使用聊天" : "管理员模式下聊天不可用"}</div>
              </div>
            )
          )}

          {/* Files Tab */}
          {activeTab === "files" && instanceId && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              {/* Breadcrumb */}
              <div className="flex items-center gap-1 text-sm text-gray-400 mb-3 flex-wrap">
                <button onClick={() => setFilePath("/")} className="hover:text-blue-400">/</button>
                {filePath !== "/" && filePath.split("/").filter(Boolean).map((seg, i, arr) => (
                  <span key={i} className="flex items-center gap-1">
                    <span className="text-gray-600">/</span>
                    <button
                      onClick={() => setFilePath("/" + arr.slice(0, i + 1).join("/"))}
                      className={i === arr.length - 1 ? "text-gray-200" : "hover:text-blue-400"}
                    >
                      {seg}
                    </button>
                  </span>
                ))}
              </div>

              {filesError && <div className="text-sm text-red-400 mb-2">{filesError}</div>}

              {filesLoading ? (
                <div className="text-sm text-gray-500 py-8 text-center">{t("files.loading")}</div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800 text-left">
                      <th className="py-2 px-2 text-gray-400 font-medium">{t("files.name")}</th>
                      <th className="py-2 px-2 text-gray-400 font-medium text-right">{t("files.size")}</th>
                      <th className="py-2 px-2 text-gray-400 font-medium">{t("files.modified")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filePath !== "/" && (
                      <tr
                        className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                        onClick={() => setFilePath("/" + filePath.split("/").filter(Boolean).slice(0, -1).join("/"))}
                      >
                        <td className="py-1.5 px-2 text-gray-400" colSpan={3}>
                          <span className="mr-2">{"📁"}</span> ..
                        </td>
                      </tr>
                    )}
                    {files.map((f) => (
                      <tr
                        key={f.name}
                        className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
                        onClick={() => {
                          if (f.type === "dir") {
                            setFilePath((filePath === "/" ? "/" : filePath + "/") + f.name);
                          } else {
                            // Download with auth token via fetch + Blob
                            const dlPath = (filePath === "/" ? "/" : filePath + "/") + f.name;
                            const token = localStorage.getItem("openclaw_token") || "";
                            const base = import.meta.env.VITE_API_BASE || "";
                            fetch(`${base}/api/instances/${instanceId}/files/download?path=${encodeURIComponent(dlPath)}`, {
                              headers: { Authorization: `Bearer ${token}` },
                            }).then(r => {
                              if (!r.ok) throw new Error("Download failed");
                              return r.blob();
                            }).then(blob => {
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement("a");
                              a.href = url;
                              a.download = f.name;
                              a.click();
                              URL.revokeObjectURL(url);
                            }).catch(() => alert("Download failed"));
                          }
                        }}
                      >
                        <td className="py-1.5 px-2 text-gray-200">
                          <span className="mr-2">{f.type === "dir" ? "📁" : "📄"}</span>
                          {f.name}
                        </td>
                        <td className="py-1.5 px-2 text-gray-500 text-right text-xs font-mono">
                          {f.type === "file" && f.size != null
                            ? f.size > 1048576 ? `${(f.size / 1048576).toFixed(1)} MB`
                              : f.size > 1024 ? `${(f.size / 1024).toFixed(1)} KB`
                              : `${f.size} B`
                            : ""}
                        </td>
                        <td className="py-1.5 px-2 text-gray-500 text-xs">{f.modified}</td>
                      </tr>
                    ))}
                    {files.length === 0 && !filesLoading && (
                      <tr><td colSpan={3} className="py-4 text-center text-gray-600">{t("files.empty")}</td></tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Monitor Tab */}
          {activeTab === "monitor" && instanceId && (
            <div className={`bg-gray-900 border border-gray-800 rounded-lg overflow-hidden ${monitorExpanded ? "h-[calc(100vh-120px)]" : "h-[600px]"}`}>
              <div className="h-full overflow-auto p-4">
                <div className="flex justify-end mb-2">
                  <button onClick={() => { setMonitorExpanded((v) => { const n = !v; localStorage.setItem("monitor_expanded", n ? "1" : "0"); return n; }); }}
                    className="text-gray-500 hover:text-gray-300 p-1" title={monitorExpanded ? "收起" : "展开"}>
                    {monitorExpanded ? (
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9H4.5M9 9L3.75 3.75M9 15v4.5M9 15H4.5M9 15l-5.25 5.25M15 9h4.5M15 9V4.5M15 9l5.25-5.25M15 15h4.5M15 15v4.5m0-4.5l5.25 5.25" /></svg>
                    ) : (
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" /></svg>
                    )}
                  </button>
                </div>
                <MonitorTab instanceId={instanceId} />
              </div>
            </div>
          )}

          {/* Info cards */}
          {activeTab === "info" && (<>
          {instance.product === "local_agent" && isOwner && (
            <LocalAgentSetup instanceId={instance.id} />
          )}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">{t("detail.instanceDetails")}</h2>
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-xs text-gray-500">{t("detail.product")}</dt>
                <dd className="text-gray-300 capitalize">{PRODUCT_LABELS[instance.product] ?? instance.product}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">{t("detail.instanceId")}</dt>
                <dd className="text-gray-300 text-xs font-mono break-all">{instance.id}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">{t("detail.status")}</dt>
                <dd><StatusPill state={instance.status} /></dd>
              </div>
              {/* Web Console link removed - users interact via Telegram */}
              {instance.web_console_port && (
                <div>
                  <dt className="text-xs text-gray-500">{t("detail.gatewayPort")}</dt>
                  <dd className="text-gray-400 font-mono text-xs">{instance.web_console_port}</dd>
                </div>
              )}
              {instance.http_port && (
                <div>
                  <dt className="text-xs text-gray-500">{t("detail.bridgePort")}</dt>
                  <dd className="text-gray-400 font-mono text-xs">{instance.http_port}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-gray-500">{t("detail.deployedAt")}</dt>
                <dd className="text-gray-300 text-xs">{formatDate(instance.created_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">{t("detail.lastUpdated")}</dt>
                <dd className="text-gray-300 text-xs">{formatDate(instance.updated_at)}</dd>
              </div>
            </dl>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">{t("detail.repository")}</h2>
            <a
              href={PRODUCT_REPOS[instance.product] ?? instance.repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 break-all"
            >
              {instance.repo_url}
            </a>
          </div>

          {/* WeChat Integration */}
          {(instance.product === "openclaw" || instance.product === "zylos" || instance.product === "hermes") && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <h2 className="text-sm font-medium text-gray-300 mb-3">{t("weixin.title")}</h2>
              {(detail as Record<string, unknown>)?.is_weixin_installed ? (
                <div className="space-y-3">
                  <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
                    {t("weixin.installed")}
                  </div>
                  <div className="flex items-center gap-4">
                    <button onClick={handleWeixinLogin} className="text-xs text-blue-400 hover:text-blue-300 underline">
                      {t("weixin.rebind")}
                    </button>
                    <button onClick={handleWeixinRestart} disabled={weixinRestarting} className="text-xs text-gray-400 hover:text-gray-200 underline disabled:opacity-50">
                      {weixinRestarting ? t("weixin.restarting") : t("weixin.restartPlugin")}
                    </button>
                  </div>
                  {weixinRestartMsg && <p className={`text-xs ${weixinRestartMsg.startsWith("✅") ? "text-green-400" : "text-red-400"}`}>{weixinRestartMsg}</p>}
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-xs text-gray-500">{t("weixin.desc")}</p>
                  <button
                    onClick={() => navigate("/marketplace")}
                    className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-md"
                  >
                    {t("weixin.goMarketplace")}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* WeChat Login QR Modal */}
          {weixinLogging && (
            <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
              <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-4xl mx-4 max-h-[90vh] flex flex-col">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-lg font-semibold text-white">{t("weixin.qrLogin")}</h3>
                  <span className={`text-xs px-2 py-1 rounded-full ${
                    weixinLogStatus === "success" ? "bg-green-900/40 text-green-400" :
                    weixinLogStatus === "failed" ? "bg-red-900/40 text-red-400" :
                    "bg-yellow-900/40 text-yellow-400"
                  }`}>
                    {weixinLogStatus === "success" ? t("weixin.bindSuccess") :
                     weixinLogStatus === "failed" ? t("weixin.bindFailed") : t("weixin.waitingScan")}
                  </span>
                </div>
                <pre className="flex-1 overflow-auto bg-gray-950 rounded-lg p-4 text-xs text-green-400 font-mono whitespace-pre">
                  {weixinLog || t("weixin.starting")}
                </pre>
                <button onClick={closeWeixinLog} className="mt-3 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm py-2 rounded-lg">
                  {weixinLogStatus === "waiting" || weixinLogStatus === "qr_ready" ? t("weixin.closeBackground") : t("common.close")}
                </button>
              </div>
            </div>
          )}

          {/* Join Organization (HXA Connect) */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">{t("org.title")}</h2>
            <div className="space-y-3">
              {(hxaResult?.ok || config?.agent_name) && (
                <>
                  <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
                    {hxaResult?.message || t("org.alreadyConnected")}{config?.org_name ? ` — ${config.org_name}` : ""}
                  </div>
                  <dl className="space-y-1 text-xs">
                    <div><dt className="text-gray-500">{t("org.agentName")}</dt><dd className="text-gray-300 font-mono">{hxaResult?.agent_name || config?.agent_name || instance.agent_name || "-"}</dd></div>
                    <div><dt className="text-gray-500">{t("org.orgId")}</dt><dd className="text-gray-300 font-mono break-all">{config?.org_id || "-"}</dd></div>
                    <div><dt className="text-gray-500">{t("org.hubUrl")}</dt><dd className="text-gray-300 break-all">{config?.hub_url || "-"}</dd></div>
                  </dl>
                  <button
                    onClick={handleJoinOrg}
                    disabled={!instance.compose_project || hxaConfiguring}
                    className="text-xs text-gray-500 hover:text-gray-300 underline"
                  >
                    {hxaConfiguring ? t("org.reconnecting") : t("org.reconnect")}
                  </button>
                  <button
                    onClick={async () => {
                      if (!instanceId) return;
                      setPluginRestarting(true);
                      setPluginRestartMsg("");
                      try {
                        const res = await api.restartPlugins(instanceId);
                        setPluginRestartMsg(res.ok ? t("org.pluginRestarted") : res.detail);
                        if (res.ok) setTimeout(() => fetchDetail(), 5000);
                      } catch (err: unknown) {
                        setPluginRestartMsg(err instanceof Error ? err.message : t("org.pluginRestartFailed"));
                      } finally {
                        setPluginRestarting(false);
                      }
                    }}
                    disabled={pluginRestarting}
                    className="text-xs text-gray-500 hover:text-gray-300 underline ml-3"
                  >
                    {pluginRestarting ? t("org.pluginRestarting") : t("org.pluginRestart")}
                  </button>
                  {pluginRestartMsg && (
                    <p className="text-xs text-yellow-400 mt-1">{pluginRestartMsg}</p>
                  )}
                </>
              )}
              {!hxaResult?.ok && !config?.agent_name && (
                <>
                  {hxaError && (
                    <p className="text-xs text-red-400">{hxaError}</p>
                  )}
                  <p className="text-xs text-gray-500">
                    {t("org.connect")}
                  </p>
                  <button
                    onClick={handleJoinOrg}
                    disabled={!instance.compose_project || hxaConfiguring}
                    className="w-full bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md transition-colors"
                  >
                    {hxaConfiguring ? t("org.connecting") : t("org.connectButton")}
                  </button>
                  {!instance.compose_project && (
                    <p className="text-xs text-gray-600">{t("detail.installFirst")}</p>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Telegram Integration */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <div className="relative">
              <div className="flex items-center gap-2 mb-3">
                <h2 className="text-sm font-medium text-gray-300">{t("telegram.title")}</h2>
                <button
                  onClick={() => setShowTelegramHelp((v) => !v)}
                  className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-gray-200 text-xs flex items-center justify-center transition-colors"
                  title={t("telegram.help.title")}
                >
                  ?
                </button>
              </div>
              {showTelegramHelp && (
                <div className="absolute z-10 top-8 left-0 w-72 bg-gray-800 border border-gray-700 rounded-lg p-4 shadow-lg">
                  <p className="text-xs text-gray-300 font-medium mb-2">{t("telegram.help.title")}</p>
                  <ol className="text-xs text-gray-400 space-y-1.5 list-decimal list-inside">
                    <li>{t("telegram.help.step1")}</li>
                    <li>{t("telegram.help.step2")}</li>
                    <li>{t("telegram.help.step3")}</li>
                    <li>{t("telegram.help.step4")}</li>
                  </ol>
                  <button
                    onClick={() => setShowTelegramHelp(false)}
                    className="mt-3 text-xs text-gray-500 hover:text-gray-300"
                  >
                    {t("common.close")}
                  </button>
                </div>
              )}
            </div>
            <div className="space-y-3">
              {(configResult || instance.is_telegram_configured) && !showTelegramReconfig && (
                <>
                  <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
                    {configResult?.message || t("telegram.alreadyConfigured")}
                    {!configResult && instance.telegram_token_hint && (
                      <span className="ml-2 text-green-400/70">
                        (Token: ****{instance.telegram_token_hint})
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => {
                      setConfigResult(null);
                      setConfigError("");
                      setShowTelegramReconfig(true);
                    }}
                    className="text-xs text-gray-500 hover:text-gray-300 underline"
                  >
                    {t("telegram.reconfigure")}
                  </button>
                  <button
                    onClick={async () => {
                      if (!instanceId) return;
                      setPluginRestarting(true);
                      setPluginRestartMsg("");
                      try {
                        const res = await api.restartPlugins(instanceId);
                        setPluginRestartMsg(res.ok ? t("telegram.restarted") : res.detail);
                        if (res.ok) setTimeout(() => fetchDetail(), 5000);
                      } catch (err: unknown) {
                        setPluginRestartMsg(err instanceof Error ? err.message : t("telegram.restartFailed"));
                      } finally {
                        setPluginRestarting(false);
                      }
                    }}
                    disabled={pluginRestarting}
                    className="text-xs text-gray-500 hover:text-gray-300 underline ml-3"
                  >
                    {pluginRestarting ? t("telegram.restarting") : t("telegram.restartPlugin")}
                  </button>
                  {pluginRestartMsg && (
                    <p className="text-xs text-yellow-400 mt-1">{pluginRestartMsg}</p>
                  )}
                </>
              )}

              {(!instance.is_telegram_configured || showTelegramReconfig) && !configResult && (
                <>
                  <p className="text-xs text-gray-500">{t("telegram.connect")}</p>
                  <input
                    type="text"
                    placeholder={t("telegram.tokenPlaceholder")}
                    value={botToken}
                    onChange={(e) => setBotToken(e.target.value)}
                    disabled={!instance.compose_project || configuring}
                    className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 disabled:opacity-none focus:outline-none focus:border-gray-500"
                  />
                  {configError && (
                    <p className="text-xs text-red-400">{configError}</p>
                  )}
                  <button
                    onClick={handleConfigure}
                    disabled={!botToken.trim() || !instance.compose_project || configuring}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md transition-colors"
                  >
                    {configuring ? t("telegram.configuring") : t("telegram.configure")}
                  </button>
                  {!instance.compose_project && (
                    <p className="text-xs text-gray-600">{t("detail.installFirstConfig")}</p>
                  )}
                </>
              )}
            </div>
          </div>

          {/* User Settings (API Keys) — Local Agent uses the user's own machine credentials */}
          {instance.product !== "local_agent" && (
            <UserSettingsCard product={instance.product} />
          )}

          </>)}
        </div>
      </div>
    </div>
  );
}
