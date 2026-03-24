/**
 * PixelOffice — Full Canvas-based pixel art office visualization.
 * Ported from OpenClaw-bot-review (MIT License).
 * Adapts HXA bot data to the office character system.
 */
import { useEffect, useRef, useCallback, useMemo } from "react";
import { OfficeState } from "../pixel-office/engine/officeState";
import { renderFrame } from "../pixel-office/engine/renderer";
import { syncAgentsToOffice, type AgentActivity } from "../pixel-office/agentBridge";
import { TILE_SIZE } from "../pixel-office/constants";
import { loadCharacterPNGs, loadWallPNG } from "../pixel-office/sprites/pngLoader";

export interface PixelOfficeProps {
  bots: Array<{ name: string; online: boolean; bot_id: string }>;
  myBotNames: Set<string>;
  onBotClick: (botName: string) => void;
}

/** Convert HXA bot list to AgentActivity format for the office engine */
function botsToActivities(
  bots: PixelOfficeProps["bots"],
  myBotNames: Set<string>,
): AgentActivity[] {
  return bots.map((bot) => ({
    agentId: bot.bot_id,
    name: bot.name,
    emoji: myBotNames.has(bot.name) ? "🤖" : "💼",
    state: bot.online ? "working" as const : "offline" as const,
    lastActive: bot.online ? Date.now() : 0,
  }));
}

