import { useEffect, useState, useRef } from "react";
import { api } from "../api";
import { useT, useLang } from "../contexts/LanguageContext";
import type { MarketplaceItem, MarketplaceInstall, Instance } from "../types";

export function MarketplacePage() {
  return <MarketplaceGrid type="plugin" />;
}

export function SkillCenterPage() {
  return <MarketplaceGrid type="skill" />;
}

function MarketplaceGrid({ type }: { type: "plugin" | "skill" }) {
  const t = useT();
  const { lang } = useLang();
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [loading, setLoading] = useState(true);

  // Install modal state
  const [installItem, setInstallItem] = useState<MarketplaceItem | null>(null);
  const [selectedInstance, setSelectedInstance] = useState("");
  const [installing, setInstalling] = useState(false);

  // Log modal state
  const [logModal, setLogModal] = useState<{ instanceId: string; itemId: string } | null>(null);
  const [logData, setLogData] = useState<MarketplaceInstall | null>(null);
  const pollRef = useRef<number>(0);

  // Installed status per instance
  const [installedMap, setInstalledMap] = useState<Record<string, Record<string, MarketplaceInstall>>>({});

  useEffect(() => {
    Promise.all([api.marketplaceItems(), api.listInstances()])
      .then(([allItems, allInstances]) => {
        setItems(allItems.filter(i => i.type === type));
        setInstances(allInstances.filter(i => i.status === "active" || i.install_state === "running"));
      })
      .finally(() => setLoading(false));
  }, [type]);

  // Load installed status for all instances
  useEffect(() => {
    instances.forEach(inst => {
      api.marketplaceInstalled(inst.id).then(installed => {
        const map: Record<string, MarketplaceInstall> = {};
        installed.forEach(i => { map[i.item_id] = i; });
        setInstalledMap(prev => ({ ...prev, [inst.id]: map }));
      }).catch(() => {});
    });
  }, [instances]);

  function openInstallModal(item: MarketplaceItem) {
    setInstallItem(item);
    setSelectedInstance("");
  }

  async function doInstall() {
    if (!installItem || !selectedInstance) return;
    setInstalling(true);
    try {
      await api.marketplaceInstall(selectedInstance, installItem.id);
      setInstallItem(null);
      // Open log modal to poll progress
      setLogModal({ instanceId: selectedInstance, itemId: installItem.id });
    } catch (e: unknown) {
      alert((e as Error).message || "Install failed");
    }
    setInstalling(false);
  }

  // Poll install log
  useEffect(() => {
    if (!logModal) { setLogData(null); return; }
    let active = true;
    async function poll() {
      try {
        const data = await api.marketplaceInstallLog(logModal!.instanceId, logModal!.itemId);
        if (active) setLogData(data);
        if (data.status === "installing" && active) {
          pollRef.current = window.setTimeout(poll, 1000);
        } else {
          // Refresh installed map
          api.marketplaceInstalled(logModal!.instanceId).then(installed => {
            const map: Record<string, MarketplaceInstall> = {};
            installed.forEach(i => { map[i.item_id] = i; });
            setInstalledMap(prev => ({ ...prev, [logModal!.instanceId]: map }));
          }).catch(() => {});
        }
      } catch { /* */ }
    }
    poll();
    return () => { active = false; clearTimeout(pollRef.current); };
  }, [logModal?.instanceId, logModal?.itemId]);

  const title = type === "plugin" ? t("marketplace.title") : t("skills.title");
  const desc = type === "plugin" ? t("marketplace.desc") : t("skills.desc");

  const compatibleInstances = installItem
    ? instances.filter(i => installItem.product === "all" || i.product === installItem.product)
    : [];

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-1">{title}</h1>
      <p className="text-gray-400 text-sm mb-6">{desc}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {items.map(item => (
          <div key={item.id} className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex flex-col">
            <div className="flex items-start gap-3 mb-3">
              <span className="text-3xl">{item.icon}</span>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-semibold text-white">{lang === "zh" && item.name_zh ? item.name_zh : item.name}</h2>
                <p className="text-xs text-gray-400 mt-1">{lang === "zh" && item.description_zh ? item.description_zh : item.description}</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5 mb-3">
              {item.tags.map(tag => (
                <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-900/30 text-blue-400">{tag}</span>
              ))}
            </div>

            <div className="text-xs text-gray-500 space-y-1 mb-4">
              <div>{t("marketplace.compatibleWith")}: <span className="text-gray-300">{item.product === "all" ? "OpenClaw, Zylos" : item.product === "openclaw" ? "OpenClaw" : "Zylos"}</span></div>
              {item.install_time && <div>{t("marketplace.installTime")}: <span className="text-gray-300">{item.install_time}</span></div>}
              {item.models && <div>Models: <span className="text-gray-300">{item.models.join(", ")}</span></div>}
            </div>

            {(lang === "zh" ? item.note_zh : item.note) && (
              <p className="text-xs text-yellow-400/80 bg-yellow-900/20 rounded-md px-3 py-2 mb-4">
                {lang === "zh" ? item.note_zh : item.note}
              </p>
            )}

            <div className="mt-auto">
              <button
                onClick={() => openInstallModal(item)}
                className="w-full bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium py-2 rounded-lg transition-colors"
              >
                {t("marketplace.install")}
              </button>
            </div>
          </div>
        ))}
      </div>

      {items.length === 0 && (
        <div className="text-center py-16 text-gray-500">
          {type === "plugin" ? "No plugins available yet." : "No skills available yet."}
        </div>
      )}

      {/* Install Modal */}
      {installItem && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => !installing && setInstallItem(null)}>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-white mb-4">
              {t("marketplace.install")} {lang === "zh" && installItem.name_zh ? installItem.name_zh : installItem.name}
            </h3>

            <label className="block text-sm text-gray-400 mb-2">{t("marketplace.selectInstance")}</label>
            <select
              value={selectedInstance}
              onChange={e => setSelectedInstance(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 mb-4"
            >
              <option value="">-- {t("marketplace.selectInstance")} --</option>
              {compatibleInstances.map(inst => {
                const instInstalled = installedMap[inst.id]?.[installItem.id];
                const badge = instInstalled?.status === "installed" ? ` [${t("marketplace.installed")}]` : "";
                return (
                  <option key={inst.id} value={inst.id} disabled={instInstalled?.status === "installed"}>
                    {inst.name} ({inst.product}){badge}
                  </option>
                );
              })}
            </select>

            <div className="flex gap-3">
              <button
                onClick={() => setInstallItem(null)}
                disabled={installing}
                className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm py-2 rounded-lg"
              >
                {t("marketplace.cancel")}
              </button>
              <button
                onClick={doInstall}
                disabled={!selectedInstance || installing}
                className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm py-2 rounded-lg"
              >
                {installing ? t("marketplace.installing") : t("marketplace.confirm")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Log Modal — not dismissible by clicking outside during install */}
      {logModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold text-white">{t("marketplace.viewLog")}</h3>
              <span className={`text-xs px-2 py-1 rounded-full ${
                logData?.status === "installed" ? "bg-green-900/40 text-green-400" :
                logData?.status === "failed" ? "bg-red-900/40 text-red-400" :
                "bg-yellow-900/40 text-yellow-400"
              }`}>
                {logData?.status === "installed" ? t("marketplace.installed") :
                 logData?.status === "failed" ? t("marketplace.failed") :
                 t("marketplace.installing")}
              </span>
            </div>
            <pre className="flex-1 overflow-auto bg-gray-950 rounded-lg p-4 text-xs text-green-400 font-mono whitespace-pre-wrap">
              {logData?.install_log || "Waiting for output..."}
            </pre>
            <button
              onClick={() => setLogModal(null)}
              className="mt-3 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm py-2 rounded-lg"
            >
              {logData?.status === "installing" ? t("marketplace.installing") : "Close"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
