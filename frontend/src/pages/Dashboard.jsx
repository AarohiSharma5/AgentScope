import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import TracesTable from "../components/TracesTable.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import Loading from "../components/ui/Loading.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../lib/format.js";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-timestamp", label: "Newest first" },
  { value: "timestamp", label: "Oldest first" },
];

const selectClass =
  "rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState(null);
  const [models, setModels] = useState([]);

  // Filters
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("-timestamp");
  const [page, setPage] = useState(1);

  // List
  const [traces, setTraces] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Global stats + filter facets load once.
  useEffect(() => {
    api.getStats().then(setStats).catch((e) => setStatsError(e.message));
    api.getTraceFacets().then((f) => setModels(f.models || [])).catch(() => setModels([]));
  }, []);

  // Debounce the free-text search and reset to page 1 on change.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // (Re)load the filtered, paginated list whenever a filter changes.
  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .getTraces(
        { page, limit: LIMIT, sort, q: query, model, status },
        { signal: ctrl.signal }
      )
      .then((res) => {
        setTraces(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => {
        if (e.name !== "AbortError" && !ctrl.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [page, sort, query, model, status]);

  const resetFilter = (setter) => (e) => {
    setter(e.target.value);
    setPage(1);
  };

  const hasFilters = query || model || status;

  return (
    <div className="space-y-8">
      {statsError ? (
        <ErrorState message={`Failed to load stats: ${statsError}. Is the backend running?`} />
      ) : !stats ? (
        <Loading label="Loading dashboard…" />
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <StatCard label="Total Requests" value={fmtNumber(stats.total_requests)} />
          <StatCard label="Avg Latency" value={fmtLatency(stats.avg_latency_ms)} />
          <StatCard label="Avg Tokens" value={fmtNumber(stats.avg_tokens)} />
          <StatCard label="Avg Cost" value={fmtCost(stats.avg_cost)} />
          <StatCard
            label="Success Rate"
            value={`${stats.success_rate}%`}
            sublabel={`${stats.total_requests} traces`}
          />
        </div>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-wider text-gray-500">
            Requests
          </h2>
          <span className="text-xs text-gray-500">{pagination.total} total</span>
        </div>

        {/* Filter bar */}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search prompts & responses…"
          />
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Filter by model"
              value={model}
              onChange={resetFilter(setModel)}
              className={selectClass}
            >
              <option value="">All models</option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by status"
              value={status}
              onChange={resetFilter(setStatus)}
              className={selectClass}
            >
              <option value="">All statuses</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
            </select>
            <select
              aria-label="Sort requests"
              value={sort}
              onChange={resetFilter(setSort)}
              className={selectClass}
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
          <ErrorState message={`Failed to load requests: ${error}. Is the backend running?`} />
        ) : pagination.total === 0 ? (
          <EmptyState
            icon={hasFilters ? "⌕" : "◇"}
            title={hasFilters ? "No matching requests" : "No requests yet"}
            message={
              hasFilters
                ? "No requests match the current filters."
                : "Send an LLM request trace to POST /api/traces (or run the seed script) to populate the dashboard."
            }
          />
        ) : (
          <>
            <TracesTable traces={traces} />
            <Pagination
              page={pagination.page}
              pages={pagination.pages}
              total={pagination.total}
              onChange={setPage}
              noun="request"
            />
          </>
        )}
      </div>
    </div>
  );
}
