import { useNavigate } from "react-router-dom";
import StatusBadge from "../StatusBadge.jsx";
import { fmtScore, fmtTime } from "../../lib/format.js";
import { INTERACTIVE_ROW_CLASS, interactiveRowProps } from "../../lib/rowInteraction.js";

const HEADERS = ["Evaluation", "Type", "Score", "Status", "Metrics", "Conversation", "Created"];

// Colour the overall score like the metric bars.
function scoreClass(value) {
  if (value == null) return "text-gray-500";
  if (value >= 0.7) return "text-emerald-400";
  if (value >= 0.4) return "text-amber-400";
  return "text-rose-400";
}

export default function EvaluationsTable({ evaluations }) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[680px] text-left text-sm">
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
          {evaluations.map((e) => (
            <tr
              key={e.id}
              {...interactiveRowProps(
                () => navigate(`/evaluations/${e.id}`),
                `Open evaluation ${e.id}`,
              )}
              className={INTERACTIVE_ROW_CLASS}
            >
              <td className="px-4 py-3 font-mono text-gray-400">#{e.id}</td>
              <td className="px-4 py-3 text-gray-300">
                {e.evaluation_type || <span className="text-gray-600">—</span>}
              </td>
              <td className={`px-4 py-3 font-mono font-semibold ${scoreClass(e.overall_score)}`}>
                {fmtScore(e.overall_score)}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={e.status} />
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">{e.metrics?.length ?? "—"}</td>
              <td className="px-4 py-3 font-mono text-gray-400">#{e.conversation_run_id}</td>
              <td className="px-4 py-3 text-gray-400">{fmtTime(e.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
