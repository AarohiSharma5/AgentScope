import DataTable from "../DataTable.jsx";
import { fmtTime } from "../../lib/format.js";

const COLUMNS = [
  { key: "id", header: "Workflow", primary: true, className: "font-mono text-gray-400", render: (w) => `#${w.id}` },
  {
    key: "workflow_name",
    header: "Name",
    className: "font-medium text-gray-200",
    render: (w) => w.workflow_name || <span className="text-gray-600">—</span>,
  },
  {
    key: "version",
    header: "Version",
    render: (w) =>
      w.version ? (
        <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
          {w.version}
        </span>
      ) : (
        <span className="text-gray-600">—</span>
      ),
  },
  { key: "execution_count", header: "Executions", className: "font-mono text-gray-300" },
  { key: "updated_at", header: "Updated", className: "text-gray-400", render: (w) => fmtTime(w.updated_at) },
];

export default function WorkflowsTable({ workflows }) {
  return (
    <DataTable
      columns={COLUMNS}
      rows={workflows}
      rowLink={(w) => `/workflows/${w.id}`}
      rowLabel={(w) => `Open workflow ${w.id} (${w.workflow_name || "unnamed"})`}
    />
  );
}
