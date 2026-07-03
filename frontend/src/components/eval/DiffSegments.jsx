// Renders word-level diff segments from the backend (`{ op, a, b }`).
//
// `side="a"` shows the left (baseline) column: equal/removed/modified text,
// skipping additions. `side="b"` shows the right column: equal/added/modified,
// skipping removals. `side="unified"` renders a single inline view.
const SIDE_TONE = {
  a: {
    equal: "text-gray-300",
    removed: "rounded bg-rose-500/20 text-rose-300 line-through",
    modified: "rounded bg-amber-500/20 text-amber-200",
  },
  b: {
    equal: "text-gray-300",
    added: "rounded bg-emerald-500/20 text-emerald-300",
    modified: "rounded bg-amber-500/20 text-amber-200",
  },
};

function SideDiff({ segments, side }) {
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-relaxed text-gray-300">
      {segments.map((seg, i) => {
        if (side === "a" && seg.op === "added") return null;
        if (side === "b" && seg.op === "removed") return null;
        const text = side === "a" ? seg.a : seg.b;
        if (!text) return null;
        const cls = SIDE_TONE[side][seg.op] || "text-gray-300";
        return (
          <span key={i} className={cls}>
            {text}
          </span>
        );
      })}
    </pre>
  );
}

function UnifiedDiff({ segments }) {
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-relaxed text-gray-300">
      {segments.map((seg, i) => {
        if (seg.op === "equal") return <span key={i}>{seg.a}</span>;
        if (seg.op === "added")
          return (
            <span key={i} className="rounded bg-emerald-500/20 text-emerald-300">
              {seg.b}
            </span>
          );
        if (seg.op === "removed")
          return (
            <span key={i} className="rounded bg-rose-500/20 text-rose-300 line-through">
              {seg.a}
            </span>
          );
        // modified: strike the old, then show the new.
        return (
          <span key={i}>
            <span className="rounded bg-rose-500/20 text-rose-300 line-through">{seg.a}</span>
            <span className="rounded bg-emerald-500/20 text-emerald-300">{seg.b}</span>
          </span>
        );
      })}
    </pre>
  );
}

export default function DiffSegments({ segments = [], side = "unified" }) {
  if (side === "unified") return <UnifiedDiff segments={segments} />;
  return <SideDiff segments={segments} side={side} />;
}
