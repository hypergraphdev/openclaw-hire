import { useMemo, useEffect } from "react";

interface PixelOfficeProps {
  bots: Array<{ name: string; online: boolean; bot_id: string }>;
  myBotNames: Set<string>;
  onBotClick: (botName: string) => void;
}

/* ── Color palettes for pixel characters ── */
const PALETTES = [
  { shirt: "#4488CC", hair: "#553322" }, // blue
  { shirt: "#CC4444", hair: "#FFD700" }, // red
  { shirt: "#44AA66", hair: "#222222" }, // green
  { shirt: "#AA55CC", hair: "#AA4422" }, // purple
  { shirt: "#CCAA33", hair: "#553322" }, // yellow
  { shirt: "#FF8844", hair: "#111111" }, // orange
];

const SKIN_COLORS = ["#F5D0A9", "#E8B88A", "#D4A574", "#C49A6C", "#F0C8A0", "#DEB887"];

function nameHash(name: string): number {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash);
}

function getPalette(name: string) {
  const h = nameHash(name);
  return PALETTES[h % PALETTES.length];
}

function getSkin(name: string) {
  const h = nameHash(name + "_skin");
  return SKIN_COLORS[h % SKIN_COLORS.length];
}

/* ── Inject keyframes once ── */
const STYLE_TAG_ID = "pixel-office-keyframes-v2";

function ensureKeyframes() {
  if (typeof document === "undefined") return;
  if (document.getElementById(STYLE_TAG_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_TAG_ID;
  style.textContent = `
    @keyframes po-breathe {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.02); }
    }
    @keyframes po-type {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-2px); }
    }
    @keyframes po-pulse {
      0%, 100% { opacity: 0.7; }
      50% { opacity: 1; }
    }
    @keyframes po-wander {
      0%, 80%, 100% { transform: translateY(0); }
      90% { transform: translateY(-3px); }
    }
    @keyframes po-glow {
      0%, 100% { box-shadow: 0 0 4px rgba(34,197,94,0.3); }
      50% { box-shadow: 0 0 8px rgba(34,197,94,0.6); }
    }
    @keyframes po-screen {
      0%, 100% { opacity: 0.8; }
      50% { opacity: 1; }
    }
    @keyframes po-typing-dot {
      0%, 80%, 100% { opacity: 0.2; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }
    @keyframes po-desk-hover {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-4px); }
    }
  `;
  document.head.appendChild(style);
}

/* ── Typing dots indicator ── */
function TypingDots() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "2px", justifyContent: "center", height: "8px" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            display: "inline-block",
            width: "3px",
            height: "3px",
            borderRadius: "50%",
            backgroundColor: "#4ade80",
            animation: "po-typing-dot 1.4s ease-in-out infinite",
            animationDelay: `${i * 0.2}s`,
          }}
        />
      ))}
    </div>
  );
}

