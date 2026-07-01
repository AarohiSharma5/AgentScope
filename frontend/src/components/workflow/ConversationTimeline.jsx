import EmptyState from "../ui/EmptyState.jsx";
import { fmtLatency, fmtTime } from "../../lib/format.js";

const TYPE_DOT = {
  instruction: "bg-indigo-400 ring-indigo-400/30",
  question: "bg-sky-400 ring-sky-400/30",
  answer: "bg-emerald-400 ring-emerald-400/30",
  observation: "bg-violet-400 ring-violet-400/30",
  critique: "bg-rose-400 ring-rose-400/30",
  tool_result: "bg-amber-400 ring-amber-400/30",
  memory_result: "bg-teal-400 ring-teal-400/30",
};

// Vertical timeline of a conversation's message events.
export default function ConversationTimeline({ events }) {
  if (!events || events.length === 0) {
    return <EmptyState message="No timeline events for this conversation." />;
  }
  return (
    <ol className="relative ml-2 border-l border-ink-500">
      {events.map((event) => (
        <li key={event.id} className="relative pb-6 pl-6 last:pb-0">
          <span
            className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full ring-4 ${
              TYPE_DOT[event.message_type] || "bg-gray-400 ring-gray-400/30"
            }`}
          />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500">
              {event.message_type}
            </span>
            <span className="text-sm font-medium text-gray-200">{event.from}</span>
            <span aria-hidden className="text-gray-600">
              →
            </span>
            <span className="text-sm text-gray-400">{event.to}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-4 text-xs text-gray-500">
            {event.timestamp && <span>{fmtTime(event.timestamp)}</span>}
            {event.latency_ms != null && (
              <span className="font-mono">{fmtLatency(event.latency_ms)}</span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
