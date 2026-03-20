import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../contexts/AuthContext";
import { useT } from "../contexts/LanguageContext";
import type { DashboardData } from "../types";

function StatCard({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-5 py-4">
      <div className={`text-2xl font-bold ${accent ?? "text-white"}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-1">{label}</div>
    </div>
  );
}

type PlatformStats = { total_users: number; total_bots: number; running_bots: number; org_bots: number };

export function DashboardPage() {
  const { user } = useAuth();
  const t = useT();
  const [data, setData] = useState<DashboardData | null>(null);
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.dashboard()
      .then(setData)
      .catch(() => setError(t("dashboard.loadFailed")));
    api.platformStats().then(setStats).catch(() => {});

    const interval = setInterval(() => {
      api.dashboard().then(setData).catch(() => {});
      api.platformStats().then(setStats).catch(() => {});
    }, 15_000);
    return () => clearInterval(interval);
  }, [t]);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-xl font-semibold text-white">
          {t("dashboard.welcome", { name: user?.name?.split(" ")[0] ?? "" })}
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

      {/* Platform-wide stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <StatCard label={t("dashboard.totalUsers")} value={stats?.total_users ?? 0} accent="text-purple-400" />
        <StatCard label={t("dashboard.totalBots")} value={stats?.total_bots ?? 0} accent="text-cyan-400" />
        <StatCard label={t("dashboard.runningBots")} value={stats?.running_bots ?? 0} accent="text-green-400" />
        <StatCard label={t("dashboard.orgBots")} value={stats?.org_bots ?? 0} accent="text-yellow-400" />
      </div>

      {/* User's instance stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label={t("dashboard.totalInstances")} value={data?.summary.total ?? 0} />
        <StatCard label={t("dashboard.running")} value={data?.summary.running ?? 0} accent="text-green-400" />
        <StatCard label={t("dashboard.installing")} value={data?.summary.installing ?? 0} accent="text-blue-400" />
        <StatCard label={t("dashboard.failed")} value={data?.summary.failed ?? 0} accent="text-red-400" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Link
          to="/catalog"
          className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-blue-600 transition-colors group"
        >
          <div className="text-blue-400 text-xl mb-2">◈</div>
          <div className="text-sm font-medium text-white group-hover:text-blue-300">{t("dashboard.browseCatalog")}</div>
          <div className="text-xs text-gray-500 mt-1">{t("dashboard.browseCatalogDesc")}</div>
        </Link>
        <Link
          to="/instances"
          className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-blue-600 transition-colors group"
        >
          <div className="text-gray-400 text-xl mb-2">⊞</div>
          <div className="text-sm font-medium text-white group-hover:text-blue-300">{t("dashboard.myInstances")}</div>
          <div className="text-xs text-gray-500 mt-1">
            {data?.summary.total
              ? t("dashboard.instanceCount", { count: data.summary.total })
              : t("dashboard.noInstances")}
          </div>
        </Link>
      </div>

      <div className="mt-8 bg-gray-900 border border-gray-800 rounded-lg p-5">
        <h2 className="text-sm font-medium text-gray-300 mb-3">{t("dashboard.account")}</h2>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-gray-500">{t("dashboard.userId")}</dt>
          <dd className="text-gray-300 font-mono text-xs">{user?.id}</dd>
          <dt className="text-gray-500">{t("dashboard.memberSince")}</dt>
          <dd className="text-gray-300">
            {user ? new Date(user.created_at).toLocaleDateString() : "—"}
          </dd>
        </dl>
      </div>
    </div>
  );
}
