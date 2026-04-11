import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { HxaOrg, Instance } from "../types";

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
  const t = useT();
  if (!inst.agent_name) return <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-400" title={t("instances.orgNotConfigured")} />;
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-400" title={t("instances.configured")} />;
}

// ─── Three-dot dropdown menu ────────────────────────────────────────

function ActionMenu({
  inst,
  onDelete,
  onRename,
  deleting,
}: {
  inst: Instance;
  onDelete: () => void;
  onRename: () => void;
  deleting: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const canRename = (inst.agent_name || "").startsWith("hire_");

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="p-1.5 text-gray-500 hover:text-gray-300 rounded transition-colors hover:bg-gray-800"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
          <circle cx="10" cy="4" r="1.5" />
          <circle cx="10" cy="10" r="1.5" />
          <circle cx="10" cy="16" r="1.5" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-20 w-32 bg-gray-800 border border-gray-700 rounded-lg shadow-lg py-1 text-xs">
          <Link
            to={`/instances/${inst.id}`}
            className="block px-3 py-2 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            onClick={() => setOpen(false)}
          >
            {t("instances.manage")}
          </Link>
          {canRename && (
            <button
              className="block w-full text-left px-3 py-2 text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
              onClick={() => { setOpen(false); onRename(); }}
            >
              {t("instances.rename")}
            </button>
          )}
          <button
            className="block w-full text-left px-3 py-2 text-rose-400 hover:bg-gray-700 hover:text-rose-300 transition-colors"
            disabled={deleting}
            onClick={() => { setOpen(false); onDelete(); }}
          >
            {deleting ? t("instances.deleting") : t("common.delete")}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Rename dialog ──────────────────────────────────────────────────

function RenameDialog({
  inst,
  onClose,
  onRenamed,
}: {
  inst: Instance;
  onClose: () => void;
  onRenamed: (id: string, newName: string) => void;
}) {
  const t = useT();
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSave() {
    const trimmed = name.trim();
    if (!trimmed || trimmed.length < 2) { setError(t("instances.nameMinLength")); return; }
    setSaving(true);
    setError("");
    try {
      const res = await api.renameAgent(inst.id, trimmed);
      onRenamed(inst.id, res.agent_name);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("instances.renameFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-5 w-80 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-medium text-white mb-3">{t("instances.renameTitle")}</h3>
        <p className="text-xs text-gray-500 mb-2">当前: <span className="font-mono text-gray-400">{inst.agent_name}</span></p>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("instances.namePlaceholder")}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-500 placeholder-gray-500"
          onKeyDown={(e) => e.key === "Enter" && handleSave()}
          autoFocus
        />
        <p className="text-[11px] text-gray-600 mt-1">{t("instances.nameHint")}</p>
        {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-300 px-3 py-1.5">{t("common.cancel")}</button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="text-xs bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white px-3 py-1.5 rounded transition-colors"
          >
            {saving ? t("instances.saving") : t("common.ok")}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Instance Card (Grid View) ──────────────────────────────────────

function InstanceCard({
  inst,
  onDelete,
  onRename,
  deleting,
}: {
  inst: Instance;
  onDelete: () => void;
  onRename: () => void;
  deleting: boolean;
}) {
  const navigate = useNavigate();
  const t = useT();
  const isRunning = inst.install_state === "running";
  const isConfigured = inst.is_telegram_configured && !!inst.agent_name;
  const productIcon = inst.product === "zylos" ? "🤖" : "🔷";
  const stateColor = isRunning ? "border-green-500/40" : inst.install_state === "failed" ? "border-red-500/40" : "border-gray-700";

  return (
    <div className={`bg-gray-900 border-2 ${stateColor} rounded-xl p-4 hover:bg-gray-800/60 transition-all group relative`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="cursor-pointer flex-1" onClick={() => navigate(`/instances/${inst.id}`)}>
          <div className="flex items-center gap-2">
            <span className="text-lg">{productIcon}</span>
            <span className="text-white font-medium text-sm hover:text-blue-400 transition-colors truncate">{inst.name}</span>
          </div>
          <div className="text-[10px] text-gray-600 font-mono mt-0.5 ml-7">{inst.id}</div>
        </div>
        <ActionMenu inst={inst} onDelete={onDelete} onRename={onRename} deleting={deleting} />
      </div>

      {/* Status badges */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        <span className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full ${isRunning ? "bg-green-900/40 text-green-400" : inst.install_state === "failed" ? "bg-red-900/40 text-red-400" : "bg-gray-800 text-gray-400"}`}>
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${isRunning ? "bg-green-400" : inst.install_state === "failed" ? "bg-red-400" : "bg-gray-500"}`} />
          {inst.install_state}
        </span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full ${isConfigured ? "bg-blue-900/30 text-blue-400" : "bg-amber-900/30 text-amber-400"}`}>
          {isConfigured ? t("instances.configured") : inst.agent_name ? t("instances.tgNotConfigured") : t("instances.orgNotConfigured")}
        </span>
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-800 text-gray-400 capitalize">{inst.product}</span>
      </div>

      {/* Info grid */}
      <div className="space-y-1.5 text-[11px]">
        {inst.agent_name && (
          <div className="flex justify-between">
            <span className="text-gray-500">Agent</span>
            <span className="text-green-400 font-mono truncate ml-2">{inst.agent_name}</span>
          </div>
        )}
        {inst.org_name && (
          <div className="flex justify-between">
            <span className="text-gray-500">{t("instances.org")}</span>
            <span className="text-blue-400 truncate ml-2">{inst.org_name}</span>
          </div>
        )}
        {inst.web_console_port && (
          <div className="flex justify-between">
            <span className="text-gray-500">{t("instances.ports")}</span>
            <span className="text-gray-300 font-mono">{inst.web_console_port}{inst.http_port ? ` / ${inst.http_port}` : ""}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-gray-500">{t("instances.deploy")}</span>
          <span className="text-gray-400">{formatDate(inst.created_at)}</span>
        </div>
      </div>

      {/* Quick actions bar */}
      <div className="mt-3 pt-3 border-t border-gray-800 flex items-center justify-between">
        <button onClick={() => navigate(`/instances/${inst.id}`)} className="text-[11px] text-blue-400 hover:text-blue-300">{t("instances.manage")}</button>
        <button onClick={() => navigate(`/instances/${inst.id}#chat`)} className="text-[11px] text-gray-500 hover:text-gray-300">💬 聊天</button>
      </div>
    </div>
  );
}

// ─── View toggle ────────────────────────────────────────────────────

function ViewToggle({ view, onChange }: { view: "list" | "grid"; onChange: (v: "list" | "grid") => void }) {
  return (
    <div className="flex bg-gray-800 rounded-md p-0.5">
      <button onClick={() => onChange("list")} className={`px-2.5 py-1 rounded text-xs transition-colors ${view === "list" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"}`} title="列表">
        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" /></svg>
      </button>
      <button onClick={() => onChange("grid")} className={`px-2.5 py-1 rounded text-xs transition-colors ${view === "grid" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"}`} title="网格">
        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" /></svg>
      </button>
    </div>
  );
}

// ─── Main page ──────────────────────────────────────────────────────

export function InstancesPage() {
  const t = useT();
  const navigate = useNavigate();
  const [instances, setInstances] = useState<Instance[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string>("");
  const [renamingInst, setRenamingInst] = useState<Instance | null>(null);
  const [orgs, setOrgs] = useState<HxaOrg[]>([]);
  const [viewMode, setViewMode] = useState<"list" | "grid">(() => (localStorage.getItem("inst_view") as "list" | "grid") || "list");
  const orgMap = Object.fromEntries(orgs.map((o) => [o.id, o.name]));

  function configStatus(inst: Instance) {
    if (!inst.is_telegram_configured) return t("instances.configTelegramNo");
    if (!inst.agent_name) return t("instances.configOrgNo");
    return t("instances.configDone");
  }

  useEffect(() => {
    api.listInstances().then(setInstances).finally(() => setLoading(false));
    api.hxaOrgs().then((r) => setOrgs(r.orgs || [])).catch(() => {});
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

  function handleRenamed(id: string, newName: string) {
    setInstances((prev) => prev.map((x) => x.id === id ? { ...x, agent_name: newName } : x));
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
        <div className="flex items-center gap-3">
          {instances.length > 0 && <ViewToggle view={viewMode} onChange={(v) => { setViewMode(v); localStorage.setItem("inst_view", v); }} />}
          <Link
            to="/catalog"
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-md transition-colors whitespace-nowrap"
          >
            {t("instances.deployNew")}
          </Link>
        </div>
      </div>

      {instances.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-10 text-center">
          <div className="text-gray-600 text-4xl mb-3">⊞</div>
          <div className="text-gray-400 text-sm">{t("instances.noInstances")}</div>
          <Link to="/catalog" className="text-blue-400 hover:text-blue-300 text-sm mt-2 inline-block">
            {t("instances.browseCatalog")}
          </Link>
        </div>
      ) : viewMode === "grid" ? (
        /* ─── Grid view ─── */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {instances.map((inst) => (
            <InstanceCard
              key={inst.id}
              inst={inst}
              onDelete={() => handleDelete(inst.id, inst.name)}
              onRename={() => setRenamingInst(inst)}
              deleting={deletingId === inst.id}
            />
          ))}
        </div>
      ) : (
        <>
          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {instances.map((inst) => (
              <div key={inst.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="cursor-pointer" onClick={() => navigate(`/instances/${inst.id}`)}>
                    <div className="text-white font-medium hover:text-blue-400 transition-colors">{inst.name}</div>
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

                <div className="mt-4 flex items-center justify-end">
                  <ActionMenu
                    inst={inst}
                    onDelete={() => handleDelete(inst.id, inst.name)}
                    onRename={() => setRenamingInst(inst)}
                    deleting={deletingId === inst.id}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden md:block bg-gray-900 border border-gray-800 rounded-lg overflow-visible">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.name")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.product")}</th>
                  <th className="text-center px-3 py-3 text-xs text-gray-500 font-medium">{t("admin.state")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.configured")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.org")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.orgName")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.ports")}</th>
                  <th className="text-left px-5 py-3 text-xs text-gray-500 font-medium">{t("instances.deployed")}</th>
                  <th className="px-3 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {instances.map((inst) => (
                  <tr key={inst.id} className="hover:bg-gray-800/50 transition-colors">
                    <td className="px-5 py-3">
                      <Link to={`/instances/${inst.id}`} className="block">
                        <div className="text-white font-medium hover:text-blue-400 transition-colors">{inst.name}</div>
                        <div className="text-xs text-gray-500 font-mono mt-0.5">{inst.id}</div>
                      </Link>
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
                    <td className="px-5 py-3 text-blue-400 text-xs">
                      {inst.org_name || (inst.org_id ? inst.org_id.substring(0, 8) + "..." : "-")}
                    </td>
                    <td className="px-5 py-3 text-gray-300 text-xs font-mono">{inst.agent_name || "-"}</td>
                    <td className="px-5 py-3 text-gray-300 text-xs font-mono">
                      {inst.web_console_port ? `${inst.web_console_port}${inst.http_port ? " / " + inst.http_port : ""}` : "-"}
                    </td>
                    <td className="px-5 py-3 text-gray-500">{formatDate(inst.created_at)}</td>
                    <td className="px-3 py-3">
                      <ActionMenu
                        inst={inst}
                        onDelete={() => handleDelete(inst.id, inst.name)}
                        onRename={() => setRenamingInst(inst)}
                        deleting={deletingId === inst.id}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Rename dialog */}
      {renamingInst && (
        <RenameDialog
          inst={renamingInst}
          onClose={() => setRenamingInst(null)}
          onRenamed={handleRenamed}
        />
      )}
    </div>
  );
}
