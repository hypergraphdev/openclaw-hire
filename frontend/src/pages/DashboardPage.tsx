import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../contexts/AuthContext";
import type { DashboardData } from "../types";

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-5 py-4">
      <div className={`text-2xl font-bold ${accent ?? "text-white"}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.dashboard()
      .then(setData)
      .catch(() => setError("Failed to load dashboard."));

    const interval = setInterval(() => {
      api.dashboard().then(setData).catch(() => {});
    }, 15_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-xl font-semibold text-white">
          Welcome back, {user?.name?.split(" ")[0]}
        </h1>
        <p className="text-gray-500 text-sm mt-1">
          {user?.company_name ? `${user.company_name} · ` : ""}
          {user?.email}
        </p>
      </div>

      {error && (
        <div className="mb-6 p-3 bg-red-900/40 border border-red-700 rounded-md text-red-300 text-sm">
          {error}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Instances" value={data?.summary.total ?? 0} />
        <StatCard label="Running" value={data?.summary.running ?? 0} accent="text-green-400" />
        <StatCard label="Installing" value={data?.summary.installing ?? 0} accent="text-blue-400" />
        <StatCard label="Failed" value={data?.summary.failed ?? 0} accent="text-red-400" />
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Link
          to="/catalog"
          className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-blue-600 transition-colors group"
        >
          <div className="text-blue-400 text-xl mb-2">◈</div>
          <div className="text-sm font-medium text-white group-hover:text-blue-300">Browse Catalog</div>
          <div className="text-xs text-gray-500 mt-1">Deploy OpenClaw or Zylos to your environment</div>
        </Link>
        <Link
          to="/instances"
          className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-blue-600 transition-colors group"
        >
          <div className="text-gray-400 text-xl mb-2">⊞</div>
          <div className="text-sm font-medium text-white group-hover:text-blue-300">My Instances</div>
          <div className="text-xs text-gray-500 mt-1">
            {data?.summary.total
              ? `${data.summary.total} instance${data.summary.total !== 1 ? "s" : ""} deployed`
              : "No instances yet"}
          </div>
        </Link>
      </div>

      {/* Account info */}
      <div className="mt-8 bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-300 mb-3">Account</h2>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-gray-500">User ID</dt>
          <dd className="text-gray-300 font-mono text-xs">{user?.id}</dd>
          <dt className="text-gray-500">Member since</dt>
          <dd className="text-gray-300">
            {user ? new Date(user.created_at).toLocaleDateString() : "—"}
          </dd>
        </dl>
      </div>
    </div>
  );
}
