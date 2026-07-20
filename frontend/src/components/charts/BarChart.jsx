// Reusable vertical bar chart (pure SVG, no dependencies).
// data: [{ label, value }]. `format` renders the value tooltip/axis.
import ChartFallbackTable from "./ChartFallbackTable.jsx";

export default function BarChart({
  data = [],
  format = (v) => (v == null ? "—" : String(v)),
  height = 160,
  color = "bg-accent/70",
  emptyMessage = "No data to chart.",
  label = "Bar chart",
  onSelect,
  selectedKey,
}) {
  const points = data.filter((d) => d.value != null);
  if (points.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-500">{emptyMessage}</p>;
  }
  const max = Math.max(...points.map((d) => d.value), 0) || 1;
  const rows = points.map((d, i) => ({
    key: d.label ?? i,
    label: String(d.label ?? i),
    value: format(d.value),
  }));
  // Interactive mode makes each bar a real button so it's keyboard-focusable;
  // in that case the buttons carry the accessible labels, so the container is
  // no longer aria-hidden and the sr-only fallback table would be redundant.
  const interactive = typeof onSelect === "function";

  return (
    <figure className="m-0" role="group" aria-label={label}>
      <div className="flex items-end gap-2" style={{ height }} aria-hidden={!interactive}>
        {data.map((d, i) => {
          const value = d.value ?? 0;
          const pct = max ? (value / max) * 100 : 0;
          const selected = interactive && d.key != null && d.key === selectedKey;
          const inner = (
            <>
              <span aria-hidden="true" className="text-[10px] text-gray-300">
                {d.value == null ? "" : format(d.value)}
              </span>
              <div
                className={`w-full rounded-t ${color} ${
                  selected ? "ring-2 ring-accent ring-offset-1 ring-offset-ink-700" : ""
                }`}
                style={{ height: `${pct}%`, minHeight: d.value ? 3 : 0 }}
              />
              <span
                aria-hidden="true"
                className="w-full truncate text-center text-[10px] text-gray-400"
              >
                {d.label}
              </span>
            </>
          );
          const shared = "flex min-w-0 flex-1 flex-col items-center justify-end gap-1";
          if (interactive) {
            return (
              <button
                key={d.key ?? d.label ?? i}
                type="button"
                onClick={() => onSelect(d)}
                aria-pressed={selected}
                aria-label={`${d.label}: ${format(d.value)}`}
                title={`${d.label}: ${format(d.value)}`}
                className={`${shared} appearance-none border-0 bg-transparent p-0 transition-opacity hover:opacity-80 focus:outline-none focus-visible:opacity-100 ${
                  selected ? "opacity-100" : ""
                }`}
              >
                {inner}
              </button>
            );
          }
          return (
            <div
              key={d.label ?? i}
              className={shared}
              title={`${d.label}: ${format(d.value)}`}
            >
              {inner}
            </div>
          );
        })}
      </div>
      {!interactive && <ChartFallbackTable caption={label} rows={rows} />}
    </figure>
  );
}
