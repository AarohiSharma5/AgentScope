// Status pill used across requests and agent runs/steps.
// success / failed keep their original look; running / pending are additive.
const STYLES = {
  success: {
    wrap: "bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20",
    dot: "bg-emerald-400",
    label: "Success",
  },
  failed: {
    wrap: "bg-rose-500/10 text-rose-400 ring-1 ring-rose-500/20",
    dot: "bg-rose-400",
    label: "Failed",
  },
  running: {
    wrap: "bg-sky-500/10 text-sky-400 ring-1 ring-sky-500/20",
    dot: "bg-sky-400 animate-pulse",
    label: "Running",
  },
  pending: {
    wrap: "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20",
    dot: "bg-amber-400",
    label: "Pending",
  },
  cancelled: {
    wrap: "bg-gray-500/10 text-gray-400 ring-1 ring-gray-500/20",
    dot: "bg-gray-400",
    label: "Cancelled",
  },
  timeout: {
    wrap: "bg-orange-500/10 text-orange-400 ring-1 ring-orange-500/20",
    dot: "bg-orange-400",
    label: "Timeout",
  },
};

export default function StatusBadge({ status }) {
  const style = STYLES[status] || {
    wrap: "bg-gray-500/10 text-gray-400 ring-1 ring-gray-500/20",
    dot: "bg-gray-400",
    label: status || "Unknown",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${style.wrap}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {style.label}
    </span>
  );
}
