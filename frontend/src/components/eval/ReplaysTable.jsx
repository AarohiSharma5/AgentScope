import { useNavigate } from "react-router-dom";
import StatusBadge from "../StatusBadge.jsx";
import { fmtCost, fmtLatency, fmtTime } from "../../lib/format.js";
import { INTERACTIVE_ROW_CLASS, interactiveRowProps } from "../../lib/rowInteraction.js";

const HEADERS = ["Replay", "Model", "Status", "Latency", "Cost", "Original", "Created", ""];

export default function ReplaysTable({ replays, onReplayAgain, busyId }) {
  const navigate = useNavigate();

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            {HEADERS.map((h, i) => (
              <th key={i} className="px-4 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {replays.map((r) => (
            <tr
              key={r.id}
              {...interactiveRowProps(() => navigate(`/replays/${r.id}`), `Open replay ${r.id}`)}
              className={INTERACTIVE_ROW_CLASS}
            >
              <td className="px-4 py-3 font-mono text-gray-400">#{r.id}</td>
              <td className="px-4 py-3 font-medium text-gray-200">
                {r.replayed_model || <span className="text-gray-600">—</span>}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={r.status} />
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">{fmtLatency(r.latency_ms)}</td>
              <td className="px-4 py-3 font-mono text-gray-300">{fmtCost(r.cost)}</td>
              <td className="px-4 py-3 font-mono text-gray-400">
                #{r.original_conversation_run_id}
              </td>
              <td className="px-4 py-3 text-gray-400">{fmtTime(r.created_at)}</td>
              <td className="px-4 py-3 text-right">
                {onReplayAgain && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onReplayAgain(r);
                    }}
                    disabled={busyId === r.id}
                    className="rounded-md border border-ink-500 px-2.5 py-1 text-xs text-gray-300 transition-colors enabled:hover:bg-ink-500 disabled:opacity-40"
                  >
                    {busyId === r.id ? "Replaying…" : "Replay again"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
