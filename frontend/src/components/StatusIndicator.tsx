/**
 * StatusIndicator — Animated dot + label for instance/process status.
 */
const STATUS_CONFIG: Record<string, { color: string; label: string; pulse?: boolean }> = {
  working: { color: "bg-green-400", label: "运行中", pulse: true },
  running: { color: "bg-green-400", label: "运行中", pulse: true },
  online: { color: "bg-green-400", label: "在线" },
  idle: { color: "bg-yellow-400", label: "空闲" },
  offline: { color: "bg-gray-500", label: "离线" },
  error: { color: "bg-red-500", label: "异常", pulse: true },
  stopped: { color: "bg-red-500", label: "已停止" },
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
        {label || cfg.label}
      </span>
    </span>
  );
}
