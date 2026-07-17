// Reusable radar / spider chart (pure SVG). axes: [{ label, value }] with
// values expected in the 0..1 range (clamped). Renders concentric rings, one
// spoke per axis and the filled value polygon.
import ChartFallbackTable from "./ChartFallbackTable.jsx";

const SIZE = 220;
const CENTER = SIZE / 2;
const RADIUS = SIZE / 2 - 34;

function point(angle, radius) {
  return [
    CENTER + radius * Math.cos(angle),
    CENTER + radius * Math.sin(angle),
  ];
}

export default function RadarChart({
  axes = [],
  emptyMessage = "No metrics to chart.",
  label = "Radar chart",
  format = (v) => (v == null ? "—" : v.toFixed(2)),
}) {
  const scored = axes.filter((a) => a.value != null);
  if (scored.length < 3) {
    return <p className="py-8 text-center text-sm text-gray-500">{emptyMessage}</p>;
  }

  const n = scored.length;
  const angleFor = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;

  const rings = [0.25, 0.5, 0.75, 1];
  const polygon = scored
    .map((a, i) => {
      const v = Math.max(0, Math.min(1, a.value));
      return point(angleFor(i), RADIUS * v).map((c) => c.toFixed(1)).join(",");
    })
    .join(" ");
  const rows = scored.map((a, i) => ({
    key: a.label ?? i,
    label: String(a.label ?? i),
    value: format(a.value),
  }));

  return (
    <figure className="m-0" role="group" aria-label={label}>
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="mx-auto h-64 w-64"
      aria-hidden="true"
    >
      {rings.map((r) => (
        <polygon
          key={r}
          points={scored
            .map((_, i) => point(angleFor(i), RADIUS * r).map((c) => c.toFixed(1)).join(","))
            .join(" ")}
          className="fill-none stroke-ink-500"
          strokeWidth="0.5"
        />
      ))}
      {scored.map((a, i) => {
        const [x, y] = point(angleFor(i), RADIUS);
        const [lx, ly] = point(angleFor(i), RADIUS + 16);
        return (
          <g key={a.label}>
            <line
              x1={CENTER}
              y1={CENTER}
              x2={x}
              y2={y}
              className="stroke-ink-500"
              strokeWidth="0.5"
            />
            <text
              x={lx}
              y={ly}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-gray-300 text-[7px]"
            >
              {a.label}
            </text>
          </g>
        );
      })}
      <polygon
        points={polygon}
        className="fill-accent/25 stroke-accent"
        strokeWidth="1.5"
      />
    </svg>
      <ChartFallbackTable caption={label} columns={["Metric", "Score"]} rows={rows} />
    </figure>
  );
}
