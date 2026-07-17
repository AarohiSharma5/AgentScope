import StatusBadge from "./StatusBadge.jsx";
import DataTable from "./DataTable.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtTime } from "../lib/format.js";

const COLUMNS = [
  {
    key: "project",
    header: "Application",
    primary: true,
    render: (t) =>
      t.project ? (
        <span className="rounded-md bg-accent/10 px-2 py-1 text-xs font-medium text-accent">
          {t.project}
        </span>
      ) : (
        <span className="text-xs text-gray-600">untagged</span>
      ),
  },
  {
    key: "model_name",
    header: "Model",
    render: (t) => (
      <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
        {t.model_name}
      </span>
    ),
  },
  {
    key: "user_prompt",
    header: "Prompt",
    className: "max-w-xs truncate text-gray-400",
    render: (t) => t.user_prompt || "—",
  },
  { key: "status", header: "Status", render: (t) => <StatusBadge status={t.status} /> },
  {
    key: "total_tokens",
    header: "Tokens",
    align: "right",
    className: "font-mono text-gray-300",
    render: (t) => fmtNumber(t.total_tokens),
  },
  {
    key: "latency_ms",
    header: "Latency",
    align: "right",
    className: "font-mono text-gray-300",
    render: (t) => fmtLatency(t.latency_ms),
  },
  {
    key: "estimated_cost",
    header: "Cost",
    align: "right",
    className: "font-mono text-gray-300",
    render: (t) => fmtCost(t.estimated_cost),
  },
  {
    key: "timestamp",
    header: "Time",
    align: "right",
    className: "text-gray-500",
    render: (t) => fmtTime(t.timestamp),
  },
];

export default function TracesTable({ traces }) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={traces}
      rowLink={(t) => `/traces/${t.id}`}
      rowLabel={(t) => `Open trace ${t.id} (${t.model_name})`}
      minWidth="min-w-[860px]"
      emptyMessage="No traces yet. Send an LLM request or run the seed script."
    />
  );
}
