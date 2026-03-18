import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { InstallTimeline } from "../components/InstallTimeline";
import { StatusPill } from "../components/StatusPill";
import type { InstanceDetail, TelegramConfigResponse } from "../types";

const PRODUCT_LABELS: Record<string, string> = {
  openclaw: "OpenClaw",
  zylos: "Zylos",
};

const PRODUCT_REPOS: Record<string, string> = {
  openclaw: "https://github.com/openclaw/openclaw",
  zylos: "https://github.com/zylos-ai/zylos-core",
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function InstanceDetailPage() {
  const { instanceId } = useParams<{ instanceId: string }>();
  const [detail, setDetail] = useState<InstanceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [actionLoading, setActionLoading] = useState<"" | "stop" | "restart" | "uninstall" | "logs">("");
  const [logs, setLogs] = useState("");
  const [error, setError] = useState("");
  const [botToken, setBotToken] = useState("");
  const [configuring, setConfiguring] = useState(false);
  const [configResult, setConfigResult] = useState<TelegramConfigResponse | null>(null);
  const [configError, setConfigError] = useState("");
  const [showConfigureForm, setShowConfigureForm] = useState(true);

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
    const configured = Boolean(detail?.config?.org_token) || Boolean(configResult);
    setShowConfigureForm(!configured);
  }, [detail?.config?.org_token, configResult]);

  async function handleInstall() {
    if (!instanceId) return;
    setError("");
    setInstalling(true);
    try {
      await api.startInstall(instanceId);
      await fetchDetail();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Install failed.");
    } finally {
      setInstalling(false);
    }
  }

  async function handleAction(action: "stop" | "restart" | "uninstall" | "logs") {
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
      await fetchDetail();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `${action} failed.`);
    } finally {
      setActionLoading("");
    }
  }

  async function handleConfigure() {
    if (!instanceId || !botToken.trim()) return;
    setConfigError("");
    setConfiguring(true);
    try {
      const result = await api.configureInstance(instanceId, botToken.trim());
      setConfigResult(result);
      setBotToken("");
      await fetchDetail();
    } catch (err: unknown) {
      setConfigError(err instanceof Error ? err.message : "Configuration failed.");
    } finally {
      setConfiguring(false);
    }
  }

  if (loading) {
    return <div className="text-gray-500 text-sm">Loading instance...</div>;
  }

  if (!detail) {
    return (
      <div className="text-gray-500 text-sm">
        Instance not found. <Link to="/instances" className="text-blue-400">Back to instances</Link>
      </div>
    );
  }

  const { instance, install_timeline, config } = detail;
  const isInstalling = ["pulling", "configuring", "starting"].includes(instance.install_state);
  const canInstall = instance.install_state === "idle" || instance.install_state === "failed";

  return (
    <div>
      {/* Breadcrumb */}
      <div className="text-xs text-gray-500 mb-5">
        <Link to="/instances" className="hover:text-gray-300">Instances</Link>
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
              {installing ? "Starting..." : instance.install_state === "failed" ? "Retry Install" : "Install"}
            </button>
          )}
          <button onClick={() => handleAction("logs")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">Logs</button>
          <button onClick={() => handleAction("stop")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">Stop</button>
          <button onClick={() => handleAction("restart")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">Restart</button>
          <button onClick={() => handleAction("uninstall")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">Uninstall</button>
        </div>

        {isInstalling && (
          <div className="flex items-center gap-2 text-blue-400 text-sm">
            <span className="inline-block h-2 w-2 rounded-full bg-blue-400 animate-pulse" />
            Installing...
          </div>
        )}

        {instance.install_state === "running" && (
          <div className="flex items-center gap-2 text-green-400 text-sm font-medium">
            <span className="inline-block h-2 w-2 rounded-full bg-green-400" />
            Running
          </div>
        )}
      </div>

      {error && (
        <div className="mb-5 p-3 bg-red-900/40 border border-red-700 rounded-md text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Install timeline */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">Install Progress</h2>
          <InstallTimeline events={install_timeline} />
          <div className="mt-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-300">Docker Logs</h3>
              {actionLoading === "logs" ? <span className="text-xs text-gray-500">Loading...</span> : null}
            </div>
            <pre className="bg-gray-950 border border-gray-800 rounded-md p-3 text-xs text-gray-300 overflow-auto max-h-80 whitespace-pre-wrap">
              {logs || "Click Logs to fetch the latest container output."}
            </pre>
          </div>
        </div>

        {/* Instance info */}
        <div className="space-y-4">
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">Instance Details</h2>
            <dl className="space-y-2 text-sm">
              <div>
                <dt className="text-xs text-gray-500">Product</dt>
                <dd className="text-gray-300 capitalize">{PRODUCT_LABELS[instance.product] ?? instance.product}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Instance ID</dt>
                <dd className="text-gray-300 text-xs font-mono break-all">{instance.id}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Status</dt>
                <dd><StatusPill state={instance.status} /></dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">{instance.product === "zylos" ? "Web Console URL" : "Gateway URL"}</dt>
                <dd className="text-xs break-all">
                  {instance.web_console_url ? (
                    <a href={instance.web_console_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300">
                      {instance.web_console_url}
                    </a>
                  ) : instance.web_console_port ? (
                    <a href={`https://www.ucai.net/connect/${instance.product === "zylos" ? "zylos" : "openclaw"}/${instance.id}/`} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300">
                      {`https://www.ucai.net/connect/${instance.product === "zylos" ? "zylos" : "openclaw"}/${instance.id}/`}
                    </a>
                  ) : (
                    <span className="text-gray-400">-</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Deployed</dt>
                <dd className="text-gray-300 text-xs">{formatDate(instance.created_at)}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">Last updated</dt>
                <dd className="text-gray-300 text-xs">{formatDate(instance.updated_at)}</dd>
              </div>
            </dl>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">Repository</h2>
            <a
              href={PRODUCT_REPOS[instance.product] ?? instance.repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 break-all"
            >
              {instance.repo_url}
            </a>
          </div>

          {/* Telegram Integration */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">Telegram Integration</h2>
            <div className="space-y-3">
              {(configResult || config?.org_token) && (
                <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
                  {configResult?.message || "Already configured"}
                </div>
              )}

              {(configResult || config?.org_token) && (
                <dl className="space-y-1 text-xs">
                  <div><dt className="text-gray-500">Plugin</dt><dd className="text-gray-300 font-mono">{configResult?.plugin_name || config?.plugin_name || "-"}</dd></div>
                  <div><dt className="text-gray-500">Org ID</dt><dd className="text-gray-300 font-mono break-all">{configResult?.org_id || config?.org_id || "-"}</dd></div>
                  <div><dt className="text-gray-500">Hub URL</dt><dd className="text-gray-300 break-all">{configResult?.hub_url || config?.hub_url || "-"}</dd></div>
                  <div><dt className="text-gray-500">组织内名字</dt><dd className="text-gray-300 font-mono">{configResult?.agent_name || config?.agent_name || instance.agent_name || "-"}</dd></div>
                </dl>
              )}

              {!showConfigureForm && (configResult || config?.org_token) && (
                <button
                  onClick={() => {
                    setConfigResult(null);
                    setConfigError("");
                    setShowConfigureForm(true);
                  }}
                  className="text-xs text-gray-500 hover:text-gray-300 underline"
                >
                  重新配置 Telegram
                </button>
              )}

              {showConfigureForm && (
                <>
                  <p className="text-xs text-gray-500">Connect a Telegram bot to this instance.</p>
                  <input
                    type="text"
                    placeholder="Bot token (e.g. 123456:ABC…)"
                    value={botToken}
                    onChange={(e) => setBotToken(e.target.value)}
                    disabled={!instance.compose_project || configuring}
                    className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 disabled:opacity-50 focus:outline-none focus:border-gray-500"
                  />
                  {configError && (
                    <p className="text-xs text-red-400">{configError}</p>
                  )}
                  <button
                    onClick={handleConfigure}
                    disabled={!botToken.trim() || !instance.compose_project || configuring}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-md transition-colors"
                  >
                    {configuring ? "Configuring…" : "Configure"}
                  </button>
                  {!instance.compose_project && (
                    <p className="text-xs text-gray-600">Install the instance first to enable configuration.</p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
