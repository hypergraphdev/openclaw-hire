/**
 * MiniSparkline — Tiny SVG area chart for inline metrics display.
 * Ported from OpenClaw-bot-review's MiniSparkline component.
 */
export function MiniSparkline({
  data,
  width = 80,
  height = 20,
  color,
}: {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (!data || data.length < 2) return null;

  const max = Math.max(...data, 1);
  const points = data.map((v, i) => ({
    x: (i / (data.length - 1)) * width,
    y: height - (v / max) * height * 0.85 - 1,
  }));

  // Determine trend color
  const trend = data[data.length - 1] - data[0];
  const autoColor = trend > 0 ? "#f87171" : trend < 0 ? "#4ade80" : "#f59e0b";
  const c = color || autoColor;

  const polyline = points.map((p) => `${p.x},${p.y}`).join(" ");
  const polygon = `0,${height} ${polyline} ${width},${height}`;
  const gradId = `spark-${Math.random().toString(36).slice(2, 8)}`;

  return (
    <svg width={width} height={height} className="inline-block align-middle">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={c} stopOpacity={0.3} />
          <stop offset="100%" stopColor={c} stopOpacity={0.05} />
        </linearGradient>
      </defs>
      <polygon points={polygon} fill={`url(#${gradId})`} />
      <polyline points={polyline} fill="none" stroke={c} strokeWidth={1.5} strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={1.2} fill={c} />
      ))}
    </svg>
  );
}
