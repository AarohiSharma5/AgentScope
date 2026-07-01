import Card from "../ui/Card.jsx";
import Field from "../ui/Field.jsx";
import CodeBlock from "../ui/CodeBlock.jsx";
import StatusBadge from "../StatusBadge.jsx";
import { fmtLatency } from "../../lib/format.js";

export default function StepCard({ step }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="grid h-6 min-w-6 place-items-center rounded-md bg-accent/15 px-1.5 text-xs font-semibold text-accent">
            {step.step_number ?? "?"}
          </span>
          <span className="text-sm font-medium text-gray-200">
            {step.name || "Untitled step"}
          </span>
          {step.step_type && (
            <span className="rounded-md bg-ink-500 px-2 py-0.5 font-mono text-xs text-gray-300">
              {step.step_type}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-gray-500">
            {fmtLatency(step.latency_ms)}
          </span>
          <StatusBadge status={step.status} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field label="Input">
          <CodeBlock value={step.input} />
        </Field>
        <Field label="Output">
          <CodeBlock value={step.output} />
        </Field>
      </div>

      {step.token_usage != null && (
        <div className="mt-4">
          <Field label="Token Usage">
            <CodeBlock value={step.token_usage} />
          </Field>
        </div>
      )}

      {step.metadata != null && (
        <div className="mt-4">
          <Field label="Metadata">
            <CodeBlock value={step.metadata} />
          </Field>
        </div>
      )}
    </Card>
  );
}
