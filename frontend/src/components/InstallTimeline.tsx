import type { InstallEvent } from "../types";

const STATE_COLORS: Record<string, string> = {
  pulling: "bg-blue-500",
  configuring: "bg-purple-500",
  starting: "bg-amber-500",
  running: "bg-green-500",
  failed: "bg-red-500",
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function InstallTimeline({ events }: { events: InstallEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 text-sm">
        No install events yet. Click Install to begin.
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {events.map((event, idx) => {
        const dotColor = STATE_COLORS[event.state] ?? "bg-gray-500";
        const isLast = idx === events.length - 1;
        return (
          <div key={event.id} className="flex gap-4">
            {/* Timeline line + dot */}
            <div className="flex flex-col items-center">
              <div className={`w-2.5 h-2.5 rounded-full mt-1.5 flex-shrink-0 ${dotColor}`} />
              {!isLast && <div className="w-px flex-1 bg-gray-700 mt-1" />}
            </div>
            {/* Content */}
            <div className={`pb-4 ${isLast ? "" : ""}`}>
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-300 capitalize">{event.state}</span>
                <span className="text-xs text-gray-600">{formatTime(event.created_at)}</span>
              </div>
              <p className="text-sm text-gray-400 mt-0.5">{event.message}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
