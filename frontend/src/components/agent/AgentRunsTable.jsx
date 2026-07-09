import { Link, useNavigate } from "react-router-dom";
import StatusBadge from "../StatusBadge.jsx";
import { fmtDuration, fmtLatency, fmtTime } from "../../lib/format.js";
import { INTERACTIVE_ROW_CLASS, interactiveRowProps } from "../../lib/rowInteraction.js";

const HEADERS = [
  "Run ID",
  "Agent",
  "Type",
  "Status",
  "Latency",
  "Started",
  "Duration",
  "Request ID",
];

export default function AgentRunsTable({ runs }) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[720px] text-left text-sm">
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
          {runs.map((run) => (
            <tr
              key={run.id}
              {...interactiveRowProps(
                () => navigate(`/agent-runs/${run.id}`),
                `Open agent run ${run.id} (${run.agent_name})`,
              )}
              className={INTERACTIVE_ROW_CLASS}
            >
              <td className="px-4 py-3 font-mono text-gray-400">#{run.id}</td>
              <td className="px-4 py-3 font-medium text-gray-200">{run.agent_name}</td>
              <td className="px-4 py-3">
                {run.agent_type ? (
                  <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                    {run.agent_type}
                  </span>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={run.status} />
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">
                {fmtLatency(run.latency_ms)}
              </td>
              <td className="px-4 py-3 text-gray-500">{fmtTime(run.start_time)}</td>
              <td className="px-4 py-3 font-mono text-gray-300">
                {fmtDuration(run.start_time, run.end_time)}
              </td>
              <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                <Link
                  to={`/traces/${run.request_id}`}
                  className="font-mono text-accent hover:text-accent-hover"
                >
                  #{run.request_id}
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
