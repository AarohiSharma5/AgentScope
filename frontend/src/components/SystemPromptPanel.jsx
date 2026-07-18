// The system prompt behind the selected application — the artifact that defines
// the area — shown so its owner can see exactly what is driving it. Renders
// nothing when no area is selected. Shared by Requests and Agent Runs.
export default function SystemPromptPanel({ area }) {
  if (!area) return null;
  return (
    <div className="rounded-xl border border-ink-500 bg-ink-800/60 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-gray-500">
          System prompt ·{" "}
          <span className="text-accent">
            {area.type === "project" ? area.value : "untagged area"}
          </span>
        </span>
        {area.system_prompt_variants > 1 && (
          <span className="rounded-md bg-amber-500/10 px-2 py-0.5 text-xs text-amber-400">
            {area.system_prompt_variants} prompt variants in use
          </span>
        )}
      </div>
      {area.system_prompt ? (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-gray-300">
          {area.system_prompt}
        </pre>
      ) : (
        <p className="text-xs text-gray-600">
          No system prompt recorded for this application.
        </p>
      )}
    </div>
  );
}
