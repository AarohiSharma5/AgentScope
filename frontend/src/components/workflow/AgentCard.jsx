import StatusBadge from "../StatusBadge.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../../lib/format.js";

// A single agent's card: role, status and its run aggregates plus lineage.
export default function AgentCard({ node, selected = false, onSelect }) {
  const children = node.children || [];
  return (
    <div
      onClick={onSelect ? () => onSelect(node) : undefined}
      className={`rounded-xl border bg-ink-700 p-4 transition-colors ${
        selected ? "border-accent ring-1 ring-accent/40" : "border-ink-500"
      } ${onSelect ? "cursor-pointer hover:border-accent/50" : ""}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-gray-100">{node.name || `Node #${node.id}`}</p>
          {node.role && (
            <span className="mt-1 inline-block rounded-md bg-ink-500 px-2 py-0.5 font-mono text-xs text-gray-300">
              {node.role}
            </span>
          )}
        </div>
        <StatusBadge status={node.status} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-500">Latency</p>
          <p className="font-mono text-gray-200">{fmtLatency(node.latency_ms)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-500">Tokens</p>
          <p className="font-mono text-gray-200">{fmtNumber(node.total_tokens)}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-gray-500">Cost</p>
          <p className="font-mono text-gray-200">{fmtCost(node.cost)}</p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        <span>
          Parent:{" "}
          {node.parent_node_id ? (
            <span className="font-mono text-gray-400">#{node.parent_node_id}</span>
          ) : (
            <span className="text-gray-600">root</span>
          )}
        </span>
        <span>
          Children:{" "}
          <span className="font-mono text-gray-400">{children.length}</span>
        </span>
        {node.parallel_group && (
          <span className="rounded bg-violet-500/10 px-1.5 py-0.5 font-mono text-violet-300">
            ∥ {node.parallel_group}
          </span>
        )}
      </div>
    </div>
  );
}
