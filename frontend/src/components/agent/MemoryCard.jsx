import Card from "../ui/Card.jsx";
import Field from "../ui/Field.jsx";
import CodeBlock from "../ui/CodeBlock.jsx";
import { fmtLatency } from "../../lib/format.js";

export default function MemoryCard({ memory }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-md bg-sky-500/10 px-2 py-0.5 text-xs font-medium text-sky-400 ring-1 ring-sky-500/20">
          {memory.memory_type || "memory"}
        </span>
        <div className="flex items-center gap-3">
          {memory.similarity_score != null && (
            <span className="font-mono text-xs text-gray-500">
              sim {Number(memory.similarity_score).toFixed(2)}
            </span>
          )}
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
              memory.used
                ? "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20"
                : "bg-gray-500/10 text-gray-400 ring-gray-500/20"
            }`}
          >
            {memory.used ? "Used" : "Not used"}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4">
        <Field label="Query" value={memory.query} />
        <Field label="Retrieved Text">
          <CodeBlock value={memory.retrieved_text} />
        </Field>
        {memory.latency_ms != null && (
          <Field label="Latency" value={fmtLatency(memory.latency_ms)} />
        )}
      </div>
    </Card>
  );
}
