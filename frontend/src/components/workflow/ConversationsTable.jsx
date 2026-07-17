import StatusBadge from "../StatusBadge.jsx";
import DataTable from "../DataTable.jsx";
import { fmtLatency, fmtTime } from "../../lib/format.js";

const COLUMNS = [
  { key: "id", header: "Conversation", primary: true, className: "font-mono text-gray-400", render: (c) => `#${c.id}` },
  {
    key: "conversation_name",
    header: "Workflow",
    className: "max-w-[220px] truncate text-gray-200",
    render: (c) => c.conversation_name || <span className="text-gray-600">—</span>,
  },
  { key: "agent_count", header: "Agents", className: "font-mono text-gray-300" },
  { key: "status", header: "Status", render: (c) => <StatusBadge status={c.status} /> },
  { key: "latency_ms", header: "Latency", className: "font-mono text-gray-300", render: (c) => fmtLatency(c.latency_ms) },
  { key: "started_at", header: "Started", className: "text-gray-400", render: (c) => fmtTime(c.started_at) },
  { key: "finished_at", header: "Finished", className: "text-gray-400", render: (c) => fmtTime(c.finished_at) },
];

export default function ConversationsTable({ conversations }) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={conversations}
      rowLink={(c) => `/conversations/${c.id}`}
      rowLabel={(c) => `Open conversation ${c.id}`}
      minWidth="min-w-[820px]"
    />
  );
}