/* ── Pixel Bot Character (pure CSS) ── */
function PixelCharacter({
  name,
  online,
  wanderDelay,
}: {
  name: string;
  online: boolean;
  wanderDelay: number;
}) {
  const palette = getPalette(name);
  const skin = getSkin(name);

  const baseStyle: React.CSSProperties = online
    ? {
        animation: `po-breathe 3s ease-in-out infinite, po-wander 8s ease-in-out infinite`,
        animationDelay: `0s, ${wanderDelay}s`,
      }
    : {
        filter: "grayscale(0.9)",
        opacity: 0.35,
      };

  return (
    <div
      style={{
        position: "relative",
        width: "24px",
        height: "34px",
        ...baseStyle,
      }}
    >
      {/* Hair */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: "4px",
          width: "16px",
          height: "5px",
          backgroundColor: palette.hair,
          borderRadius: "3px 3px 0 0",
        }}
      />
      {/* Head */}
      <div
        style={{
          position: "absolute",
          top: "4px",
          left: "4px",
          width: "16px",
          height: "14px",
          backgroundColor: skin,
          borderRadius: "3px",
        }}
      >
        {/* Left eye */}
        <div
          style={{
            position: "absolute",
            top: "5px",
            left: "3px",
            width: "3px",
            height: "3px",
            backgroundColor: online ? "#fff" : "#999",
            borderRadius: "1px",
          }}
        />
        {/* Right eye */}
        <div
          style={{
            position: "absolute",
            top: "5px",
            right: "3px",
            width: "3px",
            height: "3px",
            backgroundColor: online ? "#fff" : "#999",
            borderRadius: "1px",
          }}
        />
        {/* Mouth - tiny smile for online */}
        {online && (
          <div
            style={{
              position: "absolute",
              bottom: "2px",
              left: "50%",
              transform: "translateX(-50%)",
              width: "6px",
              height: "2px",
              borderBottom: "1.5px solid #c0755a",
              borderRadius: "0 0 3px 3px",
            }}
          />
        )}
      </div>
      {/* Body / Shirt */}
      <div
        style={{
          position: "absolute",
          top: "18px",
          left: "2px",
          width: "20px",
          height: "12px",
          backgroundColor: palette.shirt,
          borderRadius: "2px 2px 3px 3px",
        }}
      />
      {/* Left arm */}
      <div
        style={{
          position: "absolute",
          top: "19px",
          left: "0px",
          width: "4px",
          height: "10px",
          backgroundColor: palette.shirt,
          borderRadius: "2px",
          animation: online ? "po-type 0.3s ease-in-out infinite" : "none",
          animationDelay: "0s",
        }}
      />
      {/* Right arm */}
      <div
        style={{
          position: "absolute",
          top: "19px",
          right: "0px",
          width: "4px",
          height: "10px",
          backgroundColor: palette.shirt,
          borderRadius: "2px",
          animation: online ? "po-type 0.3s ease-in-out infinite" : "none",
          animationDelay: "0.15s",
        }}
      />
      {/* Legs */}
      <div
        style={{
          position: "absolute",
          bottom: "0",
          left: "4px",
          width: "6px",
          height: "5px",
          backgroundColor: "#334",
          borderRadius: "0 0 2px 2px",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: "0",
          right: "4px",
          width: "6px",
          height: "5px",
          backgroundColor: "#334",
          borderRadius: "0 0 2px 2px",
        }}
      />
    </div>
  );
}

