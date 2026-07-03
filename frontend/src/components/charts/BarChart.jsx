// Reusable vertical bar chart (pure SVG, no dependencies).
// data: [{ label, value }]. `format` renders the value tooltip/axis.
export default function BarChart({
  data = [],
  format = (v) => (v == null ? "—" : String(v)),
  height = 160,
  color = "bg-accent/70",
  emptyMessage = "No data to chart.",
}) {
  const points = data.filter((d) => d.value != null);
  if (points.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-500">{emptyMessage}</p>;
  }
  const max = Math.max(...points.map((d) => d.value), 0) || 1;

  return (
    <div className="flex items-end gap-2" style={{ height }}>
      {data.map((d, i) => {
        const value = d.value ?? 0;
        const pct = max ? (value / max) * 100 : 0;
        return (
          <div
            key={d.label ?? i}
            className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1"
            title={`${d.label}: ${format(d.value)}`}
          >
            <span className="text-[10px] text-gray-400">
              {d.value == null ? "" : format(d.value)}
            </span>
            <div
              className={`w-full rounded-t ${color}`}
              style={{ height: `${pct}%`, minHeight: d.value ? 3 : 0 }}
            />
            <span className="w-full truncate text-center text-[10px] text-gray-600">
              {d.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
