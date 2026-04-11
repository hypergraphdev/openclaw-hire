/**
 * ConnectivityTest — One-click connectivity test panel for HXA/Telegram/Claude.
 */
import { useState } from "react";
import { api } from "../api";
import { useT } from "../contexts/LanguageContext";

type TestResult = {
  ok: boolean;
  elapsed_ms: number;
  detail?: string;
  error?: string;
};

type TestState = "idle" | "testing" | "done";

export function ConnectivityTest({ instanceId }: { instanceId: string }) {
  const t = useT();
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [states, setStates] = useState<Record<string, TestState>>({});

  async function runAll() {
    setStates({ hxa: "testing", telegram: "testing", claude: "testing" });
    setResults({});
    try {
      const data = await api.instanceConnectivityTest(instanceId);
      setResults(data);
      setStates({ hxa: "done", telegram: "done", claude: "done" });
    } catch {
      setStates({ hxa: "done", telegram: "done", claude: "done" });
    }
  }

  function renderBadge(key: string, label: string, icon: string) {
    const state = states[key] || "idle";
    const result = results[key];

    return (
      <div className="flex items-center gap-2 px-3 py-2 bg-gray-800/50 rounded-lg border border-gray-700/50">
        <span className="text-sm">{icon}</span>
        <span className="text-xs text-gray-300 min-w-[60px]">{label}</span>
        <span className="ml-auto text-xs">
          {state === "idle" && <span className="text-gray-600">--</span>}
          {state === "testing" && <span className="text-blue-400 animate-pulse">{t("connectivity.testing")}</span>}
          {state === "done" && result && (
            result.ok ? (
              <span className="text-green-400" title={result.detail || ""}>
                ✅ {result.elapsed_ms}ms
                {result.detail && <span className="text-gray-500 ml-1">({result.detail})</span>}
              </span>
            ) : (
              <span className="text-red-400" title={result.error || ""}>
                ❌ {result.error?.slice(0, 30) || "Failed"}
              </span>
            )
          )}
        </span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-gray-400">{t("connectivity.title")}</h4>
        <button
          onClick={runAll}
          disabled={Object.values(states).some((s) => s === "testing")}
          className="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-50"
        >
          {t("connectivity.testAll")}
        </button>
      </div>
      {renderBadge("claude", "Claude", "🧠")}
      {renderBadge("hxa", "HXA Hub", "📡")}
      {renderBadge("telegram", "Telegram", "💬")}
    </div>
  );
}
