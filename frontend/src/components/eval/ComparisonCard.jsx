import { useState } from "react";
import Card from "../ui/Card.jsx";
import SideBySide from "./SideBySide.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtTime } from "../../lib/format.js";

// A model comparison record: a compact header (A vs B, winner, deltas) that
// expands to a full side-by-side view built from the stored profiles.
function Delta({ label, value, fmt }) {
  return (
    <span className="text-gray-500">
      {label} <span className="font-mono text-gray-300">{value == null ? "—" : fmt(value)}</span>
    </span>
  );
}

export default function ComparisonCard({ comparison }) {
  const [open, setOpen] = useState(false);
  const meta = comparison.metadata || {};
  const left = meta.baseline || { model: comparison.model_a };
  const right = meta.variant || { model: comparison.model_b };
  const canExpand = Boolean(meta.baseline && meta.variant);

  return (
    <Card className="overflow-hidden">
      <button
        onClick={() => canExpand && setOpen((v) => !v)}
        className={`flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left ${
          canExpand ? "cursor-pointer hover:bg-ink-600" : "cursor-default"
        }`}
      >
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm text-gray-100">{comparison.model_a || "—"}</span>
          <span className="text-xs text-gray-600">vs</span>
          <span className="font-mono text-sm text-gray-100">{comparison.model_b || "—"}</span>
          {comparison.winner && (
            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-400 ring-1 ring-emerald-500/20">
              {comparison.winner} wins
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 text-xs">
          <Delta label="Δcost" value={comparison.cost_difference} fmt={fmtCost} />
          <Delta label="Δlatency" value={comparison.latency_difference} fmt={fmtLatency} />
          <Delta label="Δtokens" value={comparison.token_difference} fmt={fmtNumber} />
          <span className="hidden text-gray-600 sm:inline">{fmtTime(comparison.created_at)}</span>
          {canExpand && <span className="text-gray-500">{open ? "▾" : "▸"}</span>}
        </div>
      </button>

      {open && canExpand && (
        <div className="border-t border-ink-500 p-4">
          {comparison.reason && (
            <p className="mb-3 text-sm text-gray-400">{comparison.reason}</p>
          )}
          <SideBySide left={left} right={right} winner={comparison.winner} />
        </div>
      )}
    </Card>
  );
}
