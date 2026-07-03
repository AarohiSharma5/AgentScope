import { colorForType, describeEvent } from "../../lib/liveEvents.js";
import EmptyState from "../ui/EmptyState.jsx";

function relativeTime(iso) {
  if (!iso) return "";
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 2) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}

// Vertical, auto-updating timeline of the most recent stream events.
export default function LiveTimeline({ events, limit = 40 }) {
  if (!events.length) {
    return <EmptyState icon="≋" message="Waiting for live activity…" />;
  }

  return (
    <ol className="relative max-h-[460px] space-y-1 overflow-y-auto pl-4">
      <span className="absolute left-[7px] top-1 bottom-1 w-px bg-ink-500" aria-hidden />
      {events.slice(0, limit).map((event, i) => (
        <li key={`${event.id ?? "e"}-${i}`} className="relative flex items-start gap-3 py-1.5">
          <span
            className="absolute -left-4 mt-1.5 h-3 w-3 rounded-full border-2 border-ink-800"
            style={{ backgroundColor: colorForType(event.type) }}
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-gray-200">{describeEvent(event.type, event.data)}</p>
            <p className="text-[11px] text-gray-500">
              <span className="font-mono">{event.type}</span> · {relativeTime(event.timestamp)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
