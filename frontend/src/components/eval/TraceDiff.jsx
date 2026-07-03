import Card from "../ui/Card.jsx";
import DiffSegments from "./DiffSegments.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../../lib/format.js";

const METRIC_FMT = {
  latency_ms: fmtLatency,
  cost: fmtCost,
  total_tokens: fmtNumber,
};

const METRIC_LABEL = {
  latency_ms: "Latency",
  cost: "Cost",
  total_tokens: "Tokens",
  nodes: "Agents",
  steps: "Steps",
  tools: "Tools",
  memory: "Memory",
  retrievers: "Retrievers",
  documents: "Documents",
};

function DeltaCell({ value, fmt }) {
  if (value == null) return <span className="text-gray-600">—</span>;
  if (value === 0) return <span className="font-mono text-gray-600">0</span>;
  const sign = value > 0 ? "+" : "-";
  return (
    <span className="font-mono text-gray-300">
      {sign}
      {fmt(Math.abs(value))}
    </span>
  );
}

function DiffTable({ title, rows, fmt }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            <th className="px-4 py-3 font-medium">{title}</th>
            <th className="px-4 py-3 font-medium">A</th>
            <th className="px-4 py-3 font-medium">B</th>
            <th className="px-4 py-3 font-medium">Diff</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {rows.map((row) => {
            const f = fmt(row.metric);
            const changed = (row.delta ?? 0) !== 0;
            return (
              <tr key={row.metric} className={changed ? "bg-amber-500/5" : undefined}>
                <td className="px-4 py-3 text-gray-400">{METRIC_LABEL[row.metric] || row.metric}</td>
                <td className="px-4 py-3 font-mono text-gray-200">{f(row.a)}</td>
                <td className="px-4 py-3 font-mono text-gray-200">{f(row.b)}</td>
                <td className="px-4 py-3">
                  <DeltaCell value={row.delta} fmt={f} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function NodeSide({ node }) {
  if (!node) return <p className="text-sm text-gray-600">— not present —</p>;
  return (
    <div className="space-y-1 text-xs text-gray-500">
      <p className="text-sm font-medium text-gray-200">
        {node.name || node.role || `Node #${node.node_id}`}
      </p>
      <p>
        {node.steps} steps · {fmtNumber(node.tokens)} tokens · {fmtCost(node.cost)}
      </p>
    </div>
  );
}

function NodeRow({ node }) {
  return (
    <Card className={`p-4 ${node.changed ? "border-amber-500/30" : ""}`}>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider text-gray-500">
          Node {node.index + 1}
        </span>
        {node.changed && (
          <span className="rounded-md bg-amber-500/20 px-2 py-0.5 text-xs text-amber-200">
            changed
          </span>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <NodeSide node={node.a} />
        <NodeSide node={node.b} />
      </div>
      {node.output_diff && (
        <div className="mt-3 border-t border-ink-600 pt-3">
          <p className="mb-2 text-xs uppercase tracking-wider text-gray-500">Output diff</p>
          <DiffSegments segments={node.output_diff} side="unified" />
        </div>
      )}
    </Card>
  );
}

// Full trace diff: metric/count tables + node-by-node side-by-side.
// `diff` is the /api/trace-diff response.
export default function TraceDiff({ diff }) {
  const metricFmt = (metric) => METRIC_FMT[metric] || fmtNumber;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-2">
        <DiffTable title="Metric" rows={diff.metrics} fmt={metricFmt} />
        <DiffTable title="Counts" rows={diff.counts} fmt={() => fmtNumber} />
      </div>

      <div>
        <p className="mb-3 text-sm font-medium uppercase tracking-wider text-gray-500">
          Nodes ({diff.nodes.length})
        </p>
        <div className="space-y-3">
          {diff.nodes.map((node) => (
            <NodeRow key={node.index} node={node} />
          ))}
        </div>
      </div>
    </div>
  );
}
