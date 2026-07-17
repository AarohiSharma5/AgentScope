import StatusBadge from "../StatusBadge.jsx";
import DataTable from "../DataTable.jsx";
import { fmtScore, fmtTime } from "../../lib/format.js";

// Colour the overall score like the metric bars.
function scoreClass(value) {
  if (value == null) return "text-gray-500";
  if (value >= 0.7) return "text-emerald-400";
  if (value >= 0.4) return "text-amber-400";
  return "text-rose-400";
}

const COLUMNS = [
  { key: "id", header: "Evaluation", primary: true, className: "font-mono text-gray-400", render: (e) => `#${e.id}` },
  {
    key: "evaluation_type",
    header: "Type",
    className: "text-gray-300",
    render: (e) => e.evaluation_type || <span className="text-gray-600">—</span>,
  },
  {
    key: "overall_score",
    header: "Score",
    render: (e) => (
      <span className={`font-mono font-semibold ${scoreClass(e.overall_score)}`}>
        {fmtScore(e.overall_score)}
      </span>
    ),
  },
  { key: "status", header: "Status", render: (e) => <StatusBadge status={e.status} /> },
  { key: "metrics", header: "Metrics", className: "font-mono text-gray-300", render: (e) => e.metrics?.length ?? "—" },
  {
    key: "conversation_run_id",
    header: "Conversation",
    className: "font-mono text-gray-400",
    render: (e) => `#${e.conversation_run_id}`,
  },
  { key: "created_at", header: "Created", className: "text-gray-400", render: (e) => fmtTime(e.created_at) },
];

export default function EvaluationsTable({ evaluations }) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={evaluations}
      rowLink={(e) => `/evaluations/${e.id}`}
      rowLabel={(e) => `Open evaluation ${e.id}`}
      minWidth="min-w-[680px]"
    />
  );
}
