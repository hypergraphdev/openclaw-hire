import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { StatusPill } from "../components/StatusPill";
import type { Instance } from "../types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function configStatus(inst: Instance) {
  if (!inst.telegram_bot_token) return "Telegram 未配置";
  if (!inst.agent_name) return "组织名未绑定";
  return "已配置";
}

export function InstancesPage() {
  const [instances, setInstances] = useState<Instance[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string>("");

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
    if (!confirm(`Delete instance '${name}'? This will remove runtime data and cannot be undone.`)) return;
    setDeletingId(id);
    try {
      await api.deleteInstance(id);
      setInstances((prev) => prev.filter((x) => x.id !== id));
    } finally {
      setDeletingId("");
    }
  }

  if (loading) {
    return <div className="text-gray-500 text-sm">Loading instances...</div>;
  }

  return (
    <div>
      <div className="flex items-start sm:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-white">My Instances</h1>
          <p className="text-gray-500 text-sm mt-1">
            {instances.length} instance{instances.length !== 1 ? "s" : ""} deployed
          </p>
        </div>
        <Link
          to="/catalog"
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-md transition-colors whitespace-nowrap"
        >
          + Deploy New
        </Link>
      </div>

      {instances.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-10 text-center">
          <div className="text-gray-600 text-4xl mb-3">⊞</div>
          <div className="text-gray-400 text-sm">No instances deployed yet</div>
          <Link to="/catalog" className="text-blue-400 hover:text-blue-300 text-sm mt-2 inline-block">
            Browse catalog →
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
                  <StatusPill state={inst.install_state} />
                </div>

                <div className="mt-3 text-xs text-gray-400 space-y-1">
                  <div>Product: <span className="capitalize text-gray-300">{inst.product}</span></div>
                  <div>配置: <span className={inst.telegram_bot_token && inst.agent_name ? "text-green-400" : "text-amber-400"}>{configStatus(inst)}</span></div>
                  <div>组织内名字: <span className="text-gray-300 font-mono">{inst.agent_name || "-"}</span></div>
                  {inst.web_console_port && <div>Gateway Port: <span className="text-gray-300 font-mono">{inst.web_console_port}</span></div>}
                  {inst.http_port && <div>Bridge Port: <span className="text-gray-300 font-mono">{inst.http_port}</span></div>}
                  <div>Deployed: <span className="text-gray-300">{formatDate(inst.created_at)}</span></div>
                </div>

                <div className="mt-4 flex items-center justify-between">
                  <button
                    onClick={() => handleDelete(inst.id, inst.name)}
                    disabled={deletingId === inst.id}
                    className="text-xs text-rose-400 hover:text-rose-300 disabled:opacity-50"
                  >
                    {deletingId === inst.id ? "Deleting..." : "Delete"}
                  </button>
                  <Link to={`/instances/${inst.id}`} className="text-xs text-blue-400 hover:text-blue-300">
                    Manage →
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
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Name</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Product</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Install State</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Configured</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Org Name</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Ports</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">Deployed</th>
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
                    <td className="px-5 py-3">
                      <StatusPill state={inst.install_state} />
                    </td>
                    <td className="px-5 py-3">
                      <span className={`text-xs ${inst.telegram_bot_token && inst.agent_name ? "text-green-400" : "text-amber-400"}`}>
                        {configStatus(inst)}
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
                          {deletingId === inst.id ? "Deleting..." : "Delete"}
                        </button>
                        <Link to={`/instances/${inst.id}`} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                          Manage →
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
