import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import { useEffect, useState, useRef, useCallback } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { AdminUserInstances, DockerContainerGroup, HxaOrg, Instance, User } from "../types";

const AdminHXAPage = lazy(() => import("./AdminHXAPage"));
const AdminSettingsPage = lazy(() => import("./AdminSettingsPage"));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type DiagData = Record<string, any>;

function StatusDot({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="inline-block w-2 h-2 rounded-full bg-gray-600" />;
  return <span className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-green-400" : "bg-red-500"}`} />;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ZylosConfigPanel({ config, instanceId, onUpdated }: { config: any; instanceId: string; onUpdated: () => void }) {
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const amDefaults = config.am_defaults || {};
  const values = config.values || {};

  // Editable fields: keys that are marked configurable OR the known hardcoded ones we want to expose
  const t = useT();
  const editableKeys = [
    { key: "periodic_probe_interval", label: "定期探针间隔", hardcoded: 180 },
    { key: "health_check_interval", label: "健康检查间隔", hardcoded: 21600 },
    { key: "heartbeat_interval", label: "心跳安全网间隔", hardcoded: 7200 },
    { key: "usage_check_interval", label: "用量检查间隔", hardcoded: 3600 },
  ];

  const [drafts, setDrafts] = useState<Record<string, string>>(() => {
    const d: Record<string, string> = {};
    for (const { key, hardcoded } of editableKeys) {
      d[key] = String(values[key] ?? hardcoded);
    }
    return d;
  });

  async function handleSave(restart: boolean) {
    setSaving(true); setMsg("");
    const updates: Record<string, number> = {};
    for (const { key } of editableKeys) {
      const v = parseInt(drafts[key]);
      if (!isNaN(v) && v > 0) updates[key] = v;
    }
    try {
      const r = await api.adminZylosConfig(instanceId, updates, restart);
      const msgs: string[] = [];
      if (r.patched) msgs.push(t("admin.patchedAuto"));
      msgs.push(restart ? t("admin.pm2Restarted") : t("admin.savedNeedRestart"));
      setMsg(msgs.join("，"));
      onUpdated();
    } catch (e: unknown) {
      setMsg((e as Error).message || t("admin.saveFailed"));
    }
    setSaving(false);
  }

  function formatInterval(sec: number): string {
    if (sec >= 3600) return t("admin.hours", { n: (sec / 3600).toFixed(sec % 3600 ? 1 : 0) });
    if (sec >= 60) return t("admin.minutes", { n: Math.floor(sec / 60) });
    return t("admin.secs", { n: sec });
  }

  return (
    <div className="bg-gray-800/50 rounded p-3">
      <h4 className="text-gray-400 font-medium mb-2 text-xs">{t("admin.activityMonitorConfig")}
        <span className="text-gray-600 ml-2 font-mono text-[10px]">{config.path}</span>
      </h4>
      <div className="space-y-2">
        {editableKeys.map(({ key, label, hardcoded }) => {
          const meta = amDefaults[key];
          const currentVal = parseInt(drafts[key]) || hardcoded;
          return (
            <div key={key} className="flex items-center gap-2 text-xs">
              <span className="text-gray-400 w-32 shrink-0">{label}</span>
              <input type="number" min={10} value={drafts[key]}
                onChange={(e) => setDrafts(prev => ({ ...prev, [key]: e.target.value }))}
                className="w-24 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-200 focus:outline-none focus:border-gray-500" />
              <span className="text-gray-600">{t("admin.seconds")}</span>
              <span className="text-gray-600">= {formatInterval(currentVal)}</span>
              {meta && <span className="text-gray-700 text-[10px]">{t("admin.default", { value: meta.default })}</span>}
            </div>
          );
        })}
        <div className="flex items-center gap-2 pt-1">
          <button onClick={() => handleSave(false)} disabled={saving}
            className="px-3 py-1 text-xs rounded border border-gray-600 text-gray-300 hover:bg-gray-700 disabled:opacity-50">
            {saving ? "..." : t("admin.saveOnly")}
          </button>
          <button onClick={() => handleSave(true)} disabled={saving}
            className="px-3 py-1 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50">
            {saving ? "..." : t("admin.saveAndRestart")}
          </button>
          {msg && <span className={`text-xs ${msg.includes("生效") || msg.includes("patch") ? "text-green-400" : msg.startsWith("已") ? "text-green-400" : "text-red-400"}`}>{msg}</span>}
        </div>
        <p className="text-gray-600 text-[10px]">⚠️ periodic_probe_interval 是费 token 的主因（每次探针触发 Claude 回应）。建议设为 600+ 秒。保存时会自动 patch 源码让硬编码常量读 config.json，"保存并重启"立即生效。</p>
      </div>
    </div>
  );
}

export function AdminPage() {
  const t = useT();
  const [users, setUsers] = useState<User[]>([]);
  const [userSearch, setUserSearch] = useState("");
  const [selectedUserId, _setSelectedUserId] = useState<string>(() => {
    const hash = window.location.hash.replace("#", "");
    return hash.startsWith("user/") ? hash.slice(5) : "";
  });
  const setSelectedUserId = (id: string) => {
    _setSelectedUserId(id);
    window.location.hash = id ? `user/${id}` : "";
  };
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

  // Tab state
  const [activeTab, setActiveTab] = useState<"instances" | "docker" | "hxa" | "users" | "settings">(() => {
    const hash = window.location.hash;
    if (hash === "#docker") return "docker";
    if (hash === "#hxa") return "hxa";
    if (hash === "#users") return "users";
    if (hash === "#settings") return "settings";
    return "instances";
  });

  // User management tab
  type UserStat = { id: string; name: string; email: string; is_admin: number; created_at: string; last_login_at: string | null; instance_count: number; running_count: number };
  const [userStats, setUserStats] = useState<UserStat[]>([]);
  const [userStatsLoading, setUserStatsLoading] = useState(false);

  // HXA online status
  const [hxaStatus, setHxaStatus] = useState<Record<string, { online: boolean; org_id: string; agent_name: string }>>({});
  const [hxaRestarting, setHxaRestarting] = useState("");

  // Docker management
  const [dockerGroups, setDockerGroups] = useState<DockerContainerGroup[]>([]);
  const [dockerLoading, setDockerLoading] = useState(false);
  const [cleaningProject, setCleaningProject] = useState("");
  const [dockerMenuProject, setDockerMenuProject] = useState("");
  const dockerMenuRef = useRef<HTMLDivElement>(null);
  const [dockerDiagId, setDockerDiagId] = useState("");
  const [dockerDiagData, setDockerDiagData] = useState<DiagData | null>(null);
  const [dockerDiagLoading, setDockerDiagLoading] = useState(false);

  // Resource limits form
  const [resMemory, setResMemory] = useState(8192);
  const [resCpus, setResCpus] = useState(4);
  const [resSaving, setResSaving] = useState(false);
  const [resMsg, setResMsg] = useState("");

  // Close menu on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuId("");
      if (dockerMenuRef.current && !dockerMenuRef.current.contains(e.target as Node)) setDockerMenuProject("");
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => {
    api.adminUsers()
      .then((rows) => {
        setUsers(rows);
        // Restore from hash or default to first user
        const hashId = window.location.hash.replace("#user/", "");
        const hasValidHash = hashId && rows.some((u) => u.id === hashId);
        if (hasValidHash) _setSelectedUserId(hashId);
        else if (rows.length > 0) setSelectedUserId(rows[0].id);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : t("admin.loadFailed")))
      .finally(() => setLoadingUsers(false));

    api.hxaOrgs().then((r) => setOrgs(r.orgs || [])).catch(() => {});
    api.adminHxaStatus().then(setHxaStatus).catch(() => {});
  }, [t]);

  // Load user stats for user management tab
  useEffect(() => {
    if (activeTab !== "users") return;
    setUserStatsLoading(true);
    api.adminUsersStats()
      .then(setUserStats)
      .catch(() => {})
      .finally(() => setUserStatsLoading(false));
  }, [activeTab]);

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
    if (!confirm(t("admin.confirmTransfer", { name: inst.agent_name || "", target: targetName }))) return;
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
    const labels: Record<string, string> = { stop: t("admin.actionStop"), start: t("admin.actionStart"), restart: t("admin.actionRestart"), kill_claude: t("admin.actionKillClaude") };
    if (!confirm(`${labels[action] || action}?`)) return;
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

  const loadDockerContainers = useCallback(async () => {
    setDockerLoading(true);
    try {
      const r = await api.adminDockerContainers();
      setDockerGroups(r.groups || []);
    } catch { /* ignore */ }
    setDockerLoading(false);
  }, []);

  useEffect(() => {
    if (activeTab === "docker") loadDockerContainers();
  }, [activeTab, loadDockerContainers]);

  async function openDockerDiag(instanceId: string) {
    setDockerDiagId(instanceId);
    setDockerDiagLoading(true);
    setDockerDiagData(null);
    setDockerMenuProject("");
    try {
      const data = await api.adminInstanceDiagnostics(instanceId);
      setDockerDiagData(data);
    } catch (e: unknown) {
      alert((e as Error).message || "加载失败");
      setDockerDiagId("");
    }
    setDockerDiagLoading(false);
  }

  async function handleDockerCleanup(project: string) {
    if (!confirm(`确定要清理 "${project}"？将停止并删除所有相关容器和 runtime 目录。此操作不可撤销！`)) return;
    setCleaningProject(project);
    try {
      const r = await api.adminDockerCleanup(project);
      alert(r.details?.join("\n") || "清理完成");
      loadDockerContainers();
    } catch (e: unknown) {
      alert((e as Error).message || "清理失败");
    }
    setCleaningProject("");
  }

  function formatUptime(seconds: number | null): string {
    if (seconds === null || seconds === undefined) return "-";
    if (seconds < 60) return t("admin.secs", { n: seconds });
    if (seconds < 3600) return t("admin.minutes", { n: Math.floor(seconds / 60) });
    if (seconds < 86400) return t("admin.hoursMin", { h: Math.floor(seconds / 3600), m: Math.floor((seconds % 3600) / 60) });
    return t("admin.days", { n: Math.floor(seconds / 86400), h: Math.floor((seconds % 86400) / 3600) });
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-white">{t("admin.title")}</h1>
        {/* Tab bar */}
        <div className="flex gap-1 mt-3 border-b border-gray-800">
          {([
            ["instances", t("admin.instancesTab")],
            ["docker", "Docker " + t("admin.management")],
            ["hxa", t("admin.hxaTab")],
            ["users", t("admin.usersTab")],
            ["settings", t("admin.settingsTab")],
          ] as const).map(([key, label]) => (
            <button key={key} onClick={() => { setActiveTab(key); window.location.hash = key === "instances" ? "" : key; }}
              className={`px-4 py-1.5 text-sm rounded-t ${activeTab === key ? "bg-gray-800 text-white border border-gray-700 border-b-0" : "text-gray-500 hover:text-gray-300"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="mb-4 p-3 text-sm rounded bg-red-900/40 border border-red-700 text-red-300">{error}</div>}

      {/* ── Docker Tab ── */}
      {activeTab === "docker" && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm text-gray-400">
              {t("admin.totalGroups", { count: dockerGroups.length })}
              {" · "}
              <span className="text-amber-400 font-medium">{dockerGroups.filter(g => g.is_orphan).length}</span> {t("admin.orphan")}
              {" · "}
              <span className="text-purple-400 font-medium">{dockerGroups.filter(g => g.is_ghost).length}</span> {t("admin.ghost")}
              {" · "}
              <span className="text-gray-500">{dockerGroups.filter(g => g.containers.length > 0 && g.containers.every(c => c.state !== "running")).length}</span> {t("status.stopped")}
            </div>
            <button onClick={loadDockerContainers} disabled={dockerLoading}
              className="px-3 py-1 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800 disabled:opacity-50">
              {dockerLoading ? t("common.loading") : "🔄 " + t("session.refresh")}
            </button>
          </div>

          {dockerLoading && dockerGroups.length === 0 ? (
            <div className="text-sm text-gray-500 text-center py-8">{t("common.loading")}</div>
          ) : dockerGroups.length === 0 ? (
            <div className="text-sm text-gray-500 text-center py-8">{t("admin.noContainers")}</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="text-left pb-2 w-8"></th>
                  <th className="text-left pb-2">{t("admin.containerGroups")}</th>
                  <th className="text-left pb-2">{t("admin.product")}</th>
                  <th className="text-left pb-2">{t("admin.linkedInstance")}</th>
                  <th className="text-left pb-2">{t("admin.owner")}</th>
                  <th className="text-left pb-2">Runtime</th>
                  <th className="text-left pb-2">{t("admin.containers")}</th>
                  <th className="text-right pb-2">{t("adminHxa.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {dockerGroups.map((g) => {
                  const isRunning = g.containers.some(c => c.state === "running");
                  const isOrphanDir = g.project.startsWith("dir:");
                  return (
                    <tr key={g.project}
                      className={`border-b border-gray-800/50 ${g.is_orphan ? "border-l-2 border-l-amber-500 bg-amber-900/10" : g.is_ghost ? "border-l-2 border-l-purple-500 bg-purple-900/10" : ""}`}>
                      <td className="py-2 pl-2">
                        {g.is_ghost ? (
                          <span className="inline-block w-2 h-2 rounded-full bg-purple-500" title={t("admin.ghost")} />
                        ) : isOrphanDir ? (
                          <span className="inline-block w-2 h-2 rounded-full bg-gray-600" title={t("admin.dirOnly")} />
                        ) : (
                          <span className={`inline-block w-2 h-2 rounded-full ${isRunning ? "bg-green-400" : "bg-gray-600"}`}
                            title={isRunning ? t("status.running") : t("status.stopped")} />
                        )}
                      </td>
                      <td className="py-2">
                        <span className="text-gray-200 text-xs font-mono">
                          {isOrphanDir ? g.project.slice(4) : g.project}
                        </span>
                      </td>
                      <td className="py-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${g.product === "openclaw" ? "bg-blue-900/40 text-blue-300" : g.product === "zylos" ? "bg-purple-900/40 text-purple-300" : g.product === "hermes" ? "bg-green-900/40 text-green-300" : "bg-gray-800 text-gray-500"}`}>
                          {g.product === "openclaw" ? "OC" : g.product === "zylos" ? "ZY" : g.product === "hermes" ? "HM" : "?"}
                        </span>
                      </td>
                      <td className="py-2">
                        {g.instance_id ? (
                          <Link to={`/instances/${g.instance_id}`} className="text-blue-400 hover:text-blue-300 text-xs">
                            {g.instance_name || g.instance_id}
                          </Link>
                        ) : (
                          <span className="text-amber-400 text-xs">无关联</span>
                        )}
                      </td>
                      <td className="py-2 text-gray-400 text-xs">{g.owner_email || "-"}</td>
                      <td className="py-2">
                        {g.runtime_exists ? (
                          <span className="text-green-400 text-xs" title={g.runtime_dir || ""}>{t("admin.exists")}</span>
                        ) : g.runtime_dir ? (
                          <span className="text-red-400 text-xs">{t("admin.notExists")}</span>
                        ) : (
                          <span className="text-gray-600 text-xs">-</span>
                        )}
                      </td>
                      <td className="py-2 text-xs text-gray-500">
                        {g.containers.map(c => (
                          <div key={c.name} className="truncate max-w-[180px]" title={`${c.name} - ${c.status}`}>
                            <span className={c.state === "running" ? "text-green-400" : "text-gray-600"}>●</span>{" "}
                            {c.name.replace(g.project + "-", "").replace(g.project, "(main)")} <span className="text-gray-700">{c.status}</span>
                          </div>
                        ))}
                        {g.containers.length === 0 && <span className="text-gray-700">{g.is_ghost ? t("admin.noContainers") : t("admin.dirOnly")}</span>}
                      </td>
                      <td className="py-2 text-right relative">
                        <button onClick={() => setDockerMenuProject(dockerMenuProject === g.project ? "" : g.project)}
                          className="px-2 py-1 text-gray-400 hover:text-white text-sm">⋯</button>
                        {dockerMenuProject === g.project && (
                          <div ref={dockerMenuRef}
                            className="absolute right-0 top-8 z-30 bg-gray-800 border border-gray-700 rounded shadow-lg py-1 min-w-[120px]">
                            {g.instance_id && (
                              <>
                                <button onClick={() => openDockerDiag(g.instance_id!)}
                                  className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">
                                  {t("admin.details")}
                                </button>
                                <Link to={`/instances/${g.instance_id}`} onClick={() => setDockerMenuProject("")}
                                  className="block px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">
                                  {t("admin.goToInstance")}
                                </Link>
                              </>
                            )}
                            {(g.is_orphan || g.is_ghost) && (
                              <button onClick={() => { setDockerMenuProject(""); handleDockerCleanup(g.project); }}
                                disabled={cleaningProject === g.project}
                                className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-gray-700 disabled:opacity-50">
                                🗑 {cleaningProject === g.project ? t("common.loading") : g.is_ghost ? t("admin.cleanGhost") : t("admin.clean")}
                              </button>
                            )}
                            {!g.instance_id && !g.is_orphan && !g.is_ghost && (
                              <div className="px-3 py-1.5 text-xs text-gray-600">{t("admin.noAction")}</div>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Docker Diagnostics Modal */}
      {dockerDiagId && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setDockerDiagId("")}>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-[680px] max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-white">{t("admin.diagnostics")}</h3>
              <button onClick={() => setDockerDiagId("")} className="text-gray-500 hover:text-white text-lg">✕</button>
            </div>
            {dockerDiagLoading ? (
              <div className="text-sm text-gray-500 text-center py-8">{t("common.loading")}</div>
            ) : dockerDiagData ? (
              <div className="space-y-3">
                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2 text-xs">{t("admin.basicInfo")}</h4>
                    <div className="space-y-1 text-xs">
                      <div><span className="text-gray-500">{t("admin.instanceName")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.basic_info?.name}</span></div>
                      <div><span className="text-gray-500">{t("admin.product")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.basic_info?.product}</span></div>
                      <div><span className="text-gray-500">ID</span> <span className="text-gray-200 ml-2 font-mono">{dockerDiagData.basic_info?.instance_id}</span></div>
                      <div><span className="text-gray-500">{t("admin.owner")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.basic_info?.owner_name}</span></div>
                      <div><span className="text-gray-500">{t("admin.state")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.basic_info?.install_state} / {dockerDiagData.basic_info?.status}</span></div>
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2 text-xs">{t("admin.hxaPlugin")}</h4>
                    <div className="space-y-1 text-xs">
                      <div><span className="text-gray-500">{t("admin.state")}</span> <StatusDot ok={dockerDiagData.hxa_plugin?.installed} /> <span className="ml-1">{dockerDiagData.hxa_plugin?.installed ? t("admin.installed") : t("admin.notInstalled")}</span></div>
                      <div><span className="text-gray-500">状态</span> <span className="text-gray-200 ml-2">{dockerDiagData.hxa_plugin?.status}</span></div>
                      <div><span className="text-gray-500">Agent</span> <span className="text-blue-400 ml-2">{dockerDiagData.hxa_plugin?.agent_name || "-"}</span></div>
                      <div><span className="text-gray-500">组织</span> <span className="text-gray-200 ml-2 font-mono text-[10px]">{dockerDiagData.hxa_plugin?.org_id || "-"}</span></div>
                    </div>
                  </div>
                </div>
                {/* Container + Resources */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2 text-xs">{t("admin.container")}</h4>
                    <div className="space-y-1 text-xs">
                      <div><span className="text-gray-500">{t("admin.state")}</span> <StatusDot ok={dockerDiagData.container?.running} /> <span className="ml-1">{dockerDiagData.container?.running ? t("status.running") : t("status.stopped")}</span></div>
                      <div><span className="text-gray-500">{t("admin.disk")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.container?.disk_usage_mb ?? "-"} MB</span></div>
                      <div><span className="text-gray-500">{t("admin.memLimit")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.container?.memory_limit_mb ?? "-"} MB</span></div>
                      <div><span className="text-gray-500">{t("admin.cpuLimit")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.container?.cpu_limit ?? "-"} 核</span></div>
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2 text-xs">{t("admin.resourceUsage")}</h4>
                    <div className="space-y-1 text-xs">
                      <div><span className="text-gray-500">{t("admin.cpu")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.resource_usage?.cpu_percent ?? "-"}%</span></div>
                      <div><span className="text-gray-500">{t("admin.mem")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.resource_usage?.mem_used_mb ?? "-"} MB / {dockerDiagData.resource_usage?.mem_total_mb ?? "-"} MB</span></div>
                    </div>
                  </div>
                </div>
                {/* Config Files */}
                <div className="bg-gray-800/50 rounded p-3">
                  <h4 className="text-gray-400 font-medium mb-2 text-xs">{t("admin.configFiles")}</h4>
                  <div className="space-y-1 text-xs">
                    <div><span className="text-gray-500">{t("admin.runtimeDir")}</span> <span className="text-gray-200 ml-2 font-mono text-[10px]">{dockerDiagData.runtime_dir || "-"}</span></div>
                    {(dockerDiagData.config_files || []).length > 0 ? (
                      (dockerDiagData.config_files as { label: string; path: string }[]).map((f) => (
                        <div key={f.path}>
                          <span className="text-green-400">✓</span> <span className="text-gray-400">{f.label}</span>
                          <span className="text-gray-600 ml-2 font-mono text-[10px]">{f.path}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-gray-600">无配置文件</div>
                    )}
                  </div>
                </div>
                {/* Claude */}
                <div className="bg-gray-800/50 rounded p-3">
                  <h4 className="text-gray-400 font-medium mb-2 text-xs">Claude 进程</h4>
                  <div className="space-y-1 text-xs">
                    <div><span className="text-gray-500">{t("admin.state")}</span> <StatusDot ok={dockerDiagData.claude?.running} /> <span className="ml-1">{dockerDiagData.claude?.running ? t("status.running") : t("status.stopped")}</span></div>
                    {dockerDiagData.claude?.running && (
                      <>
                        <div><span className="text-gray-500">PID</span> <span className="text-gray-200 ml-2">{dockerDiagData.claude?.pid || "-"}</span></div>
                        <div><span className="text-gray-500">{t("admin.mem")}</span> <span className="text-gray-200 ml-2">{dockerDiagData.claude?.memory_mb || "-"} MB</span></div>
                      </>
                    )}
                  </div>
                </div>
                {/* Zylos Activity Monitor Config */}
                {dockerDiagData.zylos_config && <ZylosConfigPanel config={dockerDiagData.zylos_config} instanceId={dockerDiagId} onUpdated={async () => {
                  try { setDockerDiagData(await api.adminInstanceDiagnostics(dockerDiagId)); } catch {}
                }} />}
              </div>
            ) : (
              <div className="text-sm text-gray-500 text-center py-8">无数据</div>
            )}
          </div>
        </div>
      )}

      {/* ── Instances Tab (was Users Tab) ── */}
      {activeTab === "instances" && <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
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
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("instances.org")}</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">{t("instances.orgName")}</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">TG</th>
                        <th className="text-left py-2 pr-3 text-xs text-gray-500">HXA</th>
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
                          <td className="py-2 pr-3">
                            {(() => {
                              const s = hxaStatus[i.id];
                              if (!s) return <span className="text-gray-600 text-xs">-</span>;
                              return (
                                <span className="inline-flex items-center gap-1">
                                  <span className={`inline-block w-2 h-2 rounded-full ${s.online ? "bg-green-400" : "bg-gray-500"}`} />
                                  {!s.online && i.install_state === "running" && (
                                    <button
                                      onClick={async () => {
                                        setHxaRestarting(i.id);
                                        try {
                                          await api.adminInstanceControl(i.id, "restart_hxa");
                                          // Refresh status after a short delay
                                          setTimeout(() => {
                                            api.adminHxaStatus().then(setHxaStatus).catch(() => {});
                                            setHxaRestarting("");
                                          }, 3000);
                                        } catch {
                                          setHxaRestarting("");
                                        }
                                      }}
                                      disabled={hxaRestarting === i.id}
                                      className="text-[10px] text-yellow-400 hover:text-yellow-300 disabled:opacity-50"
                                    >
                                      {hxaRestarting === i.id ? "..." : "使在线"}
                                    </button>
                                  )}
                                </span>
                              );
                            })()}
                          </td>
                          <td className="py-2 pr-3 text-gray-500 text-xs">{new Date(i.created_at).toLocaleString()}</td>
                          <td className="py-2 text-right relative">
                            {/* Transfer mode */}
                            {transferId === i.id ? (
                              <div className="inline-flex items-center gap-1">
                                <select value={transferTarget} onChange={(e) => setTransferTarget(e.target.value)}
                                  className="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded px-1 py-0.5">
                                  <option value="">{t("adminHxa.transferTo")}</option>
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
                                      className="block w-full text-left px-3 py-1.5 text-xs text-gray-200 hover:bg-gray-700">{t("admin.details")}</button>
                                    <Link to={`/instances/${i.id}`} onClick={() => setMenuId("")}
                                      className="block w-full text-left px-3 py-1.5 text-xs text-blue-400 hover:bg-gray-700">{t("admin.goToInstance")}</Link>
                                    {i.agent_name && orgs.length > 1 && (
                                      <button onClick={() => { setTransferId(i.id); setMenuId(""); }}
                                        className="block w-full text-left px-3 py-1.5 text-xs text-yellow-400 hover:bg-gray-700">{t("adminHxa.transfer")}</button>
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
      </div>}

      {/* Diagnostics Modal */}
      {diagId && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center" onClick={() => setDiagId("")}>
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-[720px] max-h-[80vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-white">{t("admin.diagnostics")}</h3>
              <button onClick={() => setDiagId("")} className="text-gray-500 hover:text-gray-300">✕</button>
            </div>

            {diagLoading ? (
              <div className="text-sm text-gray-500 text-center py-8">{t("common.loading")}</div>
            ) : diagData ? (
              <div className="space-y-3 text-xs">
                {/* Row 1: Basic Info + HXA */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">{t("admin.basicInfo")}</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">{t("admin.instanceName")}</span><span className="text-gray-200">{diagData.basic_info?.name}</span>
                      <span className="text-gray-500">{t("admin.product")}</span><span className="text-gray-200 capitalize">{diagData.basic_info?.product}</span>
                      <span className="text-gray-500">ID</span><span className="text-gray-200 font-mono text-[10px]">{diagData.basic_info?.instance_id}</span>
                      <span className="text-gray-500">{t("admin.owner")}</span><span className="text-gray-200 truncate">{diagData.basic_info?.owner_name}</span>
                      <span className="text-gray-500">状态</span><span className="text-gray-200">{diagData.basic_info?.install_state} / {diagData.basic_info?.status}</span>
                      {(diagData.openclaw_version || diagData.zylos_version) && (<>
                        <span className="text-gray-500">版本</span>
                        <span className="text-gray-200 flex items-center gap-2">
                          {diagData.openclaw_version || diagData.zylos_version}
                          {diagData.openclaw_version && <button
                            onClick={async () => {
                              if (!diagData.basic_info?.instance_id) return;
                              try {
                                const r = await api.adminInstanceControl(diagData.basic_info?.instance_id, "upgrade");
                                alert(r.ok ? `升级成功！新版本: ${r.new_version || "unknown"}` : `升级失败: ${r.detail}`);
                                const fresh = await api.adminInstanceDiagnostics(diagData.basic_info?.instance_id);
                                setDiagData(fresh);
                              } catch (e: unknown) { alert((e as Error).message); }
                            }}
                            className="text-[10px] px-2 py-0.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded"
                          >升级</button>}
                        </span>
                      </>)}
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">{t("admin.hxaPlugin")}</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">{t("admin.state")}</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.hxa_plugin?.installed} /> {diagData.hxa_plugin?.installed ? t("admin.installed") : t("admin.notInstalled")}</span>
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
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.claude?.running} /> {diagData.claude?.running ? t("status.running") : t("status.stopped")}</span>
                      <span className="text-gray-500">PID</span><span className="text-gray-200">{diagData.claude?.pid ?? "-"}</span>
                      <span className="text-gray-500">Uptime</span><span className="text-gray-200">{formatUptime(diagData.claude?.uptime_seconds)}</span>
                      <span className="text-gray-500">{t("admin.mem")}</span><span className="text-gray-200">{diagData.claude?.memory_mb ? `${diagData.claude.memory_mb} MB` : "-"}</span>
                    </div>
                  </div>
                </div>

                {/* Row 3: Container + Resource Usage */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">{t("admin.container")}</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">{t("admin.state")}</span>
                      <span className="flex items-center gap-1"><StatusDot ok={diagData.container?.running} /> {diagData.container?.running ? t("status.running") : t("status.stopped")}</span>
                      <span className="text-gray-500">{t("admin.disk")}</span><span className="text-gray-200">{diagData.container?.disk_usage_mb ? `${diagData.container.disk_usage_mb} MB` : "-"}</span>
                      <span className="text-gray-500">{t("admin.memLimit")}</span><span className="text-gray-200">{diagData.container?.memory_limit_mb ? `${diagData.container.memory_limit_mb} MB` : "-"}</span>
                      <span className="text-gray-500">{t("admin.cpuLimit")}</span><span className="text-gray-200">{diagData.container?.cpu_limit ? `${diagData.container.cpu_limit}` : "-"}</span>
                    </div>
                  </div>
                  <div className="bg-gray-800/50 rounded p-3">
                    <h4 className="text-gray-400 font-medium mb-2">{t("admin.resourceUsage")}</h4>
                    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                      <span className="text-gray-500">{t("admin.cpu")}</span>
                      <span className="text-gray-200">{diagData.resource_usage?.cpu_percent != null ? `${diagData.resource_usage.cpu_percent}%` : "-"}</span>
                      <span className="text-gray-500">{t("admin.mem")}</span>
                      <span className="text-gray-200">
                        {diagData.resource_usage?.mem_used_mb != null
                          ? `${diagData.resource_usage.mem_used_mb} MB / ${diagData.resource_usage.mem_total_mb ?? "?"} MB`
                          : "-"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Zylos Activity Monitor Config */}
                {diagData?.zylos_config && <ZylosConfigPanel config={diagData.zylos_config} instanceId={diagId} onUpdated={async () => {
                  try { setDiagData(await api.adminInstanceDiagnostics(diagId)); } catch {}
                }} />}

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
                    {controlLoading === "restart" ? "..." : t("admin.actionRestart")}
                  </button>
                  <button onClick={() => handleControl(diagId, "stop")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-red-600 hover:bg-red-500 text-white disabled:opacity-50">
                    {controlLoading === "stop" ? "..." : t("admin.actionStop")}
                  </button>
                  <button onClick={() => handleControl(diagId, "start")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-green-600 hover:bg-green-500 text-white disabled:opacity-50">
                    {controlLoading === "start" ? "..." : t("admin.actionStart")}
                  </button>
                  <button onClick={() => handleControl(diagId, "kill_claude")} disabled={!!controlLoading}
                    className="px-3 py-1.5 text-xs rounded bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-50">
                    {controlLoading === "kill_claude" ? "..." : t("admin.actionKillClaude")}
                  </button>
                  <button onClick={async () => {
                    setDiagLoading(true);
                    try { setDiagData(await api.adminInstanceDiagnostics(diagId)); } catch {}
                    setDiagLoading(false);
                  }} className="ml-auto px-3 py-1.5 text-xs rounded border border-gray-700 text-gray-300 hover:bg-gray-800">
                    {t("session.refresh")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-sm text-gray-500 text-center py-8">-</div>
            )}
          </div>
        </div>
      )}

      {/* ── Users Management Tab ── */}
      {activeTab === "users" && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-3">{t("admin.usersTab")}</h2>
          {userStatsLoading ? (
            <div className="text-sm text-gray-500 py-8 text-center">{t("admin.loadingUsers")}</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left">
                  <th className="py-2 px-2 text-gray-400 font-medium">{t("admin.userName")}</th>
                  <th className="py-2 px-2 text-gray-400 font-medium">Email</th>
                  <th className="py-2 px-2 text-gray-400 font-medium text-center">{t("admin.role")}</th>
                  <th className="py-2 px-2 text-gray-400 font-medium text-center">{t("admin.instanceCount")}</th>
                  <th className="py-2 px-2 text-gray-400 font-medium text-center">{t("admin.runningCount")}</th>
                  <th className="py-2 px-2 text-gray-400 font-medium">{t("admin.lastLogin")}</th>
                  <th className="py-2 px-2 text-gray-400 font-medium">{t("admin.registered")}</th>
                </tr>
              </thead>
              <tbody>
                {userStats.map((u) => (
                  <tr key={u.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 px-2 text-gray-200">{u.name || u.email.split("@")[0]}</td>
                    <td className="py-2 px-2 text-gray-400 text-xs">{u.email}</td>
                    <td className="py-2 px-2 text-center">
                      {u.is_admin ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-700/50 text-amber-200">Admin</span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700/50 text-gray-400">User</span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-center text-gray-300">{u.instance_count}</td>
                    <td className="py-2 px-2 text-center">
                      {u.running_count > 0 ? (
                        <span className="text-green-400">{u.running_count}</span>
                      ) : (
                        <span className="text-gray-600">0</span>
                      )}
                    </td>
                    <td className="py-2 px-2 text-gray-400 text-xs">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "-"}</td>
                    <td className="py-2 px-2 text-gray-500 text-xs">{new Date(u.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── HXA Orgs Tab ── */}
      {activeTab === "hxa" && (
        <Suspense fallback={<div className="text-sm text-gray-500 py-8 text-center">Loading...</div>}>
          <AdminHXAPage />
        </Suspense>
      )}

      {/* ── Settings Tab ── */}
      {activeTab === "settings" && (
        <Suspense fallback={<div className="text-sm text-gray-500 py-8 text-center">Loading...</div>}>
          <AdminSettingsPage />
        </Suspense>
      )}
    </div>
  );
}
