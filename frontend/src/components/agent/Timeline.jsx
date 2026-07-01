import StatusBadge from "../StatusBadge.jsx";
import { fmtLatency, fmtTime } from "../../lib/format.js";

// Dot color per event type.
const TYPE_DOT = {
  step: "bg-indigo-400 ring-indigo-400/30",
  tool: "bg-amber-400 ring-amber-400/30",
  memory: "bg-sky-400 ring-sky-400/30",
  retriever: "bg-violet-400 ring-violet-400/30",
};

const TYPE_LABEL = {
  step: "Step",
  tool: "Tool",
  memory: "Memory",
  retriever: "Retriever",
};

export default function Timeline({ events }) {
  return (
    <ol className="relative ml-2 border-l border-ink-500">
      {events.map((event, i) => (
        <li key={i} className="relative pb-6 pl-6 last:pb-0">
          <span
            className={`absolute -left-[7px] top-1 h-3 w-3 rounded-full ring-4 ${
              TYPE_DOT[event.type] || "bg-gray-400 ring-gray-400/30"
            }`}
          />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500">
              {TYPE_LABEL[event.type] || event.type}
            </span>
            <span className="text-sm font-medium text-gray-200">
              {event.label || "—"}
            </span>
            {event.status && <StatusBadge status={event.status} />}
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