/* ── Single Desk Unit ── */
function DeskUnit({
  name,
  online,
  isMine,
  onClick,
  wanderDelay,
}: {
  name: string;
  online: boolean;
  isMine: boolean;
  onClick: () => void;
  wanderDelay: number;
}) {
  return (
    <button
      onClick={onClick}
      title={`${name}${online ? " (online)" : " (offline)"}`}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "8px 4px 6px",
        border: "none",
        background: "transparent",
        cursor: "pointer",
        borderRadius: "8px",
        transition: "transform 0.2s ease, box-shadow 0.2s ease",
        position: "relative",
        minWidth: "110px",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-4px)";
        e.currentTarget.style.boxShadow = "0 4px 16px rgba(59,130,246,0.15)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {/* Chair behind desk */}
      <div
        style={{
          position: "absolute",
          bottom: "38px",
          width: "20px",
          height: "14px",
          background: "linear-gradient(180deg, #555 0%, #3a3a3a 100%)",
          borderRadius: "6px 6px 2px 2px",
          zIndex: 0,
        }}
      />
      {/* Chair back */}
      <div
        style={{
          position: "absolute",
          bottom: "50px",
          width: "16px",
          height: "18px",
          background: "linear-gradient(180deg, #666 0%, #444 100%)",
          borderRadius: "4px 4px 0 0",
          zIndex: 0,
        }}
      />

      {/* Bot character */}
      <div style={{ position: "relative", zIndex: 2, marginBottom: "2px" }}>
        <PixelCharacter name={name} online={online} wanderDelay={wanderDelay} />
      </div>

      {/* Monitor */}
      <div
        style={{
          position: "relative",
          zIndex: 1,
          width: "32px",
          height: "22px",
          background: online
            ? "linear-gradient(135deg, #1a2a3a 0%, #0d1520 100%)"
            : "#1a1a22",
          border: `1px solid ${online ? "#334155" : "#252530"}`,
          borderRadius: "2px",
          marginBottom: "-2px",
        }}
      >
        {/* Screen content */}
        {online && (
          <div
            style={{
              width: "100%",
              height: "100%",
              borderRadius: "1px",
              background: "linear-gradient(135deg, rgba(56,189,248,0.12) 0%, rgba(16,185,129,0.08) 100%)",
              animation: "po-screen 3s ease-in-out infinite",
            }}
          >
            {/* Fake code lines on screen */}
            <div style={{ padding: "3px", display: "flex", flexDirection: "column", gap: "2px" }}>
              <div style={{ width: "60%", height: "1.5px", backgroundColor: "rgba(56,189,248,0.3)", borderRadius: "1px" }} />
              <div style={{ width: "80%", height: "1.5px", backgroundColor: "rgba(16,185,129,0.25)", borderRadius: "1px" }} />
              <div style={{ width: "45%", height: "1.5px", backgroundColor: "rgba(56,189,248,0.2)", borderRadius: "1px" }} />
              <div style={{ width: "70%", height: "1.5px", backgroundColor: "rgba(168,85,247,0.2)", borderRadius: "1px" }} />
            </div>
          </div>
        )}
      </div>
      {/* Monitor stand */}
      <div
        style={{
          width: "6px",
          height: "4px",
          backgroundColor: "#444",
          zIndex: 1,
        }}
      />

      {/* Desk surface */}
      <div
        style={{
          width: "90px",
          height: "14px",
          background: "linear-gradient(180deg, #A07828 0%, #8B6914 40%, #7a5c10 100%)",
          borderRadius: "3px",
          boxShadow: "0 2px 4px rgba(0,0,0,0.4)",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Desk edge highlight */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: "2px",
            background: "linear-gradient(90deg, transparent, rgba(255,220,130,0.3), transparent)",
            borderRadius: "3px 3px 0 0",
          }}
        />
      </div>
      {/* Desk legs */}
      <div style={{ display: "flex", justifyContent: "space-between", width: "80px" }}>
        <div style={{ width: "4px", height: "8px", backgroundColor: "#6a5210", borderRadius: "0 0 1px 1px" }} />
        <div style={{ width: "4px", height: "8px", backgroundColor: "#6a5210", borderRadius: "0 0 1px 1px" }} />
      </div>

      {/* Name label area */}
      <div style={{ marginTop: "4px", display: "flex", flexDirection: "column", alignItems: "center", gap: "2px" }}>
        {/* Online typing dots */}
        {online && <TypingDots />}

        {/* Name + status dot */}
        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: online ? "#4ade80" : "#6b7280",
              display: "inline-block",
              animation: online ? "po-glow 2s ease-in-out infinite" : "none",
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontSize: "11px",
              color: online ? "#e5e7eb" : "#6b7280",
              maxWidth: "80px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              animation: online ? "po-pulse 3s ease-in-out infinite" : "none",
              fontFamily: "'Courier New', monospace",
            }}
          >
            {name}
          </span>
        </div>

        {/* My bot badge */}
        {isMine && (
          <span
            style={{
              fontSize: "9px",
              padding: "1px 6px",
              borderRadius: "8px",
              backgroundColor: "rgba(59, 130, 246, 0.25)",
              color: "#60a5fa",
              border: "1px solid rgba(59, 130, 246, 0.3)",
              fontFamily: "monospace",
            }}
          >
            我的
          </span>
        )}
      </div>
    </button>
  );
}

/* ── Wall with windows decoration ── */
function OfficeWall() {
  return (
    <div
      style={{
        height: "32px",
        background: "linear-gradient(180deg, #0a0a1a 0%, #0f0f23 60%, #151530 100%)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "40px",
        paddingTop: "4px",
        borderBottom: "2px solid #222244",
        position: "relative",
      }}
    >
      {/* Windows */}
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            width: "24px",
            height: "16px",
            background: "linear-gradient(180deg, #1a2040 0%, #0d1530 100%)",
            border: "1px solid #333366",
            borderRadius: "2px",
            boxShadow: "inset 0 0 4px rgba(100,140,255,0.1)",
          }}
        >
          {/* Window cross */}
          <div style={{ position: "relative", width: "100%", height: "100%" }}>
            <div style={{ position: "absolute", top: "50%", left: 0, right: 0, height: "1px", backgroundColor: "#333366" }} />
            <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: "1px", backgroundColor: "#333366" }} />
          </div>
        </div>
      ))}
      {/* Clock */}
      <div style={{ position: "absolute", right: "12px", top: "6px", fontSize: "14px" }}>🕐</div>
    </div>
  );
}

