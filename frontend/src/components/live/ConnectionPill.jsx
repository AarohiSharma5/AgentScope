// Connection status indicator for the live stream.
const STYLES = {
  open: { dot: "bg-emerald-400 animate-pulse", text: "text-emerald-400", label: "Live" },
  connecting: { dot: "bg-sky-400 animate-pulse", text: "text-sky-400", label: "Connecting" },
  reconnecting: { dot: "bg-amber-400 animate-pulse", text: "text-amber-400", label: "Reconnecting" },
  paused: { dot: "bg-gray-400", text: "text-gray-400", label: "Paused" },
  error: { dot: "bg-rose-400", text: "text-rose-400", label: "Disconnected" },
};

export default function ConnectionPill({ status }) {
  const style = STYLES[status] || STYLES.connecting;
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border border-ink-500 bg-ink-800 px-3 py-1 text-xs font-medium ${style.text}`}
    >
      <span className={`h-2 w-2 rounded-full ${style.dot}`} />
      {style.label}
    </span>
  );
}
