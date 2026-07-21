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
  markers = [],
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

  // Resolve each marker's x-position (as a %) from the data point sharing its
  // key; markers whose date isn't in the series are dropped.
  const xByKey = {};
  coords.forEach((c) => {
    if (c.d.key != null) xByKey[c.d.key] = c.x;
  });
  const activeMarkers = (markers || [])
    .map((m) => ({ ...m, x: xByKey[m.key] }))
    .filter((m) => m.x != null);

  return (
    <figure className="m-0" role="group" aria-label={label}>
      <div className="relative" style={{ height }}>
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
        {/* Deploy/change annotation markers overlaid as vertical guide lines. */}
        {activeMarkers.map((m, i) => (
          <div
            key={`${m.key}-${i}`}
            className="pointer-events-none absolute top-0 bottom-0 border-l border-dashed border-amber-400/70"
            style={{ left: `${m.x}%` }}
            aria-hidden="true"
          >
            <span
              className="absolute -top-0.5 left-1 whitespace-nowrap rounded bg-amber-400/15 px-1 text-[9px] text-amber-300"
              title={m.label}
            >
              ⚑ {m.label}
            </span>
          </div>
        ))}
      </div>
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
