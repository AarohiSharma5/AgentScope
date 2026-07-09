import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import EvaluationsTable from "../components/eval/EvaluationsTable.jsx";
import StatCard from "../components/StatCard.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
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
  const [evaluations, setEvaluations] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getEvaluationMetrics().then(setMetrics).catch(() => setMetrics(null));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api
      .getEvaluations({ page, limit: LIMIT, sort, q: query })
      .then((res) => {
        if (!active) return;
        setEvaluations(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [page, sort, query]);

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
            onChange={(e) => {
              setPage(1);
              setSort(e.target.value);
            }}
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
