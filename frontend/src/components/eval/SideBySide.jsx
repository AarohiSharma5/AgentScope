import Card from "../ui/Card.jsx";
import CodeBlock from "../ui/CodeBlock.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtScore } from "../../lib/format.js";

// Side-by-side comparison of two model profiles. Each profile is expected to
// carry: model, output, latency_ms, total_tokens, cost, evaluation_score,
// tool_calls.success_rate, memory_usage.used_rate, retriever.precision.
const ROWS = [
  { key: "latency_ms", label: "Latency", fmt: fmtLatency, lowerBetter: true },
  { key: "total_tokens", label: "Tokens", fmt: fmtNumber, lowerBetter: true },
  { key: "cost", label: "Cost", fmt: fmtCost, lowerBetter: true },
  { key: "evaluation_score", label: "Evaluation score", fmt: fmtScore, lowerBetter: false },
  {
    key: "tool_success",
    label: "Tool success",
    fmt: fmtScore,
    lowerBetter: false,
    get: (p) => p?.tool_calls?.success_rate,
  },
  {
    key: "memory_usage",
    label: "Memory usage",
    fmt: fmtScore,
    lowerBetter: false,
    get: (p) => p?.memory_usage?.used_rate,
  },
  {
    key: "retriever",
    label: "Retriever precision",
    fmt: fmtScore,
    lowerBetter: false,
    get: (p) => p?.retriever?.precision,
  },
];

function pickBetter(a, b, lowerBetter) {
  if (a == null && b == null) return null;
  if (a == null) return "b";
  if (b == null) return "a";
  if (a === b) return null;
  const aWins = lowerBetter ? a < b : a > b;
  return aWins ? "a" : "b";
}

function Header({ profile, isWinner }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="truncate font-mono text-sm font-semibold text-gray-100" title={profile?.model}>
        {profile?.model || "—"}
      </span>
      {isWinner && (
        <span className="shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400 ring-1 ring-emerald-500/20">
          Winner
        </span>
      )}
    </div>
  );
}

export default function SideBySide({ left, right, winner }) {
  const value = (row, p) => (row.get ? row.get(p) : p?.[row.key]);

  return (
    <Card className="overflow-hidden">
      <div className="grid grid-cols-2 gap-px bg-ink-500">
        <div className="bg-ink-700 p-4">
          <Header profile={left} isWinner={winner && winner === left?.model} />
        </div>
        <div className="bg-ink-700 p-4">
          <Header profile={right} isWinner={winner && winner === right?.model} />
        </div>

        <div className="bg-ink-700 p-4">
          <p className="mb-1 text-xs uppercase tracking-wider text-gray-500">Output</p>
          <CodeBlock value={left?.output} />
        </div>
        <div className="bg-ink-700 p-4">
          <p className="mb-1 text-xs uppercase tracking-wider text-gray-500">Output</p>
          <CodeBlock value={right?.output} />
        </div>
      </div>

      <table className="w-full text-left text-sm">
        <tbody className="divide-y divide-ink-600">
          {ROWS.map((row) => {
            const a = value(row, left);
            const b = value(row, right);
            const better = pickBetter(a, b, row.lowerBetter);
            const cell = (side, v) =>
              `px-4 py-2.5 font-mono ${
                better === side ? "text-emerald-400" : "text-gray-300"
              }`;
            return (
              <tr key={row.key}>
                <td className={cell("a", a)}>{row.fmt(a)}</td>
                <td className="w-px whitespace-nowrap bg-ink-800 px-3 py-2.5 text-center text-[10px] uppercase tracking-wider text-gray-500">
                  {row.label}
                </td>
                <td className={`${cell("b", b)} text-right`}>{row.fmt(b)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
