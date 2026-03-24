/**
 * MonitorTab — Instance monitoring dashboard with charts and connectivity tests.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import { AgentActivity } from "./AgentActivity";
import { TrendChart } from "./charts/TrendChart";
import { ConnectivityTest } from "./ConnectivityTest";
import { SessionPanel } from "./SessionPanel";
import { SkillsPanel } from "./SkillsPanel";
import { StatusIndicator } from "./StatusIndicator";
import type { MetricsResponse } from "../types";

export function MonitorTab({ instanceId }: { instanceId: string }) {
  const [data, setData] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [hours, setHours] = useState(24);

  async function load() {
    try {
      const res = await api.instanceMetrics(instanceId, hours);
      setData(res);
    } catch { /* */ }
    setLoading(false);
  }

  useEffect(() => {
    setLoading(true);
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, [instanceId, hours]);

  const cpuData = (data?.metrics || [])
    .filter((m) => m.cpu_percent != null)
    .map((m) => ({ time: (m.collected_at || "").slice(11, 16), value: m.cpu_percent! }));

  const memData = (data?.metrics || [])
    .filter((m) => m.mem_used_mb != null)
    .map((m) => ({ time: (m.collected_at || "").slice(11, 16), value: m.mem_used_mb! }));

  return (
    <div className="space-y-4 p-4">
      {/* Agent Activity — real-time Claude + pm2 services */}
      <AgentActivity instanceId={instanceId} />

      {/* Time range selector */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-300">资源监控</h3>
        <div className="flex gap-1">
          {[1, 6, 24, 72, 168].map((h) => (
            <button key={h} onClick={() => setHours(h)}
              className={`px-2 py-0.5 text-xs rounded ${hours === h ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:text-gray-200"}`}>
              {h <= 24 ? `${h}h` : `${h / 24}d`}
            </button>
          ))}
        </div>
      </div>

      {loading && !data ? (
        <div className="text-center text-gray-600 text-sm py-8">加载中...</div>
      ) : (
        <>
          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
              <TrendChart data={cpuData} color="#60a5fa" unit="%" label="CPU 使用率" />
            </div>
            <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
              <TrendChart data={memData} color="#a78bfa" unit="MB" label="内存使用" />
            </div>
          </div>

          {/* Summary cards */}
          {data?.summary && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <SummaryCard label="平均 CPU" value={`${data.summary.avg_cpu}%`} color="text-blue-400" />
              <SummaryCard label="峰值 CPU" value={`${data.summary.max_cpu}%`} color="text-blue-300" />
              <SummaryCard label="平均内存" value={`${data.summary.avg_mem}MB`} color="text-purple-400" />
              <SummaryCard label="峰值内存" value={`${data.summary.max_mem}MB`} color="text-purple-300" />
            </div>
          )}

          {/* Claude status from latest metric */}
          {data?.metrics && data.metrics.length > 0 && (() => {
            const latest = data.metrics[data.metrics.length - 1];
            return (
              <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-400">Claude 进程</span>
                  <StatusIndicator status={latest.claude_running ? "running" : "offline"} />
                  {latest.claude_mem_mb != null && (
                    <span className="text-xs text-gray-500">内存: {latest.claude_mem_mb}MB</span>
                  )}
                  <span className="text-xs text-gray-600 ml-auto">
                    数据点: {data.summary?.data_points || 0}
                  </span>
                </div>
              </div>
            );
          })()}

          {/* Claude sessions */}
          <SessionPanel instanceId={instanceId} />

          {/* Skills / Plugins */}
          <SkillsPanel instanceId={instanceId} />

          {/* Connectivity test */}
          <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
            <ConnectivityTest instanceId={instanceId} />
          </div>
        </>
      )}
    </div>
  );
}

function SummaryCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2">
      <div className="text-[10px] text-gray-500">{label}</div>
      <div className={`text-lg font-mono ${color}`}>{value}</div>
    </div>
  );
}
