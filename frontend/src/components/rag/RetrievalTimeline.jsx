import { fmtCost, fmtLatency, fmtScore } from "../../lib/format.js";

const TYPE_DOT = {
  embedding: "bg-violet-400 ring-violet-400/30",
  search: "bg-sky-400 ring-sky-400/30",
  document: "bg-indigo-400 ring-indigo-400/30",
};

const TYPE_LABEL = {
  embedding: "Embedding",
  search: "Search",
  document: "Document",
};

// Vertical timeline for a retrieval: embed → search → each document.
export default function RetrievalTimeline({ events = [] }) {
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
            <span className="text-sm font-medium text-gray-200">{event.label || "—"}</span>
            {event.type === "document" && event.selected && (
              <span className="rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent ring-1 ring-accent/30">
                selected
              </span>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-4 font-mono text-xs text-gray-500">
            {event.latency_ms != null && <span>{fmtLatency(event.latency_ms)}</span>}
            {event.num_documents != null && <span>{event.num_documents} docs</span>}
            {event.tokens != null && <span>{event.tokens} tok</span>}
            {event.cost != null && <span>{fmtCost(event.cost)}</span>}
            {event.score != null && <span>score {fmtScore(event.score)}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}
