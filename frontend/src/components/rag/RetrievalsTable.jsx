import { useNavigate } from "react-router-dom";
import StatusBadge from "../StatusBadge.jsx";
import { fmtLatency, fmtScore } from "../../lib/format.js";
import { INTERACTIVE_ROW_CLASS, interactiveRowProps } from "../../lib/rowInteraction.js";

const HEADERS = [
  "Retrieval",
  "Query",
  "Similarity",
  "Documents",
  "Chunks Used",
  "Latency",
  "Embedding Model",
  "Status",
];

// Combined embed + retrieve latency for the row.
function totalLatency(r) {
  const embed = r.embedding_time_ms || 0;
  const retrieve = r.retrieval_time_ms || 0;
  const sum = embed + retrieve;
  return sum > 0 ? sum : null;
}

export default function RetrievalsTable({ retrievals }) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            {HEADERS.map((h) => (
              <th key={h} className="px-4 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {retrievals.map((r) => (
            <tr
              key={r.id}
              {...interactiveRowProps(
                () => navigate(`/retrievals/${r.id}`),
                `Open retrieval ${r.id}`,
              )}
              className={INTERACTIVE_ROW_CLASS}
            >
              <td className="px-4 py-3 font-mono text-gray-400">#{r.id}</td>
              <td className="max-w-[220px] truncate px-4 py-3 text-gray-200" title={r.query}>
                {r.query || <span className="text-gray-600">—</span>}
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="w-12 font-mono text-gray-300">
                    {fmtScore(r.avg_similarity)}
                  </span>
                  <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-500">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{
                        width: `${Math.round((r.avg_similarity || 0) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">
                {r.num_documents ?? "—"}
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">
                {r.selected_count ?? 0}
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">
                {fmtLatency(totalLatency(r))}
              </td>
              <td className="px-4 py-3">
                {r.embedding_model ? (
                  <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                    {r.embedding_model}
                  </span>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={r.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
