import { useMemo, useState } from "react";
import PromptBlock from "./PromptBlock.jsx";

// Section definitions in the order the final prompt is assembled.
const SECTIONS = [
  { key: "system", label: "System Prompt", field: "system_prompt", tok: "system" },
  { key: "conversation", label: "Conversation", field: "conversation", tok: "conversation" },
  { key: "retrieved", label: "Retrieved Context", field: "retrieved_context", tok: "retrieval" },
  { key: "memory", label: "Memory Context", field: "memory_context", tok: "memory" },
  { key: "user", label: "User Prompt", field: "user_prompt", tok: "user" },
];

const ALL_KEYS = [...SECTIONS.map((s) => s.key), "final"];

// Reconstruct a prompt from its final text, or by concatenating sections.
function fullPromptText(prompt) {
  if (prompt.final_prompt) return prompt.final_prompt;
  return SECTIONS.map((s) => prompt[s.field])
    .filter(Boolean)
    .join("\n\n");
}

export default function PromptSections({ prompt }) {
  const tokens = prompt.tokens || {};
  const [openMap, setOpenMap] = useState(() =>
    Object.fromEntries(ALL_KEYS.map((k) => [k, true]))
  );
  const [copiedAll, setCopiedAll] = useState(false);

  const setAll = (value) =>
    setOpenMap(Object.fromEntries(ALL_KEYS.map((k) => [k, value])));
  const toggle = (key) => setOpenMap((m) => ({ ...m, [key]: !m[key] }));

  const fullText = useMemo(() => fullPromptText(prompt), [prompt]);

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(fullText);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  const toolBtn =
    "rounded-md border border-ink-500 px-2.5 py-1 text-xs text-gray-400 transition-colors hover:bg-ink-500 hover:text-gray-200";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button className={toolBtn} onClick={() => setAll(true)}>
          Expand all
        </button>
        <button className={toolBtn} onClick={() => setAll(false)}>
          Collapse all
        </button>
        <button
          className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-hover"
          onClick={copyAll}
        >
          {copiedAll ? "Copied prompt" : "Copy prompt"}
        </button>
      </div>

      {SECTIONS.map((s) => (
        <PromptBlock
          key={s.key}
          label={s.label}
          text={prompt[s.field]}
          tokens={tokens[s.tok]}
          open={openMap[s.key]}
          onToggle={() => toggle(s.key)}
        />
      ))}

      <PromptBlock
        label="Final Prompt"
        text={prompt.final_prompt}
        tokens={tokens.total}
        open={openMap.final}
        onToggle={() => toggle("final")}
        accent
      />
    </div>
  );
}
