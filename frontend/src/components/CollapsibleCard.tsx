import { useEffect, useState, type ReactNode } from "react";

interface Props {
  title: ReactNode;
  /** If set, collapsed state is persisted under this localStorage key. */
  storageKey?: string;
  /** Default state when no persisted value exists. */
  defaultCollapsed?: boolean;
  /** Extra controls rendered inline after the title, before the chevron. */
  headerExtras?: ReactNode;
  children: ReactNode;
}

/**
 * Standard right-sidebar card with a chevron toggle in the top-right
 * corner. Collapsed state sticks across reloads via localStorage so the
 * user doesn't have to re-fold long blocks every visit.
 */
export function CollapsibleCard({
  title,
  storageKey,
  defaultCollapsed = false,
  headerExtras,
  children,
}: Props) {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (!storageKey) return defaultCollapsed;
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw === "1") return true;
      if (raw === "0") return false;
    } catch { /* ignore */ }
    return defaultCollapsed;
  });

  useEffect(() => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, collapsed ? "1" : "0"); } catch { /* ignore */ }
  }, [storageKey, collapsed]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="flex-1 text-sm font-medium text-gray-300">{title}</h2>
        {headerExtras}
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="p-1 rounded text-gray-500 hover:text-gray-200 hover:bg-gray-800 transition-colors"
          aria-label={collapsed ? "展开" : "收起"}
          title={collapsed ? "展开" : "收起"}
        >
          <svg
            className={`h-4 w-4 transition-transform ${collapsed ? "-rotate-90" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>
      {!collapsed && <div>{children}</div>}
    </div>
  );
}
