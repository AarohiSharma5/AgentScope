import { useState } from "react";
import Card from "../ui/Card.jsx";
import DiffSegments from "./DiffSegments.jsx";

function StatChip({ label, count, className }) {
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${className}`}>
      {count} {label}
    </span>
  );
}

function VersionHead({ side }) {
  return (
    <div className="mb-2 flex items-center gap-2 text-xs text-gray-500">
      <span className="font-medium text-gray-300">{side.version || "—"}</span>
      <span className="text-gray-600">·</span>
      <span>run #{side.agent_run_id}</span>
      {side.hash && (
        <span className="ml-auto font-mono text-[11px] text-gray-600">
          {side.hash.slice(0, 10)}
        </span>
      )}
    </div>
  );
}

// Side-by-side (and unified) prompt version diff, highlighting added/removed/
// modified text. `diff` is the /api/prompt-diff response.
export default function PromptDiff({ diff }) {
  const [view, setView] = useState("split");
  const { a, b, stats, segments, identical } = diff;

  const toggle = (value, label) => (
    <button
      type="button"
      onClick={() => setView(value)}
      className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
        view === value ? "bg-ink-500 text-gray-100" : "text-gray-400 hover:text-gray-200"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <StatChip label="added" count={stats.added} className="bg-emerald-500/20 text-emerald-300" />
          <StatChip label="removed" count={stats.removed} className="bg-rose-500/20 text-rose-300" />
          <StatChip label="modified" count={stats.modified} className="bg-amber-500/20 text-amber-200" />
        </div>
        {identical && (
          <span className="rounded-md bg-ink-500 px-2 py-0.5 text-xs text-gray-400">
            Prompts are identical
          </span>
        )}
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-ink-500 bg-ink-800 p-0.5">
          {toggle("split", "Split")}
          {toggle("unified", "Unified")}
        </div>
      </div>

      {view === "split" ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="p-4">
            <VersionHead side={a} />
            <DiffSegments segments={segments} side="a" />
          </Card>
          <Card className="p-4">
            <VersionHead side={b} />
            <DiffSegments segments={segments} side="b" />
          </Card>
        </div>
      ) : (
        <Card className="p-4">
          <DiffSegments segments={segments} side="unified" />
        </Card>
      )}
    </div>
  );
}
