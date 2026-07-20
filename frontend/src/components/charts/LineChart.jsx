// Reusable line chart (pure SVG, no dependencies).
// data: [{ label, value }]. Renders a polyline with dots over a normalized grid.
import ChartFallbackTable from "./ChartFallbackTable.jsx";

export default function LineChart({
  data = [],
  format = (v) => (v == null ? "—" : String(v)),
  height = 160,
  emptyMessage = "No data to chart.",
  label = "Line chart",
  onSelect,
  selectedKey,
}) {
  const interactive = typeof onSelect === "function";
  const points = data.filter((d) => d.value != null);
  if (points.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-500">{emptyMessage}</p>;
  }

  const W = 100;
  const H = 100;
  const values = points.map((d) => d.value);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const stepX = points.length > 1 ? W / (points.length - 1) : 0;

  const coords = points.map((d, i) => ({
    x: points.length > 1 ? i * stepX : W / 2,
    y: H - ((d.value - min) / span) * (H - 10) - 5,
    d,
  }));
  const path = coords.map((c) => `${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(" ");
  const rows = points.map((d, i) => ({
    key: d.label ?? i,
    label: String(d.label ?? i),
    value: format(d.value),
  }));

  return (
    <figure className="m-0" role="group" aria-label={label} style={{ height }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-full w-full"
        aria-hidden="true"
      >
        <polyline
          points={path}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="text-accent"
          vectorEffect="non-scaling-stroke"
        />
        {coords.map((c, i) => {
          const selected = interactive && c.d.key != null && c.d.key === selectedKey;
          return (
            <circle
              key={i}
              cx={c.x}
              cy={c.y}
              r={selected ? "3" : "1.6"}
              className={`fill-accent ${interactive ? "cursor-pointer" : ""}`}
              vectorEffect="non-scaling-stroke"
              onClick={interactive ? () => onSelect(c.d) : undefined}
            >
              <title>{`${c.d.label}: ${format(c.d.value)}`}</title>
            </circle>
          );
        })}
      </svg>
      <div
        className="mt-1 flex justify-between text-[10px] text-gray-400"
        aria-hidden="true"
      >
        <span>{points[0].label}</span>
        <span>{points[points.length - 1].label}</span>
      </div>
      <ChartFallbackTable caption={label} rows={rows} />
    </figure>
  );
}
