import { useMemo } from "react";

interface PixelOfficeProps {
  bots: Array<{ name: string; online: boolean; bot_id: string }>;
  myBotNames: Set<string>;
  onBotClick: (botName: string) => void;
}

// Deterministic color from name hash
function nameToColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#06b6d4", "#f97316", "#6366f1",
    "#14b8a6", "#e11d48", "#84cc16", "#a855f7",
  ];
  return colors[Math.abs(hash) % colors.length];
}

function nameToInitial(name: string): string {
  return name.charAt(0).toUpperCase();
}

const STYLE_TAG_ID = "pixel-office-keyframes";

function ensureKeyframes() {
  if (typeof document === "undefined") return;
  if (document.getElementById(STYLE_TAG_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_TAG_ID;
  style.textContent = `
    @keyframes po-breathe {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.06); }
    }
    @keyframes po-typing-dot {
      0%, 80%, 100% { opacity: 0.2; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-3px); }
    }
    @keyframes po-glow {
      0%, 100% { box-shadow: 0 0 4px rgba(74, 222, 128, 0.3); }
      50% { box-shadow: 0 0 12px rgba(74, 222, 128, 0.6); }
    }
    @keyframes po-float {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-2px); }
    }
  `;
  document.head.appendChild(style);
}

function TypingDots() {
  return (
    <div className="flex items-center gap-0.5 mt-1 justify-center">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="inline-block w-1 h-1 rounded-full bg-green-400"
          style={{
            animation: "po-typing-dot 1.4s ease-in-out infinite",
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
    </div>
  );
}

function DeskBot({
  name,
  online,
  isMine,
  onClick,
}: {
  name: string;
  online: boolean;
  isMine: boolean;
  onClick: () => void;
}) {
  const color = nameToColor(name);
  const initial = nameToInitial(name);

  return (
    <button
      onClick={onClick}
      className="group relative flex flex-col items-center p-3 rounded-xl transition-all duration-200 hover:-translate-y-1"
      style={{
        background: "rgba(30, 30, 40, 0.6)",
      }}
      title={`${name}${online ? " (online)" : " (offline)"}`}
    >
      {/* Desk surface */}
      <div
        className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-md"
        style={{
          width: "70%",
          height: "18px",
          background: "linear-gradient(180deg, #3a3524 0%, #2a2518 100%)",
          borderTop: "2px solid #5a4a30",
        }}
      />

      {/* Monitor behind avatar */}
      <div
        className="absolute top-1 left-1/2 -translate-x-1/2 rounded-sm"
        style={{
          width: "28px",
          height: "20px",
          background: online
            ? "linear-gradient(135deg, #1a2a3a 0%, #0f1a2a 100%)"
            : "#1a1a22",
          border: `1px solid ${online ? "#334155" : "#252530"}`,
          boxShadow: online ? "0 0 6px rgba(56, 189, 248, 0.15)" : "none",
        }}
      >
        {/* Screen glow */}
        {online && (
          <div
            className="w-full h-full rounded-sm"
            style={{
              background:
                "linear-gradient(135deg, rgba(56,189,248,0.08) 0%, rgba(16,185,129,0.05) 100%)",
            }}
          />
        )}
      </div>

      {/* Avatar */}
      <div
        className="relative z-10 mt-4 mb-1 flex items-center justify-center rounded-full text-white font-bold text-sm select-none"
        style={{
          width: "40px",
          height: "40px",
          backgroundColor: online ? color : "#4b5563",
          filter: online ? "none" : "grayscale(0.8)",
          animation: online ? "po-breathe 3s ease-in-out infinite" : "none",
          boxShadow: online
            ? `0 0 10px ${color}44, 0 2px 8px rgba(0,0,0,0.4)`
            : "0 2px 4px rgba(0,0,0,0.3)",
          transition: "filter 0.3s, box-shadow 0.3s",
        }}
      >
        {initial}
        {/* Online indicator */}
        <span
          className="absolute -bottom-0.5 -right-0.5 rounded-full border-2"
          style={{
            width: "12px",
            height: "12px",
            backgroundColor: online ? "#4ade80" : "#6b7280",
            borderColor: "#1e1e28",
            animation: online ? "po-glow 2s ease-in-out infinite" : "none",
          }}
        />
      </div>

      {/* Name + badges */}
      <div className="flex items-center gap-1 mt-0.5 z-10">
        <span
          className="text-[11px] truncate max-w-[80px]"
          style={{
            color: online ? "#e5e7eb" : "#6b7280",
          }}
        >
          {name}
        </span>
      </div>

      {isMine && (
        <span
          className="text-[9px] px-1.5 py-0.5 rounded-full mt-0.5 z-10"
          style={{
            backgroundColor: "rgba(59, 130, 246, 0.25)",
            color: "#60a5fa",
            border: "1px solid rgba(59, 130, 246, 0.3)",
          }}
        >
          MY
        </span>
      )}

      {/* Typing indicator for online bots */}
      {online && <TypingDots />}

      {/* Hover glow overlay */}
      <div
        className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none"
        style={{
          boxShadow: `0 0 20px ${color}33, inset 0 0 20px ${color}11`,
        }}
      />
    </button>
  );
}

export function PixelOffice({ bots, myBotNames, onBotClick }: PixelOfficeProps) {
  ensureKeyframes();

  // Sort: online first, then my bots, then alphabetical
  const sortedBots = useMemo(() => {
    return [...bots].sort((a, b) => {
      if (a.online !== b.online) return a.online ? -1 : 1;
      const aMine = myBotNames.has(a.name);
      const bMine = myBotNames.has(b.name);
      if (aMine !== bMine) return aMine ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }, [bots, myBotNames]);

  const onlineCount = bots.filter((b) => b.online).length;

  return (
    <div
      className="rounded-xl border border-gray-800 overflow-hidden"
      style={{
        background: `
          linear-gradient(180deg, #0f1117 0%, #151821 100%)
        `,
        backgroundSize: "100% 100%",
      }}
    >
      {/* Floor grid pattern overlay */}
      <div
        className="relative p-4"
        style={{
          backgroundImage: `
            repeating-linear-gradient(0deg, transparent, transparent 39px, rgba(255,255,255,0.02) 39px, rgba(255,255,255,0.02) 40px),
            repeating-linear-gradient(90deg, transparent, transparent 39px, rgba(255,255,255,0.02) 39px, rgba(255,255,255,0.02) 40px)
          `,
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 font-medium tracking-wide uppercase">
              Office
            </span>
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{
                backgroundColor: onlineCount > 0 ? "#4ade80" : "#6b7280",
                animation:
                  onlineCount > 0
                    ? "po-glow 2s ease-in-out infinite"
                    : "none",
              }}
            />
            <span className="text-[10px] text-gray-600">
              {onlineCount}/{bots.length} online
            </span>
          </div>
        </div>

        {/* Bot grid */}
        <div
          className="grid gap-2"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(100px, 1fr))",
          }}
        >
          {sortedBots.map((bot) => (
            <DeskBot
              key={bot.bot_id}
              name={bot.name}
              online={bot.online}
              isMine={myBotNames.has(bot.name)}
              onClick={() => onBotClick(bot.name)}
            />
          ))}
        </div>

        {bots.length === 0 && (
          <div className="text-center text-gray-600 text-xs py-6">
            No bots in this organization
          </div>
        )}
      </div>
    </div>
  );
}
