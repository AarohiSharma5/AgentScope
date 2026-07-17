import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import EvaluationsTable from "../components/eval/EvaluationsTable.jsx";
import StatCard from "../components/StatCard.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import { usePaginatedList } from "../lib/usePaginatedList.js";
import { fmtCost, fmtLatency, fmtScore } from "../lib/format.js";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "-overall_score", label: "Score (high → low)" },
  { value: "overall_score", label: "Score (low → high)" },
];

function MetricsOverview({ metrics }) {
  if (!metrics) return null;
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard label="Avg Score" value={fmtScore(metrics.average_evaluation_score)} />
      <StatCard label="Avg Cost" value={fmtCost(metrics.average_cost)} />
      <StatCard label="Avg Latency" value={fmtLatency(metrics.average_latency)} />
      <StatCard label="Success Rate" value={pct(metrics.success_rate)} />
      <StatCard label="Correctness" value={fmtScore(metrics.average_correctness)} />
      <StatCard label="Faithfulness" value={fmtScore(metrics.average_faithfulness)} />
      <StatCard label="Groundedness" value={fmtScore(metrics.average_groundedness)} />
      <StatCard label="Tool Accuracy" value={fmtScore(metrics.average_tool_accuracy)} />
    </div>
  );
}

export default function Evaluations() {
  const [metrics, setMetrics] = useState(null);
  const {
    data: evaluations,
    pagination,
    loading,
    error,
    setPage,
    sort,
    setSort,
    search,
    setSearch,
    query,
  } = usePaginatedList(api.getEvaluations, { limit: LIMIT });

  useEffect(() => {
    api.getEvaluationMetrics().then(setMetrics).catch(() => setMetrics(null));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Evaluations</h1>
        <p className="mt-1 text-sm text-gray-500">
          Automatic scoring of conversations across correctness, groundedness and more.
        </p>
      </div>

      <MetricsOverview metrics={metrics} />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput value={search} onChange={setSearch} placeholder="Search by type or model…" />
        <div className="flex items-center gap-2">
          <label className="text-xs uppercase tracking-wider text-gray-500">Sort</label>
          <select
            aria-label="Sort evaluations"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <TableSkeleton columns={7} rows={8} />
      ) : error ? (
        <ErrorState message={`Failed to load evaluations: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query ? "⌕" : "◎"}
          title={query ? "No matching evaluations" : "No evaluations yet"}
          message={
            query
              ? `No evaluations match “${query}”.`
              : "Run an evaluation via POST /api/evaluations or the EvaluationEngine."
          }
        />
      ) : (
        <>
          <EvaluationsTable evaluations={evaluations} />
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
            noun="evaluation"
          />
        </>
      )}
    </div>
  );
}
