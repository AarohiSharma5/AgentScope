import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import ReplaysTable from "../components/eval/ReplaysTable.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import TableSkeleton from "../components/ui/TableSkeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";

const LIMIT = 20;

const SORT_OPTIONS = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "-cost", label: "Cost (high → low)" },
  { value: "cost", label: "Cost (low → high)" },
  { value: "-latency_ms", label: "Latency (high → low)" },
  { value: "latency_ms", label: "Latency (low → high)" },
];

export default function Replays() {
  const [replays, setReplays] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-created_at");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

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
      .getReplays({ page, limit: LIMIT, sort, q: query }, { signal: ctrl.signal })
      .then((res) => {
        setReplays(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => {
        if (e.name !== "AbortError" && !ctrl.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [page, sort, query, reloadKey]);

  async function replayAgain(replay) {
    setBusyId(replay.id);
    setNotice(null);
    try {
      const created = await api.createReplay({
        conversation_run_id: replay.original_conversation_run_id,
        model: replay.replayed_model,
        temperature: replay.temperature,
        top_p: replay.top_p,
      });
      setNotice(`Replay #${created.id} created (${created.status}).`);
      setReloadKey((k) => k + 1);
    } catch (e) {
      setNotice(`Failed to replay: ${e.message}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Replays</h1>
        <p className="mt-1 text-sm text-gray-500">
          Re-runs of traced conversations under new models and parameters.
        </p>
      </div>

      {notice && (
        <div className="rounded-lg border border-ink-500 bg-ink-700 px-4 py-2 text-sm text-gray-300">
          {notice}
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <SearchInput value={search} onChange={setSearch} placeholder="Search by model…" />
        <div className="flex items-center gap-2">
          <label className="text-xs uppercase tracking-wider text-gray-500">Sort</label>
          <select
            aria-label="Sort replays"
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
        <ErrorState message={`Failed to load replays: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query ? "⌕" : "↺"}
          title={query ? "No matching replays" : "No replays yet"}
          message={
            query
              ? `No replays match “${query}”.`
              : "Create a replay via POST /api/replays or the ReplayEngine to see it here."
          }
        />
      ) : (
        <>
          <ReplaysTable replays={replays} onReplayAgain={replayAgain} busyId={busyId} />
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
            noun="replay"
          />
        </>
      )}
    </div>
  );
}
