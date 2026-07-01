import { useNavigate } from "react-router-dom";
import { fmtTime } from "../../lib/format.js";

const HEADERS = ["Workflow", "Name", "Version", "Executions", "Updated"];

export default function WorkflowsTable({ workflows }) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[640px] text-left text-sm">
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
          {workflows.map((w) => (
            <tr
              key={w.id}
              onClick={() => navigate(`/workflows/${w.id}`)}
              className="cursor-pointer transition-colors hover:bg-ink-600"
            >
              <td className="px-4 py-3 font-mono text-gray-400">#{w.id}</td>
              <td className="px-4 py-3 font-medium text-gray-200">
                {w.workflow_name || <span className="text-gray-600">—</span>}
              </td>
              <td className="px-4 py-3">
                {w.version ? (
                  <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                    {w.version}
                  </span>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">{w.execution_count}</td>
              <td className="px-4 py-3 text-gray-400">{fmtTime(w.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
