import { TOPICS } from "../../lib/liveEvents.js";
import ConnectionPill from "./ConnectionPill.jsx";

// Pause/resume, clear and topic filtering for the live dashboard. Topic chips
// toggle the server-side subscription filter; no selection means "everything".
export default function LiveControls({
  status,
  paused,
  onTogglePause,
  onClear,
  selectedTopics,
  onTopicsChange,
}) {
  const allSelected = selectedTopics.length === 0;

  const toggleTopic = (key) => {
    if (selectedTopics.includes(key)) {
      onTopicsChange(selectedTopics.filter((t) => t !== key));
    } else {
      onTopicsChange([...selectedTopics, key]);
    }
  };

  const btn =
    "rounded-lg border border-ink-500 bg-ink-800 px-3 py-1.5 text-sm text-gray-200 transition-colors hover:bg-ink-600";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <ConnectionPill status={status} />
        <button className={btn} onClick={onTogglePause}>
          {paused ? "▶ Resume" : "⏸ Pause"}
        </button>
        <button className={btn} onClick={onClear}>
          Clear
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <button
          onClick={() => onTopicsChange([])}
          className={`rounded-full px-2.5 py-1 text-xs font-medium transition-colors ${
            allSelected
              ? "bg-accent text-white"
              : "border border-ink-500 bg-ink-800 text-gray-400 hover:text-gray-200"
          }`}
        >
          All
        </button>
        {TOPICS.map((topic) => {
          const active = selectedTopics.includes(topic.key);
          return (
            <button
              key={topic.key}
              onClick={() => toggleTopic(topic.key)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                active
                  ? "border-transparent bg-ink-600 text-gray-100"
                  : "border-ink-500 bg-ink-800 text-gray-500 hover:text-gray-300"
              }`}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: topic.color, opacity: active || allSelected ? 1 : 0.4 }}
              />
              {topic.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
