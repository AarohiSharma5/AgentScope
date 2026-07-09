import { useNavigate } from "react-router-dom";
import StatusBadge from "../StatusBadge.jsx";
import { fmtLatency, fmtTime } from "../../lib/format.js";
import { INTERACTIVE_ROW_CLASS, interactiveRowProps } from "../../lib/rowInteraction.js";

const HEADERS = ["Conversation", "Workflow", "Agents", "Status", "Latency", "Started", "Finished"];

export default function ConversationsTable({ conversations }) {
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
          {conversations.map((c) => (
            <tr
              key={c.id}
              {...interactiveRowProps(
                () => navigate(`/conversations/${c.id}`),
                `Open conversation ${c.id}`,
              )}
              className={INTERACTIVE_ROW_CLASS}
            >
              <td className="px-4 py-3 font-mono text-gray-400">#{c.id}</td>
              <td className="max-w-[220px] truncate px-4 py-3 text-gray-200" title={c.conversation_name}>
                {c.conversation_name || <span className="text-gray-600">—</span>}
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">{c.agent_count}</td>
              <td className="px-4 py-3">
                <StatusBadge status={c.status} />
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">{fmtLatency(c.latency_ms)}</td>
              <td className="px-4 py-3 text-gray-400">{fmtTime(c.started_at)}</td>
              <td className="px-4 py-3 text-gray-400">{fmtTime(c.finished_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
