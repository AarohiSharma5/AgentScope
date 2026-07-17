import { useState } from "react";
import Card from "../ui/Card.jsx";
import ChartFallbackTable from "../charts/ChartFallbackTable.jsx";
import { fmtScore } from "../../lib/format.js";

// Build `bins` histogram buckets across the observed score range.
function histogram(scores, bins = 6) {
  if (scores.length === 0) return [];
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const span = max - min || 1;
  const width = span / bins;
  const buckets = Array.from({ length: bins }, (_, i) => ({
    lo: min + i * width,
    hi: min + (i + 1) * width,
    count: 0,
  }));
  scores.forEach((s) => {
    let idx = Math.floor((s - min) / width);
    if (idx >= bins) idx = bins - 1; // include the max value in the last bucket
    if (idx < 0) idx = 0;
    buckets[idx].count += 1;
  });
  return buckets;
}

function BarView({ documents, maxScore }) {
  return (
    <ul className="space-y-2">
      {documents.map((d, i) => {
        const score = d.score ?? d.similarity_score ?? 0;
        const width = maxScore ? Math.max((score / maxScore) * 100, 2) : 0;
        return (
          <li key={d.id ?? d.document_id ?? i} className="flex items-center gap-3">
            <span
              className="w-28 shrink-0 truncate text-xs text-gray-400"
              title={d.document_name || d.document_id || `doc ${i + 1}`}
            >
              {d.document_name || d.document_id || `doc ${i + 1}`}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-ink-500">
              <div
                className={`h-full rounded ${d.selected ? "bg-accent" : "bg-gray-500"}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right font-mono text-xs text-gray-300">
              {fmtScore(score)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function HistogramView({ scores }) {
  const buckets = histogram(scores);
  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
  const rows = buckets.map((b, i) => ({
    key: i,
    label: `${fmtScore(b.lo)}–${fmtScore(b.hi)}`,
    value: b.count,
  }));
  return (
    <figure className="m-0" role="group" aria-label="Similarity score distribution">
      <div className="flex items-end gap-2" style={{ height: 140 }} aria-hidden="true">
        {buckets.map((b, i) => (
          <div key={i} className="flex flex-1 flex-col items-center justify-end gap-1">
            <span className="text-xs text-gray-300">{b.count || ""}</span>
            <div
              className="w-full rounded-t bg-accent/70"
              style={{ height: `${(b.count / maxCount) * 100}%`, minHeight: b.count ? 4 : 0 }}
            />
            <span className="text-[10px] text-gray-400">{fmtScore(b.lo)}</span>
          </div>
        ))}
      </div>
      <ChartFallbackTable
        caption="Similarity score distribution"
        columns={["Score range", "Count"]}
        rows={rows}
      />
    </figure>
  );
}

export default function SimilarityChart({ documents = [] }) {
  const [view, setView] = useState("bars");
  const scored = documents.filter(
    (d) => (d.score ?? d.similarity_score) != null
  );
  const scores = scored.map((d) => d.score ?? d.similarity_score);
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  const maxScore = scores.length ? Math.max(...scores) : 0;

  const tab = (id, label) =>
    `rounded-md px-2.5 py-1 text-xs transition-colors ${
      view === id ? "bg-ink-500 text-gray-100" : "text-gray-500 hover:text-gray-300"
    }`;

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-gray-200">Similarity</h3>
          <span className="rounded-md bg-emerald-500/10 px-2 py-0.5 font-mono text-xs text-emerald-400 ring-1 ring-emerald-500/20">
            avg {fmtScore(avg)}
          </span>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-ink-500 p-0.5">
          <button className={tab("bars")} onClick={() => setView("bars")}>
            Bars
          </button>
          <button className={tab("histogram")} onClick={() => setView("histogram")}>
            Histogram
          </button>
        </div>
      </div>

      {scored.length === 0 ? (
        <p className="text-sm text-gray-500">No scored documents to chart.</p>
      ) : view === "bars" ? (
        <BarView documents={scored} maxScore={maxScore} />
      ) : (
        <HistogramView scores={scores} />
      )}
    </Card>
  );
}