/* ── Main Component ── */
export function PixelOffice({ bots, myBotNames, onBotClick }: PixelOfficeProps) {
  useEffect(() => {
    ensureKeyframes();
  }, []);

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
      style={{
        borderRadius: "12px",
        border: "1px solid #2a2a40",
        overflow: "hidden",
        background: "#1a1a2e",
      }}
    >
      {/* Wall */}
      <OfficeWall />

      {/* Floor area */}
      <div
        style={{
          padding: "12px",
          backgroundImage: `
            repeating-linear-gradient(
              0deg,
              transparent,
              transparent 63px,
              rgba(255,255,255,0.025) 63px,
              rgba(255,255,255,0.025) 64px
            ),
            repeating-linear-gradient(
              90deg,
              transparent,
              transparent 63px,
              rgba(255,255,255,0.025) 63px,
              rgba(255,255,255,0.025) 64px
            )
          `,
          position: "relative",
        }}
      >
        {/* Header bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "12px",
            padding: "6px 10px",
            background: "rgba(15,15,35,0.6)",
            borderRadius: "6px",
            border: "1px solid rgba(255,255,255,0.05)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "14px" }}>🏢</span>
            <span
              style={{
                fontSize: "12px",
                color: "#9ca3af",
                fontWeight: 600,
                letterSpacing: "0.05em",
                textTransform: "uppercase",
                fontFamily: "'Courier New', monospace",
              }}
            >
              Office
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {/* Online count */}
            <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <span
                style={{
                  width: "6px",
                  height: "6px",
                  borderRadius: "50%",
                  backgroundColor: onlineCount > 0 ? "#4ade80" : "#6b7280",
                  display: "inline-block",
                  animation: onlineCount > 0 ? "po-glow 2s ease-in-out infinite" : "none",
                }}
              />
              <span style={{ fontSize: "11px", color: "#6b7280", fontFamily: "monospace" }}>
                <span style={{ color: onlineCount > 0 ? "#4ade80" : "#6b7280" }}>{onlineCount}</span>
                /{bots.length} online
              </span>
            </div>

            {/* Legend */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "3px" }}>
                <span style={{ width: "4px", height: "4px", borderRadius: "50%", backgroundColor: "#4ade80", display: "inline-block" }} />
                <span style={{ fontSize: "9px", color: "#6b7280" }}>在线</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "3px" }}>
                <span style={{ width: "4px", height: "4px", borderRadius: "50%", backgroundColor: "#6b7280", display: "inline-block" }} />
                <span style={{ fontSize: "9px", color: "#6b7280" }}>离线</span>
              </div>
            </div>
          </div>
        </div>

        {/* Decorations row */}
        <div style={{ display: "flex", alignItems: "center", gap: "4px", marginBottom: "8px" }}>
          <span style={{ fontSize: "12px" }}>🪴</span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: "12px" }}>🧊</span>
        </div>

        {/* Bot desk grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
            gap: "8px",
            justifyItems: "center",
          }}
        >
          {sortedBots.map((bot, idx) => (
            <DeskUnit
              key={bot.bot_id}
              name={bot.name}
              online={bot.online}
              isMine={myBotNames.has(bot.name)}
              onClick={() => onBotClick(bot.name)}
              wanderDelay={(nameHash(bot.name) % 5) + idx * 0.7}
            />
          ))}
        </div>

        {/* Scattered plants between desks */}
        {sortedBots.length > 3 && (
          <div
            style={{
              position: "absolute",
              bottom: "16px",
              right: "16px",
              fontSize: "14px",
              opacity: 0.6,
            }}
          >
            🪴
          </div>
        )}

        {bots.length === 0 && (
          <div
            style={{
              textAlign: "center",
              color: "#6b7280",
              fontSize: "12px",
              padding: "32px 0",
              fontFamily: "'Courier New', monospace",
            }}
          >
            办公室空无一人...
          </div>
        )}
      </div>
    </div>
  );
}
