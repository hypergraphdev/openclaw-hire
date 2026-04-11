/**
 * SessionPanel — Claude session management for an instance.
 * Shows session list with metadata, supports refresh and clear-all.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ClaudeSession, SessionsResponse } from "../types";

function formatActivity(ts: string): string {
  if (!ts) return "-";
  try {
    const d = new Date(typeof ts === "number" ? ts * 1000 : ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function SessionPanel({ instanceId }: { instanceId: string }) {
  const t = useT();
  const [data, setData] = useState<SessionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);

  async function load() {
    setError("");
    try {
      const res = await api.instanceSessions(instanceId);
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("session.loadFailed"));
    }
    setLoading(false);
  }

  useEffect(() => {
    setLoading(true);
    load();
  }, [instanceId]);

  async function handleClear() {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    setClearing(true);
    setError("");
    try {
      const res = await api.instanceSessionsClear(instanceId);
      if (!res.ok) {
        setError(res.detail || t("session.clearFailed"));
      }
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("session.clearFailed"));
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  }

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-lg p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-300">{t("session.title")}</span>
          {data && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
              {data.count}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => { setLoading(true); load(); }}
            disabled={loading}
            className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-400 hover:text-gray-200 hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {loading ? t("common.loading") : t("session.refresh")}
          </button>
          {confirmClear ? (
            <div className="flex items-center gap-1">
              <button
                onClick={handleClear}
                disabled={clearing}
                className="text-xs px-2 py-1 rounded bg-red-700 text-white hover:bg-red-600 disabled:opacity-50 transition-colors"
              >
                {clearing ? t("session.clearing") : t("session.confirmClear")}
              </button>
              <button
                onClick={() => setConfirmClear(false)}
                className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors"
              >
                {t("common.cancel")}
              </button>
            </div>
          ) : (
            <button
              onClick={handleClear}
              disabled={clearing || !data || data.count === 0}
              className="text-xs px-2 py-1 rounded bg-gray-800 text-red-400 hover:text-red-300 hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {t("session.clearAll")}
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-2 p-2 bg-red-900/30 border border-red-800 rounded text-xs text-red-300">
          {error}
        </div>
      )}

      {/* Content */}
      {loading && !data ? (
        <div className="text-center text-gray-600 text-xs py-4">{t("common.loading")}</div>
      ) : !data || data.count === 0 ? (
        <div className="text-center text-gray-600 text-xs py-4">{t("session.noSessions")}</div>
      ) : (
        <div className="space-y-1.5 max-h-60 overflow-y-auto">
          {data.sessions.map((s: ClaudeSession, idx: number) => (
            <div
              key={s.id || idx}
              className="flex items-center justify-between px-2.5 py-2 bg-gray-800/50 border border-gray-700/50 rounded text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-gray-300 font-mono truncate max-w-[160px]" title={s.id}>
                  {s.id ? (s.id.length > 20 ? `${s.id.slice(0, 8)}...${s.id.slice(-8)}` : s.id) : `session-${idx + 1}`}
                </span>
                <span className="text-[10px] px-1 py-0.5 rounded bg-gray-700 text-gray-400">
                  {s.type}
                </span>
              </div>
              <div className="flex items-center gap-3 text-gray-500 shrink-0">
                {s.tokenUsage && (
                  <span title={`输入: ${s.tokenUsage.input}, 输出: ${s.tokenUsage.output}`}>
                    {formatTokens(s.tokenUsage.input + s.tokenUsage.output)} tokens
                  </span>
                )}
                <span>{formatActivity(s.lastActivity)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
