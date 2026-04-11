/**
 * StatusIndicator — Animated dot + label for instance/process status.
 */
import { useT } from "../contexts/LanguageContext";

const STATUS_CONFIG: Record<string, { color: string; labelKey: string; pulse?: boolean }> = {
  working: { color: "bg-green-400", labelKey: "status.running", pulse: true },
  running: { color: "bg-green-400", labelKey: "status.running", pulse: true },
  online: { color: "bg-green-400", labelKey: "status.online" },
  idle: { color: "bg-yellow-400", labelKey: "status.idle" },
  offline: { color: "bg-gray-500", labelKey: "status.offline" },
  error: { color: "bg-red-500", labelKey: "status.error", pulse: true },
  stopped: { color: "bg-red-500", labelKey: "status.stopped" },
};

export function StatusIndicator({
  status,
  size = "sm",
  label,
}: {
  status: string;
  size?: "sm" | "md";
  label?: string;
}) {
  const t = useT();
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.offline;
  const dotSize = size === "md" ? "h-3 w-3" : "h-2 w-2";

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="relative flex">
        <span className={`${dotSize} rounded-full ${cfg.color}`} />
        {cfg.pulse && (
          <span className={`absolute inset-0 ${dotSize} rounded-full ${cfg.color} animate-ping opacity-40`} />
        )}
      </span>
      <span className={`${size === "md" ? "text-sm" : "text-xs"} text-gray-400`}>
        {label || t(cfg.labelKey)}
      </span>
    </span>
  );
}
