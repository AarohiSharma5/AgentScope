import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import WorkflowsTable from "../components/workflow/WorkflowsTable.jsx";
import StatCard from "../components/StatCard.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../lib/format.js";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "workflow_name", label: "Name (A → Z)" },
  { value: "-updated_at", label: "Recently updated" },
];

function MetricsOverview({ metrics }) {
  if (!metrics) return null;
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <StatCard label="Total Workflows" value={fmtNumber(metrics.total_workflows)} />
      <StatCard label="Total Agents" value={fmtNumber(metrics.total_agents)} />
      <StatCard label="Avg Agents / Workflow" value={metrics.average_agents_per_workflow} />
      <StatCard label="Success Rate" value={`${metrics.success_rate}%`} />
      <StatCard label="Avg Messages" value={metrics.average_messages} />
      <StatCard label="Avg Parallel Branches" value={metrics.average_parallel_branches} />
      <StatCard label="Avg Latency" value={fmtLatency(metrics.average_latency)} />
      <StatCard label="Avg Cost" value={fmtCost(metrics.average_cost)} />
    </div>
  );
}

export default function Workflows() {
  const [workflows, setWorkflows] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getWorkflowMetrics().then(setMetrics).catch(() => setMetrics(null));
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
      .getWorkflows({ page, limit: LIMIT, sort, q: query })
      .then((res) => {
        if (!active) return;
        setWorkflows(res.data);
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
        <h1 className="text-xl font-semibold text-gray-100">Workflows</h1>
        <p className="mt-1 text-sm text-gray-500">
          Multi-agent workflow definitions and their execution history.
        </p>
      </div>

      <MetricsOverview metrics={metrics} />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by name, version or id…"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs uppercase tracking-wider text-gray-500">Sort</label>
          <select
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
        <TableSkeleton columns={5} rows={8} />
      ) : error ? (
        <ErrorState message={`Failed to load workflows: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query ? "⌕" : "◇"}
          title={query ? "No matching workflows" : "No workflows yet"}
          message={
            query
              ? `No workflows match “${query}”. Try a different search.`
              : "Register a workflow with the WorkflowEngine to see it here."
          }
        />
      ) : (
        <>
          <WorkflowsTable workflows={workflows} />
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
            noun="workflow"
          />
        </>
      )}
    </div>
  );
}
