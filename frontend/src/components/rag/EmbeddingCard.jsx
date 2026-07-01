import Card from "../ui/Card.jsx";
import Field from "../ui/Field.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../../lib/format.js";

// Compact card summarizing the embedding call behind a retrieval.
export default function EmbeddingCard({ embedding }) {
  if (!embedding) return null;
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-violet-500/10 text-violet-400 ring-1 ring-violet-500/20">
          {/* vector glyph */}
          <span className="text-sm">⋔</span>
        </span>
        <h3 className="text-sm font-medium text-gray-200">Embedding</h3>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Field label="Model" value={embedding.embedding_model} />
        <Field label="Dimensions" value={fmtNumber(embedding.embedding_dimension)} />
        <Field label="Latency" value={fmtLatency(embedding.latency_ms)} />
        <Field label="Cost" value={fmtCost(embedding.cost)} />
        {embedding.input_tokens != null && (
          <Field label="Input Tokens" value={fmtNumber(embedding.input_tokens)} />
        )}
      </div>
    </Card>
  );
}
