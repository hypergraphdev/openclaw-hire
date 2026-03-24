import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Alert } from "../types";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "text-red-400",
  warning: "text-amber-400",
  info: "text-blue-400",
};

const SEVERITY_BG: Record<string, string> = {
  critical: "bg-red-900/30 border-red-800",
  warning: "bg-amber-900/20 border-amber-800",
  info: "bg-blue-900/20 border-blue-800",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function AlertBell() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const data = await api.listAlerts();
      setAlerts(data.alerts);
      setUnreadCount(data.unread_count);
    } catch {
      // silently ignore - user may not be authenticated yet
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 30_000);
    return () => clearInterval(interval);
  }, [fetchAlerts]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  async function handleMarkRead(id: string) {
    await api.markAlertRead(id);
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, is_read: 1 } : a)));
    setUnreadCount((c) => Math.max(0, c - 1));
  }

  async function handleMarkAllRead() {
    await api.markAllAlertsRead();
    setAlerts((prev) => prev.map((a) => ({ ...a, is_read: 1 })));
    setUnreadCount(0);
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => { setOpen((v) => !v); if (!open) fetchAlerts(); }}
        className="relative p-2 text-gray-400 hover:text-white transition-colors"
        title="Alerts"
      >
        {/* Bell icon (SVG) */}
        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-96 overflow-auto bg-gray-900 border border-gray-700 rounded-lg shadow-xl z-50">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
            <span className="text-sm font-medium text-gray-200">Alerts</span>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* Alert list */}
          {alerts.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-gray-500">
              No alerts
            </div>
          ) : (
            <div className="divide-y divide-gray-800">
              {alerts.slice(0, 20).map((alert) => (
                <div
                  key={alert.id}
                  className={`px-4 py-3 ${alert.is_read ? "opacity-60" : ""} hover:bg-gray-800/50 cursor-pointer transition-colors`}
                  onClick={() => { if (!alert.is_read) handleMarkRead(alert.id); }}
                >
                  <div className="flex items-start gap-2">
                    <span className={`text-xs font-semibold uppercase mt-0.5 ${SEVERITY_COLORS[alert.severity] || "text-gray-400"}`}>
                      {alert.severity}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-200 break-words">{alert.message}</p>
                      <p className="text-xs text-gray-500 mt-1">{timeAgo(alert.created_at)}</p>
                    </div>
                    {!alert.is_read && (
                      <span className="mt-1 h-2 w-2 rounded-full bg-blue-400 flex-shrink-0" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
