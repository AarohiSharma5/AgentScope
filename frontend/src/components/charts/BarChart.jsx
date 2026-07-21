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
  // With many bars (e.g. a 90-day window), per-bar value/date text collapses
  // into an unreadable smear. Past a threshold we drop the inline labels and
  // fall back to first/last axis labels below — the value stays available on
  // hover/focus (title + aria-label). Small charts keep their inline labels.
  const dense = data.length > 24;
  const gap = dense ? "gap-px" : "gap-2";

  return (
    <figure className="m-0" role="group" aria-label={label}>
      <div className={`flex items-end ${gap}`} style={{ height }} aria-hidden={!interactive}>
        {data.map((d, i) => {
          const value = d.value ?? 0;
          const pct = max ? (value / max) * 100 : 0;
          const selected = interactive && d.key != null && d.key === selectedKey;
          const inner = (
            <>
              {!dense && (
                <span aria-hidden="true" className="text-[10px] text-gray-300">
                  {d.value == null ? "" : format(d.value)}
                </span>
              )}
              <div
                className={`w-full rounded-t ${color} ${
                  selected ? "ring-2 ring-accent ring-offset-1 ring-offset-ink-700" : ""
                }`}
                style={{ height: `${pct}%`, minHeight: d.value ? 3 : 0 }}
              />
              {!dense && (
                <span
                  aria-hidden="true"
                  className="w-full truncate text-center text-[10px] text-gray-400"
                >
                  {d.label}
                </span>
              )}
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
      {dense && (
        <div
          className="mt-1 flex justify-between text-[10px] text-gray-400"
          aria-hidden="true"
        >
          <span>{data[0]?.label}</span>
          <span>{data[data.length - 1]?.label}</span>
        </div>
      )}
      {!interactive && <ChartFallbackTable caption={label} rows={rows} />}
    </figure>
  );
}
