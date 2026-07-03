import Card from "../ui/Card.jsx";
import CodeBlock from "../ui/CodeBlock.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../../lib/format.js";

// Original vs Replay diff. `original` and `replay` are summaries carrying
// { cost, tokens, latency_ms, output }. The diff column is original − replay.
const ROWS = [
  { key: "cost", label: "Cost", fmt: fmtCost },
  { key: "tokens", label: "Tokens", fmt: fmtNumber },
  { key: "latency_ms", label: "Latency", fmt: fmtLatency },
];

function delta(a, b) {
  if (a == null && b == null) return null;
  return (a || 0) - (b || 0);
}

function DeltaCell({ value, fmt }) {
  if (value == null) return <span className="text-gray-600">—</span>;
  // Higher cost/tokens/latency on the replay reads as a regression (rose).
  const tone =
    value === 0 ? "text-gray-400" : value > 0 ? "text-rose-400" : "text-emerald-400";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return (
    <span className={`font-mono ${tone}`}>
      {sign}
      {fmt(Math.abs(value))}
    </span>
  );
}

export default function DiffTable({ original, replay }) {
  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
            <tr>
              <th className="px-4 py-3 font-medium">Metric</th>
              <th className="px-4 py-3 font-medium">Original</th>
              <th className="px-4 py-3 font-medium">Replay</th>
              <th className="px-4 py-3 font-medium">Diff</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-600">
            {ROWS.map((row) => (
              <tr key={row.key}>
                <td className="px-4 py-3 text-gray-400">{row.label}</td>
                <td className="px-4 py-3 font-mono text-gray-200">
                  {row.fmt(original?.[row.key])}
                </td>
                <td className="px-4 py-3 font-mono text-gray-200">
                  {row.fmt(replay?.[row.key])}
                </td>
                <td className="px-4 py-3">
                  <DeltaCell value={delta(original?.[row.key], replay?.[row.key])} fmt={row.fmt} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <p className="mb-1 text-xs uppercase tracking-wider text-gray-500">Original output</p>
          <CodeBlock value={original?.output} />
        </Card>
        <Card className="p-4">
          <p className="mb-1 text-xs uppercase tracking-wider text-gray-500">Replay output</p>
          <CodeBlock value={replay?.output} />
        </Card>
      </div>
    </div>
  );
}
