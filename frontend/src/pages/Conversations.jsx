import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import ConversationsTable from "../components/workflow/ConversationsTable.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "-latency_ms", label: "Latency (high → low)" },
  { value: "latency_ms", label: "Latency (low → high)" },
  { value: "status", label: "Status" },
];

const STATUS_OPTIONS = ["", "success", "failed", "running", "cancelled", "timeout"];

export default function Conversations() {
  const [conversations, setConversations] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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
      .getConversations({ page, limit: LIMIT, sort, q: query, status })
      .then((res) => {
        if (!active) return;
        setConversations(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [page, sort, query, status]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Conversations</h1>
        <p className="mt-1 text-sm text-gray-500">
          Multi-agent conversation runs — the agents, messages and timelines of each workflow run.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by name, status or id…"
        />
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
            className="rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s === "" ? "All statuses" : s[0].toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
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
        <TableSkeleton columns={7} rows={8} />
      ) : error ? (
        <ErrorState message={`Failed to load conversations: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query || status ? "⌕" : "◇"}
          title={query || status ? "No matching conversations" : "No conversations yet"}
          message={
            query || status
              ? "No conversations match your filters. Try adjusting them."
              : "Run a multi-agent workflow or orchestrator to see conversations here."
          }
        />
      ) : (
        <>
          <ConversationsTable conversations={conversations} />
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
            noun="conversation"
          />
        </>
      )}
    </div>
  );
}
