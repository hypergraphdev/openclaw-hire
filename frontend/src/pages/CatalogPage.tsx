import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";
import type { ProductCatalog } from "../types";

const LOCAL_AGENT_RUNTIMES: Array<{ id: string; label: string; hint: string }> = [
  { id: "claude", label: "Claude Code", hint: "需本机装好 `claude` CLI 并登录" },
  { id: "codex",  label: "Codex CLI",   hint: "需本机装好 `codex` CLI 并登录" },
  { id: "gemini", label: "Gemini CLI",  hint: "需本机装好 `gemini` CLI 并登录" },
];

function DeployModal({
  product,
  onClose,
  onDeploy,
  t,
}: {
  product: ProductCatalog;
  onClose: () => void;
  onDeploy: (name: string, runtime?: string) => Promise<void>;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const [name, setName] = useState(`${product.id}-${Date.now().toString(36).slice(-4)}`);
  const [runtime, setRuntime] = useState("claude");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const isLocalAgent = product.id === "local_agent";

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await onDeploy(name, isLocalAgent ? runtime : undefined);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("catalog.deployFailed"));
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 px-4">
      <div className="bg-gray-900 border border-gray-700 rounded-lg w-full max-w-md p-6">
        <h2 className="text-white font-semibold mb-1">{t("catalog.deployTitle", { name: product.name })}</h2>
        <p className="text-gray-400 text-sm mb-5">{product.tagline}</p>

        {error && (
          <div className="mb-4 p-3 bg-red-900/40 border border-red-700 rounded text-red-300 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1.5">{t("catalog.instanceName")}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          {isLocalAgent && (
            <div>
              <label className="block text-sm text-gray-400 mb-1.5">本机 CLI</label>
              <select
                value={runtime}
                onChange={(e) => setRuntime(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-white text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {LOCAL_AGENT_RUNTIMES.map((r) => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                {LOCAL_AGENT_RUNTIMES.find((r) => r.id === runtime)?.hint}
              </p>
            </div>
          )}
          <div className="bg-gray-800 rounded-md p-3 text-xs text-gray-400">
            <span className="text-gray-500">{t("catalog.repository")}</span>
            <a href={product.repo_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline break-all">
              {product.repo_url}
            </a>
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm py-2 rounded-md transition-colors"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-md transition-colors"
            >
              {loading ? t("catalog.deploying") : t("catalog.deploySubmit")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function CatalogPage() {
  const navigate = useNavigate();
  const t = useT();
  const [products, setProducts] = useState<ProductCatalog[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProduct, setSelectedProduct] = useState<ProductCatalog | null>(null);

  useEffect(() => {
    api.catalog()
      .then(setProducts)
      .finally(() => setLoading(false));
  }, []);

  async function handleDeploy(name: string, runtime?: string) {
    if (!selectedProduct) return;
    const payload: { name: string; product: string; runtime?: string } = {
      name,
      product: selectedProduct.id,
    };
    if (runtime) payload.runtime = runtime;
    const instance = await api.createInstance(payload);
    navigate(`/instances/${instance.id}`);
  }

  if (loading) {
    return <div className="text-gray-500 text-sm">{t("catalog.loading")}</div>;
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-white">{t("catalog.title")}</h1>
        <p className="text-gray-500 text-sm mt-1">{t("catalog.subtitle")}</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {products.map((product) => (
          <div
            key={product.id}
            className="bg-gray-900 border border-gray-800 rounded-lg p-6 flex flex-col"
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <h2 className="text-white font-semibold">{product.name}</h2>
                <p className="text-xs text-blue-400 mt-0.5">{product.tagline}</p>
              </div>
              <div className="flex flex-wrap gap-1 justify-end">
                {product.tags.slice(0, 2).map((tag) => (
                  <span
                    key={tag}
                    className="text-xs px-2 py-0.5 bg-gray-800 text-gray-400 rounded-full border border-gray-700"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>

            <p className="text-sm text-gray-400 mb-4 flex-1">{product.description}</p>

            <ul className="space-y-1 mb-5">
              {product.features.map((f) => (
                <li key={f} className="text-xs text-gray-500 flex items-start gap-2">
                  <span className="text-green-500 mt-0.5 flex-shrink-0">✓</span>
                  {f}
                </li>
              ))}
            </ul>

            <div className="flex items-center gap-3">
              <a
                href={product.repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
              >
                {t("catalog.viewSource")}
              </a>
              <button
                onClick={() => setSelectedProduct(product)}
                className="ml-auto bg-blue-600 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-md transition-colors"
              >
                {t("catalog.deploy")}
              </button>
            </div>
          </div>
        ))}
      </div>

      {selectedProduct && (
        <DeployModal
          product={selectedProduct}
          onClose={() => setSelectedProduct(null)}
          onDeploy={handleDeploy}
          t={t}
        />
      )}
    </div>
  );
}
