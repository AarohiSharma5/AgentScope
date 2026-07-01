import Card from "../ui/Card.jsx";
import Field from "../ui/Field.jsx";
import CodeBlock from "../ui/CodeBlock.jsx";
import StatusBadge from "../StatusBadge.jsx";
import { fmtLatency } from "../../lib/format.js";

export default function ToolCard({ tool }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-sm font-medium text-gray-200">
          {tool.tool_name}
        </span>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-gray-500">
            {fmtLatency(tool.latency_ms)}
          </span>
          <StatusBadge status={tool.status} />
        </div>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field label="Arguments">
          <CodeBlock value={tool.arguments} />
        </Field>
        <Field label="Result">
          <CodeBlock value={tool.result} />
        </Field>
      </div>

      {tool.error_message && (
        <div className="mt-4">
          <Field label="Error">
            <CodeBlock value={tool.error_message} />
          </Field>
        </div>
      )}
    </Card>
  );
}
