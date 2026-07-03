// Compact metric card for the live dashboard. When `active` (value > 0) it
// shows a pulsing accent dot to signal in-flight work.
export default function LiveStatCard({ label, value, sublabel, accent = "#6366f1", active }) {
  return (
    <div className="rounded-xl border border-ink-500 bg-ink-700 p-5 transition-colors hover:border-accent/50">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-gray-500">{label}</p>
        {active ? (
          <span
            className="h-2 w-2 rounded-full animate-pulse"
            style={{ backgroundColor: accent }}
            aria-hidden
          />
        ) : null}
      </div>
      <p className="mt-2 text-2xl font-semibold text-gray-100">{value}</p>
      {sublabel && <p className="mt-1 text-xs text-gray-500">{sublabel}</p>}
    </div>
  );
}
