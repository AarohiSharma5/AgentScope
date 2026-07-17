import StatusBadge from "../StatusBadge.jsx";
import DataTable from "../DataTable.jsx";
import { fmtLatency, fmtScore } from "../../lib/format.js";

// Combined embed + retrieve latency for the row.
function totalLatency(r) {
  const embed = r.embedding_time_ms || 0;
  const retrieve = r.retrieval_time_ms || 0;
  const sum = embed + retrieve;
  return sum > 0 ? sum : null;
}

const COLUMNS = [
  { key: "id", header: "Retrieval", primary: true, className: "font-mono text-gray-400", render: (r) => `#${r.id}` },
  {
    key: "query",
    header: "Query",
    className: "max-w-[220px] truncate text-gray-200",
    render: (r) => r.query || <span className="text-gray-600">—</span>,
  },
  {
    key: "avg_similarity",
    header: "Similarity",
    render: (r) => (
      <div className="flex items-center gap-2">
        <span className="w-12 font-mono text-gray-300">{fmtScore(r.avg_similarity)}</span>
        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-500">
          <div
            className="h-full rounded-full bg-accent"
            style={{ width: `${Math.round((r.avg_similarity || 0) * 100)}%` }}
          />
        </div>
      </div>
    ),
  },
  { key: "num_documents", header: "Documents", className: "font-mono text-gray-300", render: (r) => r.num_documents ?? "—" },
  { key: "selected_count", header: "Chunks Used", className: "font-mono text-gray-300", render: (r) => r.selected_count ?? 0 },
  { key: "latency", header: "Latency", className: "font-mono text-gray-300", render: (r) => fmtLatency(totalLatency(r)) },
  {
    key: "embedding_model",
    header: "Embedding Model",
    render: (r) =>
      r.embedding_model ? (
        <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
          {r.embedding_model}
        </span>
      ) : (
        <span className="text-gray-600">—</span>
      ),
  },
  { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
];

export default function RetrievalsTable({ retrievals }) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={retrievals}
      rowLink={(r) => `/retrievals/${r.id}`}
      rowLabel={(r) => `Open retrieval ${r.id}`}
      minWidth="min-w-[820px]"
    />
  );
}
