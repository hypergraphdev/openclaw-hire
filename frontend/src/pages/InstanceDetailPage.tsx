import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { InstallTimeline } from "../components/InstallTimeline";
import { StatusPill } from "../components/StatusPill";
import { useT } from "../contexts/LanguageContext";
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
  const t = useT();
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
  const [showTelegramReconfig, setShowTelegramReconfig] = useState(false);
  const [showTelegramHelp, setShowTelegramHelp] = useState(false);
  const [hxaConfiguring, setHxaConfiguring] = useState(false);
  const [hxaResult, setHxaResult] = useState<{ ok: boolean; message: string; agent_name?: string } | null>(null);
  const [hxaError, setHxaError] = useState("");

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
  const isInstalling = ["pulling", "configuring", "starting"].includes(instance.install_state);
  const canInstall = instance.install_state === "idle" || instance.install_state === "failed";

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
          <button onClick={() => handleAction("logs")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.logs")}</button>
          <button onClick={() => handleAction("stop")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.stop")}</button>
          <button onClick={() => handleAction("restart")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.restart")}</button>
          <button onClick={() => handleAction("uninstall")} disabled={actionLoading !== "" || !instance.compose_project} className="bg-rose-700 hover:bg-rose-600 disabled:opacity-50 text-white text-sm px-3 py-2 rounded-md">{t("detail.uninstall")}</button>
        </div>

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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Install timeline */}
        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h2 className="text-sm font-medium text-gray-300 mb-4">{t("detail.installProgress")}</h2>
          <InstallTimeline events={install_timeline} />
          <div className="mt-6">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-gray-300">{t("detail.dockerLogs")}</h3>
              {actionLoading === "logs" ? <span className="text-xs text-gray-500">{t("detail.loadingLogs")}</span> : null}
            </div>
            <pre className="bg-gray-950 border border-gray-800 rounded-md p-3 text-xs text-gray-300 overflow-auto max-h-80 whitespace-pre-wrap">
              {logs || t("detail.logsPlaceholder")}
            </pre>
          </div>
        </div>

        {/* Instance info */}
        <div className="space-y-4">
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
              {instance.web_console_url && (
                <div>
                  <dt className="text-xs text-gray-500">{t("detail.webConsole")}</dt>
                  <dd className="text-xs break-all">
                    <a href={instance.web_console_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300">
                      {t("detail.openConsole")}
                    </a>
                  </dd>
                </div>
              )}
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

          {/* Join Organization (HXA Connect) */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">{t("org.title")}</h2>
            <div className="space-y-3">
              {(hxaResult?.ok || config?.agent_name) && (
                <>
                  <div className="p-3 bg-green-900/30 border border-green-700 rounded-md text-green-300 text-xs">
                    {hxaResult?.message || t("org.alreadyConnected")}
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
        </div>
      </div>
    </div>
  );
}
