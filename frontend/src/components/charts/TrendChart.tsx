/**
 * TrendChart — SVG line chart with axes for metrics display.
 * Ported from OpenClaw-bot-review's TrendChart component.
 */
export function TrendChart({
  data,
  height = 160,
  color = "#60a5fa",
  unit = "",
  label = "",
}: {
  data: { time: string; value: number }[];
  height?: number;
  color?: string;
  unit?: string;
  label?: string;
}) {
  if (!data || data.length < 2) {
    return (
      <div className="flex items-center justify-center text-gray-600 text-xs" style={{ height }}>
        暂无数据
      </div>
    );
  }

  const padL = 48, padR = 12, padT = 24, padB = 32;
  const width = 400;
  const chartW = width - padL - padR;
  const chartH = height - padT - padB;

  const maxVal = Math.max(...data.map((d) => d.value), 1);
  const yMax = Math.ceil(maxVal * 1.15);
  const yTicks = 4;
  const yStep = yMax / yTicks;

  const points = data.map((d, i) => ({
    x: padL + (i / (data.length - 1)) * chartW,
    y: padT + chartH - (d.value / yMax) * chartH,
  }));

  const polyline = points.map((p) => `${p.x},${p.y}`).join(" ");
  const polygon = `${padL},${padT + chartH} ${polyline} ${padL + chartW},${padT + chartH}`;
  const gradId = `trend-${Math.random().toString(36).slice(2, 8)}`;

  // X labels: show ~6 labels evenly
  const xLabelCount = Math.min(6, data.length);
  const xStep = Math.max(1, Math.floor(data.length / xLabelCount));

  return (
    <div>
      {label && <div className="text-xs text-gray-400 mb-1">{label}</div>}
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.2} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>

        {/* Y axis grid + labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const y = padT + chartH - (i * yStep / yMax) * chartH;
          const val = Math.round(i * yStep);
          return (
            <g key={`y-${i}`}>
              <line x1={padL} y1={y} x2={padL + chartW} y2={y} stroke="#374151" strokeWidth={0.5} />
              <text x={padL - 4} y={y + 3} fill="#6b7280" fontSize={9} textAnchor="end">
                {val}{unit}
              </text>
            </g>
          );
        })}

        {/* Area + Line */}
        <polygon points={polygon} fill={`url(#${gradId})`} />
        <polyline points={polyline} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />

        {/* Data points */}
        {points.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={2} fill={color}>
            <title>{data[i].time}: {data[i].value}{unit}</title>
          </circle>
        ))}

        {/* X axis labels */}
        {data.map((d, i) =>
          i % xStep === 0 ? (
            <text key={`x-${i}`} x={points[i].x} y={height - 4} fill="#6b7280" fontSize={8} textAnchor="middle">
              {d.time}
            </text>
          ) : null
        )}
      </svg>
    </div>
  );
}
