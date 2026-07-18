import { Link } from "react-router-dom";
import StatusBadge from "../StatusBadge.jsx";
import DataTable from "../DataTable.jsx";
import { fmtDuration, fmtLatency, fmtTime } from "../../lib/format.js";

const COLUMNS = [
  {
    key: "id",
    header: "Run ID",
    primary: true,
    className: "font-mono text-gray-400",
    render: (r) => `#${r.id}`,
  },
  { key: "agent_name", header: "Agent", className: "font-medium text-gray-200" },
  {
    key: "project",
    header: "Application",
    render: (r) =>
      r.project ? (
        <span className="rounded-md bg-accent/10 px-2 py-1 text-xs font-medium text-accent">
          {r.project}
        </span>
      ) : (
        <span className="text-xs text-gray-600">untagged</span>
      ),
  },
  {
    key: "agent_type",
    header: "Type",
    render: (r) =>
      r.agent_type ? (
        <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
          {r.agent_type}
        </span>
      ) : (
        <span className="text-gray-600">—</span>
      ),
  },
  { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
  {
    key: "latency_ms",
    header: "Latency",
    className: "font-mono text-gray-300",
    render: (r) => fmtLatency(r.latency_ms),
  },
  { key: "start_time", header: "Started", className: "text-gray-500", render: (r) => fmtTime(r.start_time) },
  {
    key: "duration",
    header: "Duration",
    className: "font-mono text-gray-300",
    render: (r) => fmtDuration(r.start_time, r.end_time),
  },
  {
    key: "request_id",
    header: "Request ID",
    render: (r) => (
      <Link
        to={`/traces/${r.request_id}`}
        className="font-mono text-accent hover:text-accent-hover"
      >
        #{r.request_id}
      </Link>
    ),
  },
];

export default function AgentRunsTable({ runs }) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={runs}
      rowLink={(r) => `/agent-runs/${r.id}`}
      rowLabel={(r) => `Open agent run ${r.id} (${r.agent_name})`}
      minWidth="min-w-[860px]"
    />
  );
}
