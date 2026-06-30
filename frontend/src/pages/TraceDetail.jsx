import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import StatusBadge from "../components/StatusBadge.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtTime } from "../lib/format.js";

function Field({ label, children }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <div className="mt-1 text-sm text-gray-200">{children}</div>
    </div>
  );
}

function CodeBlock({ value }) {
  if (value == null) return <span className="text-gray-600">—</span>;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="mt-1 overflow-x-auto rounded-lg border border-ink-500 bg-ink-800 p-3 font-mono text-xs text-gray-300">
      {text}
    </pre>
  );
}

export default function TraceDetail() {
  const { id } = useParams();
  const [trace, setTrace] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setTrace(null);
    setError(null);
    api
      .getTrace(id)
      .then(setTrace)
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="text-rose-400">Failed to load trace: {error}</p>;
  if (!trace) return <p className="text-gray-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <Link to="/" className="text-sm text-accent hover:text-accent-hover">
        ← Back to dashboard
      </Link>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-100">Trace #{trace.id}</h1>
          <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
            {trace.model_name}
          </span>
        </div>
        <StatusBadge status={trace.status} />
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-4 rounded-xl border border-ink-500 bg-ink-700 p-5 md:grid-cols-4">
        <Field label="Input Tokens">{fmtNumber(trace.input_tokens)}</Field>
        <Field label="Output Tokens">{fmtNumber(trace.output_tokens)}</Field>
        <Field label="Total Tokens">{fmtNumber(trace.total_tokens)}</Field>
        <Field label="Estimated Cost">{fmtCost(trace.estimated_cost)}</Field>
        <Field label="Latency">{fmtLatency(trace.latency_ms)}</Field>
        <Field label="Timestamp">{fmtTime(trace.timestamp)}</Field>
      </div>

      {/* Prompts & response */}
      <div className="space-y-5 rounded-xl border border-ink-500 bg-ink-700 p-5">
        <Field label="System Prompt">
          <CodeBlock value={trace.system_prompt} />
        </Field>
        <Field label="User Prompt">
          <CodeBlock value={trace.user_prompt} />
        </Field>
        <Field label="Final Response">
          <CodeBlock value={trace.final_response} />
        </Field>
        {trace.error_message && (
          <Field label="Error">
            <CodeBlock value={trace.error_message} />
          </Field>
        )}
      </div>

      {/* Optional context */}
      <div className="space-y-5 rounded-xl border border-ink-500 bg-ink-700 p-5">
        <Field label="Retrieved Documents">
          <CodeBlock value={trace.retrieved_documents} />
        </Field>
        <Field label="Tool Calls">
          <CodeBlock value={trace.tool_calls} />
        </Field>
      </div>
    </div>
  );
}
