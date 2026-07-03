import { useMemo } from "react";
import { layoutDag } from "../../lib/dagLayout.js";
import EmptyState from "../ui/EmptyState.jsx";

// Node accent per live status.
const STATUS_COLOR = {
  running: "#38bdf8",
  success: "#34d399",
  failed: "#fb7185",
  cancelled: "#9ca3af",
  timeout: "#f59e0b",
};

function edgePath(e) {
  const midY = (e.y1 + e.y2) / 2;
  return `M ${e.x1} ${e.y1} C ${e.x1} ${midY}, ${e.x2} ${midY}, ${e.x2} ${e.y2}`;
}

// Streaming execution graph built from the live agent map. Parent → child edges
// come from each agent's parentRunId; the layout recomputes automatically as new
// agents arrive or finish. Auto-fits via viewBox so it stays responsive.
export default function LiveExecutionGraph({ agents }) {
  const layout = useMemo(() => {
    const present = new Set(agents.map((a) => String(a.id)));
    const nodes = agents.map((a) => ({
      id: String(a.id),
      label: a.name,
      role: a.type,
      status: a.status,
    }));
    const edges = agents
      .filter((a) => a.parentRunId != null && present.has(String(a.parentRunId)))
      .map((a) => ({ from: String(a.parentRunId), to: String(a.id), kind: "next" }));
    const root = agents.find((a) => a.parentRunId == null);
    return layoutDag(nodes, edges, root ? String(root.id) : null);
  }, [agents]);

  if (!layout.nodes.length) {
    return <EmptyState icon="⌗" message="No active agents to graph yet." />;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-ink-500 bg-ink-800">
      <svg
        className="h-[460px] w-full"
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        preserveAspectRatio="xMidYMin meet"
      >
        {layout.edges.map((e, i) => (
          <path
            key={i}
            d={edgePath(e)}
            fill="none"
            stroke="#6b7280"
            strokeWidth={1.5}
            strokeOpacity={0.8}
          />
        ))}
        {layout.nodes.map((n) => {
          const accent = STATUS_COLOR[n.status] || "#6366f1";
          const running = n.status === "running";
          return (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}>
              <rect
                width={n.w}
                height={n.h}
                rx="10"
                fill="#18181c"
                stroke={accent}
                strokeWidth={running ? 2 : 1.5}
                strokeOpacity={running ? 1 : 0.7}
              >
                {running && (
                  <animate
                    attributeName="stroke-opacity"
                    values="1;0.35;1"
                    dur="1.4s"
                    repeatCount="indefinite"
                  />
                )}
              </rect>
              <rect width="5" height={n.h} rx="2.5" fill={accent} />
              <text x="16" y="21" fill="#e5e7eb" fontSize="13" fontWeight="600">
                {(n.label || n.id).length > 16 ? `${(n.label || n.id).slice(0, 15)}…` : n.label || n.id}
              </text>
              <text x="16" y="38" fill="#9ca3af" fontSize="11" fontFamily="ui-monospace">
                {n.role || n.status}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
