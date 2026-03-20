import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { HxaOrg, HxaOrgAgent } from "../types";

function StatusBadge({ status }: { status: string }) {
  const color = status === "active" ? "text-green-400" : status === "suspended" ? "text-yellow-400" : "text-red-400";
  return <span className={`text-xs ${color}`}>{status}</span>;
}

function OnlineDot({ online }: { online: boolean }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${online ? "bg-green-400" : "bg-gray-500"}`} />;
}

export default function AdminHXAPage() {
  const navigate = useNavigate();
  const t = useT();

  // Global config
  const [hubUrl, setHubUrl] = useState("");
  const [editingHubUrl, setEditingHubUrl] = useState(false);
  const [hubUrlDraft, setHubUrlDraft] = useState("");
  const [hubUrlSaving, setHubUrlSaving] = useState(false);

  // Org list
  const [orgs, setOrgs] = useState<HxaOrg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Create org
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdSecret, setCreatedSecret] = useState("");

  // Org detail
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);
  const [orgAgents, setOrgAgents] = useState<HxaOrgAgent[]>([]);
  const [orgName, setOrgName] = useState("");
  const [loadingAgents, setLoadingAgents] = useState(false);

  // Editing org name
  const [editingOrgName, setEditingOrgName] = useState(false);
  const [orgNameDraft, setOrgNameDraft] = useState("");

  // Transfer
  const [transferBotId, setTransferBotId] = useState("");
  const [transferTargetOrg, setTransferTargetOrg] = useState("");
  const [transferring, setTransferring] = useState(false);

  // Filter
  const [onlyWithInstance, setOnlyWithInstance] = useState(false);

  // Secret display
  const [showOrgSecret, setShowOrgSecret] = useState<string | null>(null);
  const [newSecret, setNewSecret] = useState("");

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [cfg, orgsData] = await Promise.all([
        api.get("/api/admin/hxa/config").then((r) => r.json()),
        api.hxaOrgs(),
      ]);
      setHubUrl(cfg.hub_url || "");
      setOrgs(orgsData.orgs || []);
    } catch {
      setError(t("adminHxa.loadFailed"));
    }
    setLoading(false);
  }

  async function saveHubUrl() {
    const url = hubUrlDraft.trim().replace(/\/+$/, "");
    if (!url) return;
    setHubUrlSaving(true);
    try {
      await api.put("/api/admin/hxa/config/hub-url", { hub_url: url });
      setHubUrl(url);
      setEditingHubUrl(false);
    } finally {
      setHubUrlSaving(false);
    }
  }

  async function handleCreateOrg() {
    if (!createName.trim()) return;
    setCreating(true);
    try {
      const result = await api.hxaCreateOrg(createName.trim());
      if (result.org_secret) {
        setCreatedSecret(result.org_secret);
      }
      setCreateName("");
      await loadData();
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
    setCreating(false);
  }

  async function handleDeleteOrg(org: HxaOrg) {
    if (!confirm(t("adminHxa.confirmDelete").replace("{name}", org.name))) return;
    try {
      await api.hxaDeleteOrg(org.id);
      await loadData();
      if (selectedOrgId === org.id) setSelectedOrgId(null);
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
  }

  async function handleRotateSecret(org: HxaOrg) {
    if (!confirm(t("adminHxa.confirmRotate").replace("{name}", org.name))) return;
    try {
      const result = await api.hxaRotateSecret(org.id);
      if (result.org_secret) {
        setNewSecret(result.org_secret);
        setShowOrgSecret(org.id);
      }
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
  }

  async function handleSetDefault(orgId: string) {
    try {
      await api.hxaSetDefaultOrg(orgId);
      await loadData();
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
  }

  async function handleUpdateOrgName(orgId: string) {
    if (!orgNameDraft.trim()) return;
    try {
      await api.hxaUpdateOrg(orgId, orgNameDraft.trim());
      setEditingOrgName(false);
      setOrgName(orgNameDraft.trim());
      await loadData();
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
  }

  async function viewOrgDetail(orgId: string) {
    setSelectedOrgId(orgId);
    setLoadingAgents(true);
    try {
      const result = await api.hxaOrgAgents(orgId);
      setOrgAgents(result.agents || []);
      setOrgName(result.org_name || "");
    } catch {
      setOrgAgents([]);
    }
    setLoadingAgents(false);
  }

  async function handleTransfer(agent: HxaOrgAgent) {
    if (!transferTargetOrg || !agent.instance_id) return;
    const targetOrg = orgs.find((o) => o.id === transferTargetOrg);
    if (!confirm(t("adminHxa.transferConfirm").replace("{name}", agent.name).replace("{target}", targetOrg?.name || ""))) return;
    setTransferring(true);
    try {
      await api.hxaTransferBot(agent.instance_id, transferTargetOrg);
      setTransferBotId("");
      setTransferTargetOrg("");
      if (selectedOrgId) await viewOrgDetail(selectedOrgId);
      await loadData();
    } catch (e: unknown) {
      alert((e as Error).message || "Failed");
    }
    setTransferring(false);
  }

  const [copiedKey, setCopiedKey] = useState("");
  const copy = useCallback((text: string, key?: string) => {
    navigator.clipboard?.writeText(text).then(() => {
      const k = key || text;
      setCopiedKey(k);
      setTimeout(() => setCopiedKey((v) => v === k ? "" : v), 1500);
    });
  }, []);
  const CopyBtn = ({ text, id }: { text: string; id?: string }) => {
    const k = id || text;
    return copiedKey === k
      ? <span className="text-xs text-green-400">✓</span>
      : <button onClick={() => copy(text, k)} className="text-xs text-gray-500 hover:text-gray-300">{t("common.copy")}</button>;
  };
  const selectedOrg = orgs.find((o) => o.id === selectedOrgId);

  if (loading) return <div className="text-gray-400 text-sm p-6">{t("common.loading")}</div>;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate("/admin")} className="text-gray-400 hover:text-gray-200 text-sm">{t("common.back")}</button>
        <h1 className="text-lg font-semibold text-white">{t("adminHxa.title")}</h1>
      </div>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {/* Hub URL config */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 w-20">{t("adminHxa.hubUrl")}</span>
          {editingHubUrl ? (
            <>
              <input type="text" value={hubUrlDraft} onChange={(e) => setHubUrlDraft(e.target.value)}
                className="text-xs font-mono text-gray-200 bg-gray-800 border border-gray-700 px-2 py-1 rounded flex-1 focus:outline-none focus:border-gray-500"
                onKeyDown={(e) => e.key === "Enter" && saveHubUrl()} />
              <button onClick={saveHubUrl} disabled={hubUrlSaving} className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50">{hubUrlSaving ? "..." : t("common.save")}</button>
              <button onClick={() => setEditingHubUrl(false)} className="text-xs text-gray-500 hover:text-gray-300">{t("common.cancel")}</button>
            </>
          ) : (
            <>
              <code className="text-xs font-mono text-gray-200 bg-gray-800 px-2 py-1 rounded flex-1">{hubUrl}</code>
              <button onClick={() => { setHubUrlDraft(hubUrl); setEditingHubUrl(true); }} className="text-xs text-gray-500 hover:text-gray-300">{t("common.edit")}</button>
            </>
          )}
        </div>
      </div>

      {/* New secret display */}
      {createdSecret && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4 space-y-2">
          <p className="text-yellow-300 text-sm font-medium">⚠ {t("adminHxa.secretWarning")}</p>
          <div className="flex items-center gap-2">
            <code className="text-xs font-mono text-yellow-200 bg-gray-800 px-2 py-1 rounded flex-1 break-all">{createdSecret}</code>
            <CopyBtn text={createdSecret} id="created-secret" />
          </div>
          <button onClick={() => setCreatedSecret("")} className="text-xs text-gray-500 hover:text-gray-300">{t("common.close")}</button>
        </div>
      )}

      {/* Rotated secret display */}
      {newSecret && showOrgSecret && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4 space-y-2">
          <p className="text-yellow-300 text-sm font-medium">⚠ {t("adminHxa.newSecret")}</p>
          <div className="flex items-center gap-2">
            <code className="text-xs font-mono text-yellow-200 bg-gray-800 px-2 py-1 rounded flex-1 break-all">{newSecret}</code>
            <CopyBtn text={newSecret} id="new-secret" />
          </div>
          <button onClick={() => { setNewSecret(""); setShowOrgSecret(null); }} className="text-xs text-gray-500 hover:text-gray-300">{t("common.close")}</button>
        </div>
      )}

      {/* Org list + create */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-gray-300">{t("adminHxa.orgList")} ({orgs.length})</h2>
          <button onClick={() => setShowCreate(!showCreate)} className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded">
            {t("adminHxa.createOrg")}
          </button>
        </div>

        {showCreate && (
          <div className="flex items-center gap-2 mb-4 p-3 bg-gray-800 rounded">
            <input type="text" value={createName} onChange={(e) => setCreateName(e.target.value)}
              placeholder={t("adminHxa.createOrgName")}
              className="text-sm text-gray-200 bg-gray-700 border border-gray-600 px-3 py-1.5 rounded flex-1 focus:outline-none focus:border-blue-500"
              onKeyDown={(e) => e.key === "Enter" && handleCreateOrg()} />
            <button onClick={handleCreateOrg} disabled={creating || !createName.trim()}
              className="text-xs bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white px-3 py-1.5 rounded">
              {creating ? t("adminHxa.creating") : t("adminHxa.create")}
            </button>
            <button onClick={() => { setShowCreate(false); setCreateName(""); }} className="text-xs text-gray-500 hover:text-gray-300">{t("common.cancel")}</button>
          </div>
        )}

        {orgs.length === 0 ? (
          <p className="text-gray-500 text-sm">{t("adminHxa.noOrgs")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 pr-4">{t("adminHxa.orgName")}</th>
                  <th className="text-left py-2 pr-4">{t("adminHxa.orgId")}</th>
                  <th className="text-center py-2 pr-4">{t("adminHxa.status")}</th>
                  <th className="text-center py-2 pr-4">{t("adminHxa.botCount")}</th>
                  <th className="text-left py-2 pr-4">{t("adminHxa.createdAt")}</th>
                  <th className="text-right py-2">{t("adminHxa.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {orgs.map((org) => (
                  <tr key={org.id} className={`border-b border-gray-800/50 ${selectedOrgId === org.id ? "bg-gray-800/50" : ""}`}>
                    <td className="py-2 pr-4 text-gray-200 font-medium">
                      {org.name}
                      {org.is_default && (
                        <span className="ml-2 text-[10px] bg-blue-600/30 text-blue-400 px-1.5 py-0.5 rounded">{t("adminHxa.default")}</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 font-mono text-gray-400">{org.id.substring(0, 12)}...</td>
                    <td className="py-2 pr-4 text-center"><StatusBadge status={org.status} /></td>
                    <td className="py-2 pr-4 text-center text-gray-300">{org.bot_count}</td>
                    <td className="py-2 pr-4 text-gray-400">
                      {org.created_at ? new Date(org.created_at).toLocaleDateString() : "-"}
                    </td>
                    <td className="py-2 text-right space-x-2">
                      <button onClick={() => viewOrgDetail(org.id)} className="text-blue-400 hover:text-blue-300">{t("adminHxa.viewDetail")}</button>
                      {!org.is_default && (
                        <>
                          <button onClick={() => handleSetDefault(org.id)} className="text-gray-500 hover:text-gray-300">{t("adminHxa.setDefault")}</button>
                          <button onClick={() => handleDeleteOrg(org)} className="text-red-500 hover:text-red-400">{t("adminHxa.deleteOrg")}</button>
                        </>
                      )}
                      <button onClick={() => handleRotateSecret(org)} className="text-yellow-500 hover:text-yellow-400">{t("adminHxa.rotateSecret")}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Org detail (agents) */}
      {selectedOrg && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-medium text-gray-300">{t("adminHxa.orgDetail")}</h2>
              {editingOrgName ? (
                <div className="flex items-center gap-1">
                  <input type="text" value={orgNameDraft} onChange={(e) => setOrgNameDraft(e.target.value)}
                    className="text-sm font-mono text-gray-200 bg-gray-800 border border-gray-700 px-2 py-0.5 rounded w-40 focus:outline-none focus:border-gray-500"
                    onKeyDown={(e) => e.key === "Enter" && handleUpdateOrgName(selectedOrg.id)} />
                  <button onClick={() => handleUpdateOrgName(selectedOrg.id)} className="text-xs text-blue-400">{t("common.ok")}</button>
                  <button onClick={() => setEditingOrgName(false)} className="text-xs text-gray-500">X</button>
                </div>
              ) : (
                <span className="text-white font-medium group">
                  {orgName || selectedOrg.name}
                  <button onClick={() => { setOrgNameDraft(orgName || selectedOrg.name); setEditingOrgName(true); }}
                    className="ml-2 text-xs text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity">{t("common.edit")}</button>
                </span>
              )}
            </div>
            <button onClick={() => setSelectedOrgId(null)} className="text-xs text-gray-500 hover:text-gray-300">{t("common.close")}</button>
          </div>

          <div className="grid grid-cols-2 gap-2 mb-4 text-xs">
            <div>
              <span className="text-gray-500">{t("adminHxa.orgId")}:</span>
              <code className="ml-2 text-gray-300 font-mono">{selectedOrg.id}</code>
              <span className="ml-1"><CopyBtn text={selectedOrg.id} id="org-id" /></span>
            </div>
            <div>
              <span className="text-gray-500">{t("adminHxa.status")}:</span>
              <span className="ml-2"><StatusBadge status={selectedOrg.status} /></span>
            </div>
          </div>

          {(() => {
            const filtered = onlyWithInstance ? orgAgents.filter((a) => a.instance_id) : orgAgents;
            return (
              <>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-xs text-gray-400">{t("adminHxa.agents")} ({filtered.length}{onlyWithInstance ? ` / ${orgAgents.length}` : ""})</h3>
                  <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                    <input type="checkbox" checked={onlyWithInstance} onChange={(e) => setOnlyWithInstance(e.target.checked)}
                      className="rounded bg-gray-800 border-gray-600" />
                    只看有实例的
                  </label>
                </div>
                {loadingAgents ? (
                  <p className="text-gray-500 text-xs">{t("common.loading")}</p>
                ) : filtered.length === 0 ? (
                  <p className="text-gray-500 text-xs">{t("adminHxa.noAgents")}</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-500 border-b border-gray-800">
                        <th className="text-left py-1.5">Bot</th>
                        <th className="text-center py-1.5">状态</th>
                        <th className="text-left py-1.5">{t("adminHxa.role")}</th>
                        <th className="text-left py-1.5">所有者</th>
                        <th className="text-left py-1.5">{t("adminHxa.instance")}</th>
                        <th className="text-left py-1.5">{t("adminHxa.token")}</th>
                        <th className="text-right py-1.5">{t("adminHxa.actions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((agent) => (
                        <tr key={agent.bot_id} className="border-b border-gray-800/50">
                          <td className="py-1.5 text-gray-200 font-mono">
                            <span className="inline-flex items-center gap-1.5">
                              <OnlineDot online={agent.online} />
                              {agent.name}
                            </span>
                          </td>
                          <td className="py-1.5 text-center text-gray-400">
                            {agent.online ? t("adminHxa.online") : t("adminHxa.offline")}
                          </td>
                          <td className="py-1.5 text-gray-400">{agent.auth_role}</td>
                          <td className="py-1.5 text-gray-400">
                            {agent.owner_name ? (
                              <span title={agent.owner_email || ""}>{agent.owner_name}</span>
                            ) : "-"}
                          </td>
                          <td className="py-1.5 text-gray-400">{agent.instance_name || "-"}</td>
                          <td className="py-1.5 text-gray-400 font-mono">{agent.token_prefix || "-"}</td>
                          <td className="py-1.5 text-right">
                            {agent.instance_id && orgs.length > 1 && (
                              transferBotId === agent.bot_id ? (
                                <div className="inline-flex items-center gap-1">
                                  <select value={transferTargetOrg} onChange={(e) => setTransferTargetOrg(e.target.value)}
                                    className="text-xs bg-gray-800 border border-gray-700 text-gray-300 rounded px-1 py-0.5">
                                    <option value="">{t("adminHxa.transferTo")}</option>
                                    {orgs.filter((o) => o.id !== selectedOrgId).map((o) => (
                                      <option key={o.id} value={o.id}>{o.name}</option>
                                    ))}
                                  </select>
                                  <button onClick={() => handleTransfer(agent)} disabled={transferring || !transferTargetOrg}
                                    className="text-blue-400 hover:text-blue-300 disabled:opacity-50">
                                    {transferring ? "..." : t("common.ok")}
                                  </button>
                                  <button onClick={() => { setTransferBotId(""); setTransferTargetOrg(""); }} className="text-gray-500">X</button>
                                </div>
                              ) : (
                                <button onClick={() => setTransferBotId(agent.bot_id)} className="text-yellow-500 hover:text-yellow-400">{t("adminHxa.transfer")}</button>
                              )
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
