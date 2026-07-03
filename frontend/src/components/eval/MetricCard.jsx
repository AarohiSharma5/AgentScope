import { fmtScore } from "../../lib/format.js";

// A single metric: name, 0..1 score, weight and an inline progress bar.
// Bar colour follows the score (green ≥ .7, amber ≥ .4, rose below).
function barColor(value) {
  if (value == null) return "bg-gray-600";
  if (value >= 0.7) return "bg-emerald-500";
  if (value >= 0.4) return "bg-amber-500";
  return "bg-rose-500";
}

function humanize(name) {
  return String(name || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function MetricCard({ metric }) {
  const value = metric.metric_value ?? metric.value ?? null;
  const name = metric.metric_name ?? metric.name;
  const pct = value == null ? 0 : Math.max(0, Math.min(1, value)) * 100;

  return (
    <div className="rounded-xl border border-ink-500 bg-ink-700 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="truncate text-sm font-medium text-gray-200" title={humanize(name)}>
          {humanize(name)}
        </p>
        <span className="shrink-0 font-mono text-sm text-gray-100">{fmtScore(value)}</span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink-500">
        <div className={`h-full rounded-full ${barColor(value)}`} style={{ width: `${pct}%` }} />
      </div>
      {(metric.weight != null || metric.notes) && (
        <p className="mt-2 truncate text-xs text-gray-500" title={metric.notes || ""}>
          {metric.weight != null ? `weight ${metric.weight}` : ""}
          {metric.weight != null && metric.notes ? " · " : ""}
          {metric.notes || ""}
        </p>
      )}
    </div>
  );
}

export { humanize };
