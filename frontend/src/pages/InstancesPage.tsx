import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { Instance } from "../types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString([], {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Colored dot for install state */
function InstallDot({ state }: { state: string }) {
  const color =
    state === "running" ? "bg-green-400" :
    state === "failed" ? "bg-red-400" :
    ["pulling", "configuring", "starting"].includes(state) ? "bg-yellow-400 animate-pulse" :
    "bg-gray-500";
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${color}`} />;
}

/** Colored dot for config + org online state */
function ConfigDot({ inst }: { inst: Instance }) {
  if (!inst.agent_name) return <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-400" title="未配置组织" />;
  // has agent_name = configured, show green
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-400" title="已配置" />;
}

export function InstancesPage() {
  const t = useT();
  const [instances, setInstances] = useState<Instance[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string>("");

  function configStatus(inst: Instance) {
    if (!inst.is_telegram_configured) return t("instances.configTelegramNo");
    if (!inst.agent_name) return t("instances.configOrgNo");
    return t("instances.configDone");
  }

  useEffect(() => {
    api
      .listInstances()
      .then(setInstances)
      .finally(() => setLoading(false));

    const interval = setInterval(() => {
      api.listInstances().then(setInstances).catch(() => {});
    }, 8_000);
    return () => clearInterval(interval);
  }, []);

  async function handleDelete(id: string, name: string) {
    if (!confirm(t("instances.deleteConfirm", { name }))) return;
    setDeletingId(id);
    try {
      await api.deleteInstance(id);
      setInstances((prev) => prev.filter((x) => x.id !== id));
    } finally {
      setDeletingId("");
    }
  }

  if (loading) {
    return <div className="text-gray-500 text-sm">{t("instances.loading")}</div>;
  }

  return (
    <div>
      <div className="flex items-start sm:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-white">{t("instances.title")}</h1>
          <p className="text-gray-500 text-sm mt-1">
            {t("instances.count", { count: instances.length })}
          </p>
        </div>
        <Link
          to="/catalog"
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-md transition-colors whitespace-nowrap"
        >
          {t("instances.deployNew")}
        </Link>
      </div>

      {instances.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-10 text-center">
          <div className="text-gray-600 text-4xl mb-3">⊞</div>
          <div className="text-gray-400 text-sm">{t("instances.noInstances")}</div>
          <Link to="/catalog" className="text-blue-400 hover:text-blue-300 text-sm mt-2 inline-block">
            {t("instances.browseCatalog")}
          </Link>
        </div>
      ) : (
        <>
          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {instances.map((inst) => (
              <div key={inst.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-white font-medium">{inst.name}</div>
                    <div className="text-[11px] text-gray-500 font-mono mt-1 break-all">{inst.id}</div>
                  </div>
                  <InstallDot state={inst.install_state} />
                </div>

                <div className="mt-3 text-xs text-gray-400 space-y-1">
                  <div>{t("instances.product")}: <span className="capitalize text-gray-300">{inst.product}</span></div>
                  <div>{t("instances.config")}: <span className={inst.is_telegram_configured && inst.agent_name ? "text-green-400" : "text-amber-400"}>{configStatus(inst)}</span></div>
                  <div>{t("instances.orgInternalName")}: <span className="text-gray-300 font-mono">{inst.agent_name || "-"}</span></div>
                  {inst.web_console_port && <div>{t("instances.gatewayPort")}: <span className="text-gray-300 font-mono">{inst.web_console_port}</span></div>}
                  {inst.http_port && <div>{t("instances.bridgePort")}: <span className="text-gray-300 font-mono">{inst.http_port}</span></div>}
                  <div>{t("instances.deployed")}: <span className="text-gray-300">{formatDate(inst.created_at)}</span></div>
                </div>

                <div className="mt-4 flex items-center justify-between">
                  <button
                    onClick={() => handleDelete(inst.id, inst.name)}
                    disabled={deletingId === inst.id}
                    className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50"
                  >
                    {deletingId === inst.id ? t("instances.deleting") : t("common.delete")}
                  </button>
                  <Link to={`/instances/${inst.id}`} className="text-xs text-blue-400 hover:text-blue-300">
                    {t("instances.manage")}
                  </Link>
                </div>
              </div>
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden md:block bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.name")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.product")}</th>
                  <th className="text-center px-3 py-3 text-xs text-gray-500 font-medium" title="安装状态">状态</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.configured")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.orgName")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.ports")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.deployed")}</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {instances.map((inst) => (
                  <tr key={inst.id} className="hover:bg-gray-800/50 transition-colors">
                    <td className="px-5 py-3">
                      <div className="text-white font-medium">{inst.name}</div>
                      <div className="text-xs text-gray-500 font-mono mt-0.5">{inst.id}</div>
                    </td>
                    <td className="px-5 py-3">
                      <span className="text-gray-300 capitalize">{inst.product}</span>
                    </td>
                    <td className="px-3 py-3 text-center">
                      <InstallDot state={inst.install_state} />
                    </td>
                    <td className="px-5 py-3">
                      <span className="inline-flex items-center gap-2">
                        <span className={`text-xs ${inst.is_telegram_configured && inst.agent_name ? "text-green-400" : "text-amber-400"}`}>
                          {configStatus(inst)}
                        </span>
                        <ConfigDot inst={inst} />
                      </span>
                    </td>
                    <td className="px-5 py-3 text-gray-300 text-xs font-mono">{inst.agent_name || "-"}</td>
                    <td className="px-5 py-3 text-gray-300 text-xs font-mono">
                      {inst.web_console_port ? `${inst.web_console_port}${inst.http_port ? " / " + inst.http_port : ""}` : "-"}
                    </td>
                    <td className="px-5 py-3 text-gray-500">{formatDate(inst.created_at)}</td>
                    <td className="px-5 py-3 text-right">
                      <div className="inline-flex items-center gap-3">
                        <button
                          onClick={() => handleDelete(inst.id, inst.name)}
                          disabled={deletingId === inst.id}
                          className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50 transition-colors"
                        >
                          {deletingId === inst.id ? t("instances.deleting") : t("common.delete")}
                        </button>
                        <Link to={`/instances/${inst.id}`} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                          {t("instances.manage")}
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
