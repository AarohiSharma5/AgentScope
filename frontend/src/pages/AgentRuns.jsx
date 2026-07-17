import { api } from "../api/client.js";
import AgentRunsTable from "../components/agent/AgentRunsTable.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import { usePaginatedList } from "../lib/usePaginatedList.js";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "-latency_ms", label: "Latency (high → low)" },
  { value: "latency_ms", label: "Latency (low → high)" },
  { value: "agent_name", label: "Agent (A → Z)" },
  { value: "status", label: "Status" },
];

export default function AgentRuns() {
  const {
    data: runs,
    pagination,
    loading,
    error,
    setPage,
    sort,
    setSort,
    search,
    setSearch,
    query,
  } = usePaginatedList(api.getAgentRuns, { limit: LIMIT });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Agent Runs</h1>
        <p className="mt-1 text-sm text-gray-500">
          Every agent execution captured across your requests.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Filter by agent, type, status, id…"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs uppercase tracking-wider text-gray-500">
            Sort
          </label>
          <select
            aria-label="Sort agent runs"
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
        <TableSkeleton columns={8} rows={8} />
      ) : error ? (
        <ErrorState message={`Failed to load agent runs: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query ? "⌕" : "◇"}
          title={query ? "No matching runs" : "No agent runs yet"}
          message={
            query
              ? `No agent runs match “${query}”. Try a different search.`
              : "Instrument your agents with the TraceRecorder SDK (or hit POST /api/chat) to see runs appear here."
          }
        />
      ) : (
        <>
          <AgentRunsTable runs={runs} />
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
          />
        </>
      )}
    </div>
  );
}
