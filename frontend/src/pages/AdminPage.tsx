import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { AdminUserInstances, HxaOrg, Instance, User } from "../types";

export function AdminPage() {
  const t = useT();
  const [users, setUsers] = useState<User[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [detail, setDetail] = useState<AdminUserInstances | null>(null);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState("");

  // Orgs for name lookup & transfer
  const [orgs, setOrgs] = useState<HxaOrg[]>([]);
  const orgMap = Object.fromEntries(orgs.map((o) => [o.id, o.name]));

  // Rename state
  const [renamingId, setRenamingId] = useState("");
  const [renameDraft, setRenameDraft] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);

  // Transfer state
  const [transferId, setTransferId] = useState("");
  const [transferTarget, setTransferTarget] = useState("");
  const [transferring, setTransferring] = useState(false);

  useEffect(() => {
    api.adminUsers()
      .then((rows) => {
        setUsers(rows);
        if (rows.length > 0) setSelectedUserId(rows[0].id);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : t("admin.loadFailed")))
      .finally(() => setLoadingUsers(false));

    api.hxaOrgs().then((r) => setOrgs(r.orgs || [])).catch(() => {});
  }, [t]);

  useEffect(() => {
    if (!selectedUserId) return;
    setLoadingDetail(true);
    api.adminUserInstances(selectedUserId)
      .then(setDetail)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : t("admin.loadInstancesFailed")))
      .finally(() => setLoadingDetail(false));
  }, [selectedUserId, t]);

  async function handleRename(inst: Instance) {
    const name = renameDraft.trim();
    if (!name) return;
    setRenameSaving(true);
    try {
      const res = await api.put(`/api/admin/hxa/agents/${inst.id}/name`, { agent_name: name }).then(r => r.json());
      // Update local state
      if (detail) {
        setDetail({
          ...detail,
          instances: detail.instances.map((i) =>
            i.id === inst.id ? { ...i, agent_name: res.agent_name } : i
          ),
        });
      }
      setRenamingId("");
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
    setRenameSaving(false);
  }

  async function handleTransfer(inst: Instance) {
    if (!transferTarget) return;
    const targetName = orgMap[transferTarget] || transferTarget;
    if (!confirm(`确定将 "${inst.agent_name}" 转移到组织 "${targetName}"？Bot 将重新注册。`)) return;
    setTransferring(true);
    try {
      await api.hxaTransferBot(inst.id, transferTarget);
      // Refresh
      if (selectedUserId) {
        const d = await api.adminUserInstances(selectedUserId);
        setDetail(d);
      }
      setTransferId("");
      setTransferTarget("");
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
    setTransferring(false);
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-white">{t("admin.title")}</h1>
        <div className="flex gap-3 mt-2">
          <Link to="/admin/settings" className="text-xs text-blue-400 hover:text-blue-300">{t("admin.settingsLink")}</Link>
          <Link to="/admin/hxa" className="text-xs text-blue-400 hover:text-blue-300">{t("admin.hxaLink")}</Link>
        </div>
        <p className="text-gray-500 text-sm mt-1">{t("admin.subtitle")}</p>
      </div>

      {error && <div className="mb-4 p-3 text-sm rounded bg-red-900/40 border border-red-700 text-red-300">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-3">{t("admin.users")}</h2>
          {loadingUsers ? (
            <div className="text-sm text-gray-500">{t("admin.loadingUsers")}</div>
          ) : users.length === 0 ? (
            <div className="text-sm text-gray-500">{t("admin.noUsers")}</div>
          ) : (
            <div className="space-y-2 max-h-[520px] overflow-auto pr-1">
              {users.map((u) => (
                <button
                  key={u.id}
                  onClick={() => setSelectedUserId(u.id)}
                  className={`w-full text-left rounded-md border px-3 py-2 transition-colors ${
                    selectedUserId === u.id ? "border-blue-600 bg-blue-600/10" : "border-gray-800 hover:border-gray-700"
                  }`}
                >
                  <div className="text-sm text-white flex items-center gap-2">
                    <span className="truncate">{u.name}</span>
                    {u.is_admin ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-700/50 text-amber-200">admin</span> : null}
                  </div>
                  <div className="text-xs text-gray-500 truncate">{u.email}</div>
                  <div className="text-[11px] text-gray-600 font-mono truncate">{u.id}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-2 bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-3">{t("admin.userInstances")}</h2>
          {loadingDetail ? (
            <div className="text-sm text-gray-500">{t("common.loading")}</div>
          ) : !detail ? (
            <div className="text-sm text-gray-500">{t("admin.selectUser")}</div>
          ) : (
            <>
              <div className="mb-3 text-xs text-gray-400">
                <span className="text-gray-500">{t("admin.user")}</span> {detail.user.name} · {detail.user.email}
                {detail.user.is_admin ? " · admin" : ""}
              </div>
              {detail.instances.length === 0 ? (
                <div className="text-sm text-gray-500">{t("admin.noInstances")}</div>
              ) : (
                <div className="overflow-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-800">
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("instances.name")}</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("instances.product")}</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("admin.state")}</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">组织</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">组内名称</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("admin.telegramBound")}</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("admin.created")}</th>
                        <th className="text-right py-2 text-xs text-gray-500">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.instances.map((i) => (
                        <tr key={i.id} className="border-b border-gray-800/70">
                          <td className="py-2 pr-3">
                            <div className="text-white">{i.name}</div>
                            <div className="text-[11px] text-gray-600 font-mono">{i.id}</div>
                          </td>
                          <td className="py-2 pr-3 text-gray-300 capitalize">{i.product}</td>
                          <td className="py-2 pr-3 text-gray-300">{i.install_state}</td>
                          <td className="py-2 pr-3">
                            {i.org_id ? (
                              <span className="text-blue-400 text-xs">{orgMap[i.org_id] || i.org_id.substring(0, 8) + "..."}</span>
                            ) : (
                              <span className="text-gray-600 text-xs">-</span>
                            )}
                          </td>
                          <td className="py-2 pr-3">
                            {renamingId === i.id ? (
                              <div className="flex items-center gap-1">
                                <input type="text" value={renameDraft}
                                  onChange={(e) => setRenameDraft(e.target.value)}
                                  className="text-xs font-mono text-gray-200 bg-gray-800 border border-gray-700 px-1 py-0.5 rounded w-32 focus:outline-none focus:border-gray-500"
                                  onKeyDown={(e) => e.key === "Enter" && handleRename(i)} />
                                <button onClick={() => handleRename(i)} disabled={renameSaving}
                                  className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50">{renameSaving ? "..." : t("common.ok")}</button>
                                <button onClick={() => setRenamingId("")} className="text-xs text-gray-500">X</button>
                              </div>
                            ) : i.agent_name ? (
                              <span className="text-green-400 text-xs group cursor-default">
                                {i.agent_name}
                                <button onClick={() => { setRenameDraft(i.agent_name || ""); setRenamingId(i.id); }}
                                  className="ml-1 text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity text-[10px]">
                                  ✏️
                                </button>
                              </span>
                            ) : (
                              <span className="text-gray-600 text-xs">-</span>
                            )}
                          </td>
                          <td className="py-2 pr-3">
                            {i.is_telegram_configured
                              ? <span className="text-green-400 text-xs">✓</span>
                              : <span className="text-gray-600 text-xs">-</span>}
                          </td>
                          <td className="py-2 pr-3 text-gray-500 text-xs">{new Date(i.created_at).toLocaleString()}</td>
                          <td className="py-2 text-right">
                            {i.agent_name && orgs.length > 1 && (
                              transferId === i.id ? (
                                <div className="inline-flex items-center gap-1">
                                  <select value={transferTarget} onChange={(e) => setTransferTarget(e.target.value)}
                                    className="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded px-1 py-0.5">
                                    <option value="">选择组织</option>
                                    {orgs.filter((o) => o.id !== i.org_id).map((o) => (
                                      <option key={o.id} value={o.id}>{o.name}</option>
                                    ))}
                                  </select>
                                  <button onClick={() => handleTransfer(i)} disabled={transferring || !transferTarget}
                                    className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50">
                                    {transferring ? "..." : t("common.ok")}
                                  </button>
                                  <button onClick={() => { setTransferId(""); setTransferTarget(""); }}
                                    className="text-xs text-gray-500">X</button>
                                </div>
                              ) : (
                                <button onClick={() => setTransferId(i.id)}
                                  className="text-xs text-yellow-500 hover:text-yellow-400">转移</button>
                              )
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
