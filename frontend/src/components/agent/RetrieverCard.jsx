import Card from "../ui/Card.jsx";
import Field from "../ui/Field.jsx";
import CodeBlock from "../ui/CodeBlock.jsx";
import { fmtLatency } from "../../lib/format.js";

export default function RetrieverCard({ retriever }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-md bg-violet-500/10 px-2 py-0.5 text-xs font-medium text-violet-400 ring-1 ring-violet-500/20">
          {retriever.num_documents != null
            ? `${retriever.num_documents} documents`
            : "retrieval"}
        </span>
        <div className="flex items-center gap-4 font-mono text-xs text-gray-500">
          {retriever.embedding_time_ms != null && (
            <span>embed {fmtLatency(retriever.embedding_time_ms)}</span>
          )}
          {retriever.retrieval_time_ms != null && (
            <span>retrieve {fmtLatency(retriever.retrieval_time_ms)}</span>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-4">
        <Field label="Query" value={retriever.query} />
        <Field label="Documents">
          <CodeBlock value={retriever.retrieved_documents} />
        </Field>
      </div>
    </Card>
  );
}
