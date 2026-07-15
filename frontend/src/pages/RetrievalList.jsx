import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import RetrievalsTable from "../components/rag/RetrievalsTable.jsx";
import StatCard from "../components/StatCard.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtScore } from "../lib/format.js";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-id", label: "Newest first" },
  { value: "id", label: "Oldest first" },
  { value: "-num_documents", label: "Documents (high → low)" },
  { value: "num_documents", label: "Documents (low → high)" },
  { value: "-retrieval_time_ms", label: "Latency (high → low)" },
  { value: "retrieval_time_ms", label: "Latency (low → high)" },
];

function MetricsOverview({ metrics }) {
  if (!metrics) return null;
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard label="Avg Similarity" value={fmtScore(metrics.average_similarity)} />
      <StatCard label="Avg Docs Retrieved" value={fmtNumber(metrics.average_documents_retrieved)} />
      <StatCard label="Avg Docs Used" value={fmtNumber(metrics.average_documents_used)} />
      <StatCard label="Success Rate" value={`${metrics.success_rate}%`} />
      <StatCard label="Avg Embedding Latency" value={fmtLatency(metrics.average_embedding_latency)} />
      <StatCard label="Avg Retrieval Latency" value={fmtLatency(metrics.average_retrieval_latency)} />
      <StatCard
        label="Avg Prompt Size"
        value={`${fmtNumber(metrics.average_prompt_size)} tok`}
      />
      <StatCard label="Total Embedding Cost" value={fmtCost(metrics.total_embedding_cost)} />
    </div>
  );
}

export default function RetrievalList() {
  const [retrievals, setRetrievals] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-id");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Metrics overview loads once (independent of table paging/search).
  useEffect(() => {
    api.getRagMetrics().then(setMetrics).catch(() => setMetrics(null));
  }, []);

  // Debounce search, resetting to page 1.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .getRetrievals({ page, limit: LIMIT, sort, q: query }, { signal: ctrl.signal })
      .then((res) => {
        setRetrievals(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => {
        if (e.name !== "AbortError" && !ctrl.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [page, sort, query]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">RAG Observatory</h1>
        <p className="mt-1 text-sm text-gray-500">
          Every retrieval, embedding and assembled prompt captured across your agents.
        </p>
      </div>

      <MetricsOverview metrics={metrics} />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by query text or id…"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs uppercase tracking-wider text-gray-500">Sort</label>
          <select
            aria-label="Sort retrievals"
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
        <TableSkeleton columns={8} rows={8} />
      ) : error ? (
        <ErrorState message={`Failed to load retrievals: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query ? "⌕" : "◇"}
          title={query ? "No matching retrievals" : "No retrievals yet"}
          message={
            query
              ? `No retrievals match “${query}”. Try a different search.`
              : "Run a traced retrieval via the RetrievalService to see it appear here."
          }
        />
      ) : (
        <>
          <RetrievalsTable retrievals={retrievals} />
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
            noun="retrieval"
          />
        </>
      )}
    </div>
  );
}
