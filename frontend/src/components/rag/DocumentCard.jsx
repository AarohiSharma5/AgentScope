import { useState } from "react";
import Card from "../ui/Card.jsx";
import { fmtScore } from "../../lib/format.js";

const PREVIEW_CHARS = 240;

// A single retrieved document/chunk with a collapsible text preview.
export default function DocumentCard({ document }) {
  const [expanded, setExpanded] = useState(false);
  const text = document.chunk_text || "";
  const isLong = text.length > PREVIEW_CHARS;
  const preview = expanded || !isLong ? text : `${text.slice(0, PREVIEW_CHARS)}…`;

  return (
    <Card className={`p-4 ${document.selected ? "ring-1 ring-accent/40" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-gray-200">
            {document.document_name || document.document_id || `Document #${document.id}`}
          </p>
          <p className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-xs text-gray-500">
            {document.document_source && <span>{document.document_source}</span>}
            {document.chunk_index != null && <span>chunk {document.chunk_index}</span>}
            {document.document_id && <span>id {document.document_id}</span>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-md bg-ink-500 px-2 py-0.5 font-mono text-xs text-gray-300">
            {fmtScore(document.similarity_score)}
          </span>
          {document.selected ? (
            <span className="rounded-full bg-accent/10 px-2 py-0.5 text-xs font-medium text-accent ring-1 ring-accent/30">
              Selected
            </span>
          ) : (
            <span className="rounded-full bg-gray-500/10 px-2 py-0.5 text-xs font-medium text-gray-500 ring-1 ring-gray-500/20">
              Rejected
            </span>
          )}
        </div>
      </div>

      {text ? (
        <>
          <p className="mt-3 whitespace-pre-wrap break-words text-sm text-gray-300">
            {preview}
          </p>
          {isLong && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-2 text-xs text-accent hover:text-accent-hover"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </>
      ) : (
        <p className="mt-3 text-sm text-gray-600">No preview text.</p>
      )}
    </Card>
  );
}
