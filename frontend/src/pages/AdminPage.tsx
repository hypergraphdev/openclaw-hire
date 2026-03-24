import { Link } from "react-router-dom";
import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { AdminUserInstances, HxaOrg, Instance, User } from "../types";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DiagData = Record<string, any>;

function StatusDot({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="inline-block w-2 h-2 rounded-full bg-gray-600" />;
  return <span className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-green-400" : "bg-red-500"}`} />;
}

export function AdminPage() {
  const t = useT();
  const [users, setUsers] = useState<User[]>([]);
  const [userSearch, setUserSearch] = useState("");
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

  // Menu state (3-dot)
  const [menuId, setMenuId] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  // Transfer state
  const [transferId, setTransferId] = useState("");
  const [transferTarget, setTransferTarget] = useState("");
  const [transferring, setTransferring] = useState(false);

  // Diagnostics modal
  const [diagId, setDiagId] = useState("");
  const [diagData, setDiagData] = useState<DiagData | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [controlLoading, setControlLoading] = useState("");

  // Resource limits form
  const [resMemory, setResMemory] = useState(8192);
  const [resCpus, setResCpus] = useState(4);
  const [resSaving, setResSaving] = useState(false);
  const [resMsg, setResMsg] = useState("");

  // Close menu on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuId("");
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

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

  const filteredUsers = userSearch.trim()
    ? users.filter((u) =>
        u.name.toLowerCase().includes(userSearch.toLowerCase()) ||
        u.email.toLowerCase().includes(userSearch.toLowerCase()))
    : users;

  async function handleRename(inst: Instance) {
    const name = renameDraft.trim();
    if (!name) return;
    setRenameSaving(true);
    try {
      const res = await api.put(`/api/admin/hxa/agents/${inst.id}/name`, { agent_name: name }).then(r => r.json());
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

  async function openDiagnostics(instId: string) {
    setDiagId(instId);
    setDiagLoading(true);
    setDiagData(null);
    setResMsg("");
    setMenuId("");
    try {
      const data = await api.adminInstanceDiagnostics(instId);
      setDiagData(data);
      // Pre-populate resource limits from current container config
      if (data.container?.memory_limit_mb) setResMemory(data.container.memory_limit_mb);
      if (data.container?.cpu_limit) setResCpus(data.container.cpu_limit);
    } catch (e: unknown) {
      alert((e as Error).message || "Failed to load diagnostics");
      setDiagId("");
    }
    setDiagLoading(false);
  }

  async function handleControl(instId: string, action: string) {
    const labels: Record<string, string> = { stop: "停止", start: "启动", restart: "重启", kill_claude: "杀掉 Claude" };
    if (!confirm(`确定要 ${labels[action] || action} 这个实例？`)) return;
    setControlLoading(action);
    try {
      const res = await api.adminInstanceControl(instId, action);
      alert(res.message || "操作完成");
      // Refresh diagnostics
      const data = await api.adminInstanceDiagnostics(instId);
      setDiagData(data);
    } catch (e: unknown) {
      alert((e as Error).message || "操作失败");
    }
    setControlLoading("");
  }

  function formatUptime(seconds: number | null): string {
    if (seconds === null || seconds === undefined) return "-";
    if (seconds < 60) return `${seconds}秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时 ${Math.floor((seconds % 3600) / 60)}分`;
    return `${Math.floor(seconds / 86400)}天 ${Math.floor((seconds % 86400) / 3600)}小时`;
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

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* User list - narrower */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-3">
          <h2 className="text-sm font-medium text-gray-300 mb-2">{t("admin.users")}</h2>
          <input
            type="text"
            value={userSearch}
            onChange={(e) => setUserSearch(e.target.value)}
            placeholder="搜索用户..."
            className="w-full mb-2 text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-500"
          />
          {loadingUsers ? (
            <div className="text-sm text-gray-500">{t("admin.loadingUsers")}</div>
          ) : filteredUsers.length === 0 ? (
            <div className="text-sm text-gray-500">{userSearch ? "无匹配用户" : t("admin.noUsers")}</div>
          ) : (
            <div className="space-y-1 max-h-[520px] overflow-auto pr-1">
              {filteredUsers.map((u) => (
                <button
                  key={u.id}
                  onClick={() => setSelectedUserId(u.id)}
                  className={`w-full text-left rounded border px-2 py-1.5 transition-colors ${
                    selectedUserId === u.id ? "border-blue-600 bg-blue-600/10" : "border-gray-800 hover:border-gray-700"
                  }`}
                >
                  <div className="text-xs text-white flex items-center gap-1">
                    <span className="truncate">{u.name || u.email.split("@")[0]}</span>
                    {u.is_admin ? <span className="text-[9px] px-1 py-0.5 rounded bg-amber-700/50 text-amber-200">admin</span> : null}
                  </div>
                  <div className="text-[10px] text-gray-500 truncate">{u.email}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Instance table - wider */}
        <div className="lg:col-span-3 bg-gray-900 border border-gray-800 rounded-lg p-4">
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
                <div className="overflow-visible">
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
                        <th className="text-right py-2 text-xs text-gray-500"></th>
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
                          <td className="py-2 text-right relative">
                            {/* Transfer mode */}
                            {transferId === i.id ? (
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
                              /* 3-dot menu */
                              <div className="relative inline-block" ref={menuId === i.id ? menuRef : undefined}>
                                <button onClick={() => setMenuId(menuId === i.id ? "" : i.id)}
                                  className="text-gray-500 hover:text-gray-300 px-1 py-0.5 text-sm">⋮</button>
                                {menuId === i.id && (
                                  <div className="absolute right-0 bottom-full mb-1 z-50 bg-gray-800 border border-gray-700 rounded shadow-lg py-1 min-w-[100px]">
                                    <button onClick={() => openDiagnostics(i.id)}
                                      className="w-full text-left px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700">详情</button>
                                    <Link to={`/instances/${i.id}`} onClick={() => setMenuId("")}
                                      className="block px-3 py-1.5 text-xs text-blue-400 hover:bg-gray-700">实例</Link>
                                    {i.agent_name && orgs.length > 1 && (
                                      <button onClick={() => { setTransferId(i.id); setMenuId(""); }}
                                        className="w-full text-left px-3 py-1.5 text-xs text-yellow-400 hover:bg-gray-700">转移</button>
                                    )}
                                  </div>
                                )}
                              </div>
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

      {/* Diagnostics Modal */}
      {diagId && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setDiagId("")}>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-[720px] max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-white">实例诊断</h3>
              <button onClick={() => setDiagId("")} className="text-gray-500 hover:text-gray-300">✕</button>
            </div>

            {diagLoading ? (
              <div className="text-sm text-gray-500 text-center py-8">加载中...</div>
            ) : diagData ? (
              <div className="space-y-3 text-xs">
                {/* Row 1: Basic Info + HXA */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">基本信息</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">实例名</span><span className="text-gray-200">{diagData.basic_info?.name}</span>
                      <span className="text-gray-500">产品</span><span className="text-gray-200 capitalize">{diagData.basic_info?.product}</span>
                      <span className="text-gray-500">ID</span><span className="text-gray-200 font-mono text-[10px]">{diagData.basic_info?.instance_id}</span>
                      <span className="text-gray-500">所有者</span><span className="text-gray-200 truncate">{diagData.basic_info?.owner_name}</span>
                      <span className="text-gray-500">状态</span><span className="text-gray-200">{diagData.basic_info?.install_state} / {diagData.basic_info?.status}</span>
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">HXA 插件</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">安装</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.hxa_plugin?.installed} /> {diagData.hxa_plugin?.installed ? "已安装" : "未安装"}</span>
                      <span className="text-gray-500">状态</span><span className="text-gray-200">{diagData.hxa_plugin?.status || "-"}</span>
                      <span className="text-gray-500">Agent</span><span className="text-green-400 truncate">{diagData.hxa_plugin?.agent_name || "-"}</span>
                      <span className="text-gray-500">组织</span><span className="text-gray-200 font-mono text-[10px] truncate">{diagData.hxa_plugin?.org_id ? diagData.hxa_plugin.org_id.substring(0, 12) + "..." : "-"}</span>
                    </div>
                  </div>
                </div>

                {/* Row 2: Telegram + Claude */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">Telegram</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">已配置</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.telegram?.configured} /> {diagData.telegram?.configured ? "是" : "否"}</span>
                      <span className="text-gray-500">Token</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.telegram?.bot_token_set} /> {diagData.telegram?.bot_token_set ? "已设置" : "未设置"}</span>
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2 flex items-center gap-1">
                      Claude
                      {diagData.claude?.command_line && (
                        <button onClick={() => alert(diagData.claude.command_line)}
                          className="text-gray-600 hover:text-gray-400 text-[10px]" title="查看完整命令">ℹ️</button>
                      )}
                    </h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">状态</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.claude?.running} /> {diagData.claude?.running ? "运行中" : "未运行"}</span>
                      <span className="text-gray-500">PID</span><span className="text-gray-200">{diagData.claude?.pid ?? "-"}</span>
                      <span className="text-gray-500">运行</span><span className="text-gray-200">{formatUptime(diagData.claude?.uptime_seconds)}</span>
                      <span className="text-gray-500">内存</span><span className="text-gray-200">{diagData.claude?.memory_mb ? `${diagData.claude.memory_mb} MB` : "-"}</span>
                    </div>
                  </div>
                </div>

                {/* Row 3: Container + Resource Usage */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">容器</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">状态</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.container?.running} /> {diagData.container?.running ? "运行中" : "已停止"}</span>
                      <span className="text-gray-500">磁盘</span><span className="text-gray-200">{diagData.container?.disk_usage_mb ? `${diagData.container.disk_usage_mb} MB` : "-"}</span>
                      <span className="text-gray-500">内存限制</span><span className="text-gray-200">{diagData.container?.memory_limit_mb ? `${diagData.container.memory_limit_mb} MB` : "无限制"}</span>
                      <span className="text-gray-500">CPU 限制</span><span className="text-gray-200">{diagData.container?.cpu_limit ? `${diagData.container.cpu_limit} 核` : "无限制"}</span>
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">资源使用</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">CPU</span>
                      <span className="text-gray-200">{diagData.resource_usage?.cpu_percent != null ? `${diagData.resource_usage.cpu_percent}%` : "-"}</span>
                      <span className="text-gray-500">内存</span>
                      <span className="text-gray-200">
                        {diagData.resource_usage?.mem_used_mb != null
                          ? `${diagData.resource_usage.mem_used_mb} MB / ${diagData.resource_usage.mem_total_mb ?? "?"} MB`
                          : "-"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Row 4: Resource Limits */}
                <div className="bg-gray-800/50 rounded p-3">
                  <h4 className="text-gray-400 font-medium mb-2">资源限制设置</h4>
                  <div className="flex items-center gap-4 flex-wrap">
                    <div className="flex items-center gap-2">
                      <label className="text-gray-500">CPU</label>
                      <input type="number" min={0.5} max={32} step={0.5} value={resCpus}
                        onChange={(e) => setResCpus(parseFloat(e.target.value) || 1)}
                        className="w-20 text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200 focus:outline-none focus:border-gray-500" />
                      <span className="text-gray-600">核</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-gray-500">内存</label>
                      <input type="number" min={256} max={65536} step={256} value={resMemory}
                        onChange={(e) => setResMemory(parseInt(e.target.value) || 1024)}
                        className="w-24 text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200 focus:outline-none focus:border-gray-500" />
                      <span className="text-gray-600">MB</span>
                    </div>
                    <button onClick={async () => {
                      setResSaving(true); setResMsg("");
                      try {
                        const res = await api.adminInstanceResources(diagId, resMemory, resCpus);
                        setResMsg(res.ok ? "已应用" : (res.detail || "失败"));
                        const data = await api.adminInstanceDiagnostics(diagId);
                        setDiagData(data);
                      } catch (e: unknown) { setResMsg((e as Error).message || "操作失败"); }
                      setResSaving(false);
                    }} disabled={resSaving}
                      className="px-3 py-1 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
                      {resSaving ? "..." : "应用"}
                    </button>
                    {resMsg && <span className={`text-xs ${resMsg === "已应用" ? "text-green-400" : "text-red-400"}`}>{resMsg}</span>}
                  </div>
                </div>

                {/* Control buttons */}
                <div className="flex gap-2 pt-2 border-t border-gray-800">
                  <button onClick={() => handleControl(diagId, "restart")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
                    {controlLoading === "restart" ? "..." : "重启"}
                  </button>
                  <button onClick={() => handleControl(diagId, "stop")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-red-600 hover:bg-red-500 text-white disabled:opacity-50">
                    {controlLoading === "stop" ? "..." : "停止"}
                  </button>
                  <button onClick={() => handleControl(diagId, "start")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-green-600 hover:bg-green-500 text-white disabled:opacity-50">
                    {controlLoading === "start" ? "..." : "启动"}
                  </button>
                  <button onClick={() => handleControl(diagId, "kill_claude")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-50">
                    {controlLoading === "kill_claude" ? "..." : "杀掉 Claude"}
                  </button>
                  <button onClick={async () => {
                    setDiagLoading(true);
                    try { setDiagData(await api.adminInstanceDiagnostics(diagId)); } catch {}
                    setDiagLoading(false);
                  }} className="ml-auto px-3 py-1.5 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800">
                    刷新
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-sm text-gray-500 text-center py-8">无数据</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