export function PixelOffice({ bots, myBotNames, onBotClick }: PixelOfficeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const officeRef = useRef<OfficeState | null>(null);
  const agentIdMapRef = useRef(new Map<string, number>());
  const nextIdRef = useRef(1);
  const zoomRef = useRef(2.5);
  const panRef = useRef<{ x: number; y: number; _offsetX?: number; _offsetY?: number }>({ x: 0, y: 0 });
  const mouseRef = useRef({ x: 0, y: 0 });
  const hoveredCharRef = useRef<number | null>(null);
  const animFrameRef = useRef(0);
  const lastTimeRef = useRef(0);
  const spritesLoadedRef = useRef(false);

  // Bot name map for click handling
  const botNameMap = useMemo(() => {
    const m = new Map<string, string>();
    bots.forEach((b) => m.set(b.name, b.bot_id));
    return m;
  }, [bots]);

  // Initialize office
  useEffect(() => {
    const office = new OfficeState();
    officeRef.current = office;

    Promise.all([loadCharacterPNGs(), loadWallPNG()]).then(() => {
      spritesLoadedRef.current = true;
    }).catch(() => {
      spritesLoadedRef.current = true;
    });

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      officeRef.current = null;
    };
  }, []);

  // Sync bots to office characters
  useEffect(() => {
    const office = officeRef.current;
    if (!office) return;
    const activities = botsToActivities(bots, myBotNames);
    syncAgentsToOffice(activities, office, agentIdMapRef.current, nextIdRef);
  }, [bots, myBotNames]);

  // Render loop
  const render = useCallback((time: number) => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const office = officeRef.current;
    if (!canvas || !container || !office) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.floor(rect.width);
    const h = Math.floor(rect.height);
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
    }

    const dt = lastTimeRef.current ? Math.min((time - lastTimeRef.current) / 1000, 0.1) : 0.016;
    lastTimeRef.current = time;

    office.update(dt);

    const zoom = zoomRef.current;
    const mapW = office.layout.cols * TILE_SIZE * zoom;
    const mapH = office.layout.rows * TILE_SIZE * zoom;
    const offsetX = (w - mapW) / 2 + panRef.current.x;
    const offsetY = (h - mapH) / 2 + panRef.current.y;

    // Hit test for hovered character
    const tileX = (mouseRef.current.x - offsetX) / zoom;
    const tileY = (mouseRef.current.y - offsetY) / zoom;
    hoveredCharRef.current = null;
    for (const [id, ch] of office.characters) {
      const cx = ch.x + TILE_SIZE / 2;
      const cy = ch.y + TILE_SIZE / 2;
      // Wider hit area to include name label above character
      if (Math.abs(tileX - cx) < 20 && tileY > ch.y - 12 && tileY < ch.y + TILE_SIZE + 4) {
        hoveredCharRef.current = id;
        break;
      }
    }

    ctx.save();
    ctx.scale(dpr, dpr);

    // Extract data from OfficeState for renderFrame
    const chars = Array.from(office.characters.values());
    const result = renderFrame(
      ctx, w, h,
      office.tileMap,
      office.furniture,
      chars,
      zoom,
      panRef.current.x,
      panRef.current.y,
      undefined, // selection
      undefined, // editor
      office.layout.tileColors || undefined,
      office.layout.cols,
      office.layout.rows,
      office.getBugs?.() || undefined,
    );

    // Store offsets for click handling
    if (result) {
      panRef.current._offsetX = result.offsetX;
      panRef.current._offsetY = result.offsetY;
    }

    ctx.restore();
    animFrameRef.current = requestAnimationFrame(render);
  }, []);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(render);
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current); };
  }, [render]);

  // Mouse handlers
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }, []);

  const handleClick = useCallback(() => {
    const office = officeRef.current;
    if (!office || hoveredCharRef.current === null) return;
    const ch = office.characters.get(hoveredCharRef.current);
    if (ch?.label) {
      const name = ch.label.includes("(") ? ch.label.split("(")[0].trim() : ch.label;
      onBotClick(name);
    }
  }, [onBotClick]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.2 : 0.2;
    zoomRef.current = Math.max(0.8, Math.min(6, zoomRef.current + delta));
  }, []);

  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0, px: 0, py: 0 });

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
      isPanningRef.current = true;
      panStartRef.current = { x: e.clientX, y: e.clientY, px: panRef.current.x, py: panRef.current.y };
      e.preventDefault();
    }
  }, []);

  const handleMouseUp = useCallback(() => { isPanningRef.current = false; }, []);

  const handleMouseMoveCapture = useCallback((e: React.MouseEvent) => {
    if (isPanningRef.current) {
      panRef.current = {
        x: panStartRef.current.px + (e.clientX - panStartRef.current.x),
        y: panStartRef.current.py + (e.clientY - panStartRef.current.y),
      };
    }
    handleMouseMove(e);
  }, [handleMouseMove]);

  const onlineCount = bots.filter((b) => b.online).length;

  return (
    <div className="relative rounded-lg overflow-hidden border border-gray-800 bg-gray-950">
      <div className="absolute top-2 left-3 z-10 flex items-center gap-3">
        <span className="text-xs font-bold text-gray-300 bg-gray-900/80 px-2 py-1 rounded">🏢 OFFICE</span>
        <span className="text-[10px] text-gray-500 bg-gray-900/80 px-2 py-0.5 rounded">
          <span className="text-green-400">{onlineCount}</span>/{bots.length} online
        </span>
      </div>

      <div className="absolute top-2 right-3 z-10 flex gap-1">
        <button onClick={() => { zoomRef.current = Math.min(6, zoomRef.current + 0.3); }}
          className="text-xs bg-gray-800/80 text-gray-400 hover:text-white px-2 py-1 rounded">+</button>
        <button onClick={() => { zoomRef.current = Math.max(0.8, zoomRef.current - 0.3); }}
          className="text-xs bg-gray-800/80 text-gray-400 hover:text-white px-2 py-1 rounded">−</button>
        <button onClick={() => { zoomRef.current = 2.5; panRef.current = { x: 0, y: 0 }; }}
          className="text-xs bg-gray-800/80 text-gray-400 hover:text-white px-2 py-1 rounded">⊙</button>
      </div>

      <div className="absolute bottom-0 left-0 right-0 z-10 bg-gray-900/90 border-t border-gray-800 px-3 py-1.5 flex gap-2 overflow-x-auto">
        {bots.filter(b => b.online).sort((a, b) => a.name.localeCompare(b.name)).map((bot) => (
          <button key={bot.bot_id} onClick={() => onBotClick(bot.name)}
            className="shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] border border-gray-700 hover:border-blue-600 transition-colors bg-gray-800/50">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
            <span className="text-gray-300">{bot.name}</span>
            <span className="text-[9px] text-green-500 uppercase">ONLINE</span>
          </button>
        ))}
        {bots.filter(b => !b.online).map((bot) => (
          <button key={bot.bot_id} onClick={() => onBotClick(bot.name)}
            className="shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] border border-gray-800 bg-gray-900/50 opacity-50">
            <span className="h-1.5 w-1.5 rounded-full bg-gray-600" />
            <span className="text-gray-500">{bot.name}</span>
            <span className="text-[9px] text-gray-600 uppercase">OFFLINE</span>
          </button>
        ))}
      </div>

      <div ref={containerRef} className="w-full" style={{ height: "min(60vh, 500px)" }}>
        <canvas
          ref={canvasRef}
          className="block"
          style={{ width: "100%", height: "100%", cursor: "pointer" }}
          onMouseMove={handleMouseMoveCapture}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onClick={handleClick}
          onWheel={handleWheel}
        />
      </div>
    </div>
  );
}
