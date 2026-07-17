import StatusBadge from "../StatusBadge.jsx";
import DataTable from "../DataTable.jsx";
import { fmtCost, fmtLatency, fmtTime } from "../../lib/format.js";

export default function ReplaysTable({ replays, onReplayAgain, busyId }) {
  const columns = [
    { key: "id", header: "Replay", primary: true, className: "font-mono text-gray-400", render: (r) => `#${r.id}` },
    {
      key: "replayed_model",
      header: "Model",
      className: "font-medium text-gray-200",
      render: (r) => r.replayed_model || <span className="text-gray-600">—</span>,
    },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "latency_ms", header: "Latency", className: "font-mono text-gray-300", render: (r) => fmtLatency(r.latency_ms) },
    { key: "cost", header: "Cost", className: "font-mono text-gray-300", render: (r) => fmtCost(r.cost) },
    {
      key: "original_conversation_run_id",
      header: "Original",
      className: "font-mono text-gray-400",
      render: (r) => `#${r.original_conversation_run_id}`,
    },
    { key: "created_at", header: "Created", className: "text-gray-400", render: (r) => fmtTime(r.created_at) },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) =>
        onReplayAgain ? (
          <button
            onClick={() => onReplayAgain(r)}
            disabled={busyId === r.id}
            className="rounded-md border border-ink-500 px-2.5 py-1 text-xs text-gray-300 transition-colors enabled:hover:bg-ink-500 disabled:opacity-40"
          >
            {busyId === r.id ? "Replaying…" : "Replay again"}
          </button>
        ) : null,
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={replays}
      rowLink={(r) => `/replays/${r.id}`}
      rowLabel={(r) => `Open replay ${r.id}`}
      minWidth="min-w-[720px]"
    />
  );
}
