import { useMemo, useRef, useState } from "react";
import EmptyState from "../ui/EmptyState.jsx";
import { layoutDag } from "../../lib/dagLayout.js";

// Edge color per transition kind.
const EDGE_COLOR = {
  next: "#6b7280",
  true: "#34d399",
  false: "#fb7185",
  parallel: "#a78bfa",
};

// Node accent (left border) per node type.
const TYPE_COLOR = {
  task: "#6366f1",
  parallel: "#a78bfa",
  condition: "#f59e0b",
  end: "#10b981",
};

const MIN_SCALE = 0.4;
const MAX_SCALE = 2.2;

function edgePath(e) {
  const midY = (e.y1 + e.y2) / 2;
  return `M ${e.x1} ${e.y1} C ${e.x1} ${midY}, ${e.x2} ${midY}, ${e.x2} ${e.y2}`;
}

export default function ExecutionGraph({ nodes = [], edges = [], entry = null }) {
  const layout = useMemo(() => layoutDag(nodes, edges, entry), [nodes, edges, entry]);
  const [view, setView] = useState({ scale: 0.85, tx: 20, ty: 20 });
  const [selected, setSelected] = useState(null);
  const [hovered, setHovered] = useState(null);
  const drag = useRef(null);

  if (!layout.nodes.length) {
    return <EmptyState message="This workflow has no nodes to graph." />;
  }

  const zoomBy = (factor) =>
    setView((v) => ({
      ...v,
      scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.scale * factor)),
    }));

  const reset = () => setView({ scale: 0.85, tx: 20, ty: 20 });

  const onWheel = (e) => {
    e.preventDefault();
    zoomBy(e.deltaY < 0 ? 1.1 : 0.9);
  };

  const onPointerDown = (e) => {
    // Only start panning when the background (not a node) is grabbed.
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
  };
  const onPointerMove = (e) => {
    if (!drag.current) return;
    setView((v) => ({
      ...v,
      tx: drag.current.tx + (e.clientX - drag.current.x),
      ty: drag.current.ty + (e.clientY - drag.current.y),
    }));
  };
  const endDrag = () => {
    drag.current = null;
  };

  const isDimmed = (id) => hovered != null && hovered !== id;
  const edgeActive = (edge) =>
    hovered != null && (edge.from === hovered || edge.to === hovered);

  const btn =
    "grid h-7 w-7 place-items-center rounded-md border border-ink-500 bg-ink-800 text-gray-300 hover:bg-ink-600";

  return (
    <div className="relative overflow-hidden rounded-xl border border-ink-500 bg-ink-800">
      {/* Toolbar */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-1.5">
        <button className={btn} onClick={() => zoomBy(1.2)} title="Zoom in" aria-label="Zoom in">
          +
        </button>
        <button className={btn} onClick={() => zoomBy(0.8)} title="Zoom out" aria-label="Zoom out">
          −
        </button>
        <button
          className="rounded-md border border-ink-500 bg-ink-800 px-2 py-1 text-xs text-gray-300 hover:bg-ink-600"
          onClick={reset}
        >
          Reset
        </button>
      </div>
      <p className="pointer-events-none absolute left-3 top-3 z-10 text-[11px] text-gray-600">
        Scroll to zoom · drag to pan · click a node
      </p>

      <svg
        className="h-[460px] w-full cursor-grab active:cursor-grabbing"
        onWheel={onWheel}
        onMouseDown={onPointerDown}
        onMouseMove={onPointerMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
      >
        <g transform={`translate(${view.tx},${view.ty}) scale(${view.scale})`}>
          {/* Edges */}
          {layout.edges.map((e, i) => (
            <path
              key={i}
              d={edgePath(e)}
              fill="none"
              stroke={EDGE_COLOR[e.kind] || "#6b7280"}
              strokeWidth={edgeActive(e) ? 2.5 : 1.5}
              strokeOpacity={hovered != null && !edgeActive(e) ? 0.25 : 0.9}
            />
          ))}

          {/* Nodes */}
          {layout.nodes.map((n) => {
            const accent = TYPE_COLOR[n.type] || "#6366f1";
            const isSelected = selected?.id === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${n.x},${n.y})`}
                className="cursor-pointer"
                opacity={isDimmed(n.id) ? 0.4 : 1}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelected(n);
                }}
              >
                <rect
                  width={n.w}
                  height={n.h}
                  rx="10"
                  fill="#18181c"
                  stroke={isSelected ? "#6366f1" : "#2a2a31"}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                />
                <rect width="5" height={n.h} rx="2.5" fill={accent} />
                <text x="16" y="21" fill="#e5e7eb" fontSize="13" fontWeight="600">
                  {n.id.length > 16 ? `${n.id.slice(0, 15)}…` : n.id}
                </text>
                <text x="16" y="38" fill="#9ca3af" fontSize="11" fontFamily="ui-monospace">
                  {n.role || n.type}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Selected node detail */}
      {selected && (
        <div className="absolute bottom-3 left-3 z-10 w-60 rounded-lg border border-ink-500 bg-ink-700/95 p-3 text-sm shadow-lg backdrop-blur">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-semibold text-gray-100">{selected.id}</span>
            <button
              className="text-gray-500 hover:text-gray-300"
              onClick={() => setSelected(null)}
              aria-label="Close"
            >
              ✕
            </button>
          </div>
          <dl className="space-y-1 text-xs text-gray-400">
            <div className="flex justify-between">
              <dt>Type</dt>
              <dd className="font-mono text-gray-300">{selected.type}</dd>
            </div>
            {selected.role && (
              <div className="flex justify-between">
                <dt>Role</dt>
                <dd className="font-mono text-gray-300">{selected.role}</dd>
              </div>
            )}
            {selected.retries != null && (
              <div className="flex justify-between">
                <dt>Retries</dt>
                <dd className="font-mono text-gray-300">{selected.retries}</dd>
              </div>
            )}
            {selected.timeout_ms != null && (
              <div className="flex justify-between">
                <dt>Timeout</dt>
                <dd className="font-mono text-gray-300">{selected.timeout_ms}ms</dd>
              </div>
            )}
            {selected.branches && (
              <div className="flex justify-between">
                <dt>Branches</dt>
                <dd className="font-mono text-gray-300">{selected.branches.length}</dd>
              </div>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}
