/**
 * AgentActivity — Compact card showing Claude process, pm2 services, and overall state.
 * Auto-refreshes every 10 seconds.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import { StatusIndicator } from "./StatusIndicator";
import type { AgentActivityResponse } from "../types";

const STATE_BADGE_STYLE: Record<string, { bg: string; text: string; key: string }> = {
  idle: { bg: "bg-yellow-900/40", text: "text-yellow-400", key: "status.idle" },
  busy: { bg: "bg-green-900/40", text: "text-green-400", key: "status.busy" },
  waiting: { bg: "bg-blue-900/40", text: "text-blue-400", key: "status.waiting" },
  offline: { bg: "bg-gray-800/40", text: "text-gray-500", key: "status.offline" },
};

function formatUptime(seconds: number | null): string {
  if (seconds == null || seconds < 0) return "-";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

export function AgentActivity({ instanceId }: { instanceId: string }) {
  const t = useT();
  const [data, setData] = useState<AgentActivityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const res = await api.agentActivity(instanceId);
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("agent.loadFailed"));
    }
    setLoading(false);
  }

  useEffect(() => {
    setLoading(true);
    load();
    const timer = setInterval(load, 10_000);
    return () => clearInterval(timer);
  }, [instanceId]);

  if (loading && !data) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
        <div className="text-center text-gray-600 text-sm py-4">{t("agent.loading")}</div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
        <div className="text-center text-red-500 text-sm py-4">{error}</div>
      </div>
    );
  }

  if (!data) return null;

  const badge = STATE_BADGE_STYLE[data.state] || STATE_BADGE_STYLE.offline;

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3 space-y-3">
      {/* Header: title + state badge */}
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-gray-300">{t("agent.title")}</h4>
        <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full ${badge.bg} ${badge.text}`}>
          {t(badge.key)}
        </span>
      </div>

      {/* Claude process */}
      <div className="flex items-center gap-3 flex-wrap">
        <StatusIndicator status={data.claude.running ? "running" : "offline"} label={data.claude.running ? t("agent.claudeRunning") : t("agent.claudeStopped")} />
        {data.claude.running && (
          <>
            <span className="text-[10px] text-gray-500">
              PID {data.claude.pid}
            </span>
            <span className="text-[10px] text-gray-500">
              {t("agent.running", { uptime: formatUptime(data.claude.uptime_seconds) })}
            </span>
            {data.claude.memory_mb != null && (
              <span className="text-[10px] text-gray-500">
                {data.claude.memory_mb}MB
              </span>
            )}
          </>
        )}
      </div>

      {/* pm2 services table */}
      {data.services.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-1 pr-2 font-normal">{t("agent.service")}</th>
                <th className="text-left py-1 pr-2 font-normal">{t("admin.state")}</th>
                <th className="text-right py-1 pr-2 font-normal">{t("agent.uptime")}</th>
                <th className="text-right py-1 pr-2 font-normal">Memory</th>
                <th className="text-right py-1 font-normal">{t("agent.restarts")}</th>
              </tr>
            </thead>
            <tbody>
              {data.services.map((svc) => (
                <tr key={svc.name} className="border-b border-gray-800/50">
                  <td className="py-1 pr-2 text-gray-300 font-mono">{svc.name}</td>
                  <td className="py-1 pr-2">
                    <StatusIndicator status={svc.status === "online" ? "online" : svc.status === "stopped" ? "stopped" : "error"} />
                  </td>
                  <td className="py-1 pr-2 text-right text-gray-400">{svc.uptime}</td>
                  <td className="py-1 pr-2 text-right text-gray-400">{svc.memory_mb}MB</td>
                  <td className="py-1 text-right text-gray-400">
                    {svc.restarts > 0 ? (
                      <span className="text-yellow-500">{svc.restarts}</span>
                    ) : (
                      svc.restarts
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.services.length === 0 && !data.claude.running && (
        <div className="text-center text-gray-600 text-[11px] py-2">{t("agent.noProcesses")}</div>
      )}
    </div>
  );
}
