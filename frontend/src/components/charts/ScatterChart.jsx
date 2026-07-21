// Reusable quadrant scatter plot (pure CSS/HTML positioning, no dependencies).
// data: [{ x, y, label, size }]. Median guide lines split the plot into four
// quadrants; points are colored by whether they land in the "good" corner
// (low x / high y by default, e.g. cheap + high quality) or the "bad" one.
import ChartFallbackTable from "./ChartFallbackTable.jsx";

const PAD = 10; // inner padding (%) so points never sit on the edge

function median(nums) {
  if (nums.length === 0) return null;
  const s = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export default function ScatterChart({
  data = [],
  xFormat = (v) => String(v),
  yFormat = (v) => String(v),
  xLabel = "X",
  yLabel = "Y",
  height = 260,
  emptyMessage = "No data to chart.",
  label = "Scatter chart",
  legend = [],
}) {
  const points = data.filter((d) => d.x != null && d.y != null);
  if (points.length === 0) {
    return <p className="py-8 text-center text-sm text-gray-500">{emptyMessage}</p>;
  }

  const xs = points.map((d) => d.x);
  const ys = points.map((d) => d.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xSpan = xMax - xMin || 1;
  const ySpan = yMax - yMin || 1;
  const sizes = points.map((d) => d.size).filter((s) => s != null);
  const sizeMax = sizes.length ? Math.max(...sizes) : 0;

  // Map a value into the inner [PAD, 100-PAD] band; y is inverted (SVG-style).
  const left = (x) => PAD + ((x - xMin) / xSpan) * (100 - 2 * PAD);
  const top = (y) => PAD + ((yMax - y) / ySpan) * (100 - 2 * PAD);
  const radius = (size) => {
    if (!size || !sizeMax) return 9;
    return 7 + (size / sizeMax) * 11; // 7px..18px by relative volume
  };

  const xMed = median(xs);
  const yMed = median(ys);
  const rows = points.map((d, i) => ({
    key: d.label ?? i,
    label: String(d.label ?? i),
    value: `${xLabel} ${xFormat(d.x)}, ${yLabel} ${yFormat(d.y)}`,
  }));

  return (
    <figure className="m-0" role="group" aria-label={label}>
      <div className="flex">
        <span className="mr-1 flex items-center text-[10px] uppercase tracking-wider text-gray-500 [writing-mode:vertical-rl] rotate-180">
          {yLabel} ↑
        </span>
        <div
          className="relative flex-1 rounded-md border border-ink-500 bg-ink-800/40"
          style={{ height }}
          aria-hidden="true"
        >
          {/* Median guide lines splitting the plot into four quadrants. */}
          {xMed != null && (
            <div
              className="absolute top-0 bottom-0 border-l border-dashed border-ink-500"
              style={{ left: `${left(xMed)}%` }}
            />
          )}
          {yMed != null && (
            <div
              className="absolute left-0 right-0 border-t border-dashed border-ink-500"
              style={{ top: `${top(yMed)}%` }}
            />
          )}
          {/* Corner hint for the ideal quadrant (top-left: cheap + high quality). */}
          <span className="absolute left-1.5 top-1.5 text-[10px] font-medium text-emerald-400/80">
            ideal
          </span>

          {points.map((d, i) => {
            const cheap = xMed == null || d.x <= xMed;
            const good = yMed == null || d.y >= yMed;
            // A per-point color (e.g. by provider) takes precedence; otherwise
            // fall back to encoding the quadrant (ideal green / worst red).
            const color =
              d.color ||
              (cheap && good
                ? "bg-emerald-500/80 border-emerald-300"
                : !cheap && !good
                  ? "bg-rose-500/80 border-rose-300"
                  : "bg-accent/80 border-accent");
            const r = radius(d.size);
            return (
              <div
                key={d.label ?? i}
                className="absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${left(d.x)}%`, top: `${top(d.y)}%` }}
                title={`${d.label}: ${xLabel} ${xFormat(d.x)}, ${yLabel} ${yFormat(d.y)}`}
              >
                <div
                  className={`rounded-full border ${color}`}
                  style={{ width: r, height: r }}
                />
                <span className="mt-0.5 block max-w-[80px] truncate text-center text-[10px] text-gray-300">
                  {d.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-1 pl-5 text-right text-[10px] uppercase tracking-wider text-gray-500">
        {xLabel} →
      </div>
      {legend.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 pl-5" aria-hidden="true">
          {legend.map((g) => (
            <span key={g.label} className="inline-flex items-center gap-1.5 text-[11px] text-gray-400">
              <span className={`h-2.5 w-2.5 rounded-full border ${g.color}`} />
              {g.label}
            </span>
          ))}
        </div>
      )}
      <ChartFallbackTable caption={label} rows={rows} />
    </figure>
  );
}
