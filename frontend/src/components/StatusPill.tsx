type Props = {
  state: string;
  size?: "sm" | "md";
};

const STATE_STYLES: Record<string, string> = {
  running: "bg-green-900 text-green-300 border border-green-700",
  active: "bg-green-900 text-green-300 border border-green-700",
  idle: "bg-gray-800 text-gray-400 border border-gray-700",
  pulling: "bg-blue-900 text-blue-300 border border-blue-700",
  configuring: "bg-blue-900 text-blue-300 border border-blue-700",
  starting: "bg-blue-900 text-blue-300 border border-blue-700",
  failed: "bg-red-900 text-red-300 border border-red-700",
  installing: "bg-purple-900 text-purple-300 border border-purple-700",
};

const STATE_LABELS: Record<string, string> = {
  running: "Running",
  active: "Active",
  idle: "Idle",
  pulling: "Pulling",
  configuring: "Configuring",
  starting: "Starting",
  failed: "Failed",
  installing: "Installing",
};

export function StatusPill({ state, size = "sm" }: Props) {
  const style = STATE_STYLES[state] ?? "bg-gray-800 text-gray-400 border border-gray-700";
  const label = STATE_LABELS[state] ?? state;
  const sizeClass = size === "md" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs";

  return (
    <span className={`inline-flex items-center rounded-full font-medium ${style} ${sizeClass}`}>
      {["pulling", "configuring", "starting"].includes(state) && (
        <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" />
      )}
      {state === "running" && (
        <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-green-400" />
      )}
      {label}
    </span>
  );
}
