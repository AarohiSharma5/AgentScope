import { memo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import StatusBadge from "./StatusBadge.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtTime } from "../lib/format.js";
import { INTERACTIVE_ROW_CLASS, interactiveRowProps } from "../lib/rowInteraction.js";

// Memoized row so re-renders (e.g. periodic dashboard refreshes) only touch
// rows whose data actually changed, keeping large trace pages responsive.
const TraceRow = memo(function TraceRow({ trace: t, onOpen }) {
  return (
    <tr
      {...interactiveRowProps(() => onOpen(t.id), `Open trace ${t.id} (${t.model_name})`)}
      className={INTERACTIVE_ROW_CLASS}
    >
      <td className="px-4 py-3">
        <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
          {t.model_name}
        </span>
      </td>
      <td className="max-w-xs truncate px-4 py-3 text-gray-400">
        {t.user_prompt || "—"}
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={t.status} />
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">
        {fmtNumber(t.total_tokens)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">
        {fmtLatency(t.latency_ms)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-gray-300">
        {fmtCost(t.estimated_cost)}
      </td>
      <td className="px-4 py-3 text-right text-gray-500">
        {fmtTime(t.timestamp)}
      </td>
    </tr>
  );
});

export default function TracesTable({ traces }) {
  const navigate = useNavigate();
  const openTrace = useCallback((id) => navigate(`/traces/${id}`), [navigate]);

  return (
    <div className="overflow-hidden rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            <th className="px-4 py-3 font-medium">Model</th>
            <th className="px-4 py-3 font-medium">Prompt</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 text-right font-medium">Tokens</th>
            <th className="px-4 py-3 text-right font-medium">Latency</th>
            <th className="px-4 py-3 text-right font-medium">Cost</th>
            <th className="px-4 py-3 text-right font-medium">Time</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {traces.map((t) => (
            <TraceRow key={t.id} trace={t} onOpen={openTrace} />
          ))}
          {traces.length === 0 && (
            <tr>
              <td colSpan={7} className="px-4 py-10 text-center text-gray-500">
                No traces yet. Send an LLM request or run the seed script.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
