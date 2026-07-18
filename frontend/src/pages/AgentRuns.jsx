import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import AgentRunsTable from "../components/agent/AgentRunsTable.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import AreaSelect from "../components/AreaSelect.jsx";
import SystemPromptPanel from "../components/SystemPromptPanel.jsx";
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

const selectClass =
  "rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent";

export default function AgentRuns() {
  const [areas, setAreas] = useState([]);
  const [statuses, setStatuses] = useState([]);
  const [areaIdx, setAreaIdx] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    api
      .getAgentRunFacets()
      .then((f) => {
        setAreas(f.areas || []);
        setStatuses(f.statuses || []);
      })
      .catch(() => {
        setAreas([]);
        setStatuses([]);
      });
  }, []);

  const area = areaIdx === "" ? null : areas[Number(areaIdx)];
  const extraParams = useMemo(
    () => ({
      status: status || undefined,
      project: area?.type === "project" ? area.value : undefined,
      system_prompt: area?.type === "system_prompt" ? area.value : undefined,
    }),
    [status, area]
  );

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
  } = usePaginatedList(api.getAgentRuns, { limit: LIMIT, extraParams });

  const hasFilters = query || status || area;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Agent Runs</h1>
        <p className="mt-1 text-sm text-gray-500">
          Every agent execution captured across your requests, grouped by the
          application driving them.
        </p>
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center">
          <AreaSelect
            areas={areas}
            value={areaIdx}
            onChange={(e) => setAreaIdx(e.target.value)}
            className="sm:min-w-[16rem]"
          />
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Filter by agent, type, status, id…"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className={selectClass}
          >
            <option value="">All statuses</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            aria-label="Sort agent runs"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
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

      <SystemPromptPanel area={area} />

      {loading ? (
        <TableSkeleton columns={9} rows={8} />
      ) : error ? (
        <ErrorState message={`Failed to load agent runs: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={hasFilters ? "⌕" : "◇"}
          title={hasFilters ? "No matching runs" : "No agent runs yet"}
          message={
            hasFilters
              ? "No agent runs match the current filters."
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
