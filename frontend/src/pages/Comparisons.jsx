import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import ComparisonCard from "../components/eval/ComparisonCard.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import Card from "../components/ui/Card.jsx";
import Section from "../components/ui/Section.jsx";
import Loading from "../components/ui/Loading.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";

const LIMIT = 20;

function NewComparisonForm({ onCreated }) {
  const [conversationId, setConversationId] = useState("");
  const [models, setModels] = useState("gpt-4o, gpt-4o-mini, claude-3-5-sonnet");
  const [evaluate, setEvaluate] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    const id = Number(conversationId);
    const modelList = models.split(",").map((m) => m.trim()).filter(Boolean);
    if (!Number.isInteger(id) || id <= 0) {
      setError("Enter a valid conversation id.");
      return;
    }
    if (modelList.length === 0) {
      setError("Enter at least one model.");
      return;
    }
    setBusy(true);
    try {
      await api.createComparison({
        conversation_run_id: id,
        models: modelList,
        evaluate,
      });
      onCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const input =
    "rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 placeholder-gray-600 outline-none focus:border-accent";

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="flex flex-col gap-3 md:flex-row md:items-end">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wider text-gray-500">Conversation ID</span>
          <input
            type="number"
            value={conversationId}
            onChange={(e) => setConversationId(e.target.value)}
            placeholder="e.g. 1"
            className={`${input} w-full md:w-36`}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs uppercase tracking-wider text-gray-500">Models (comma-separated)</span>
          <input
            type="text"
            value={models}
            onChange={(e) => setModels(e.target.value)}
            className={`${input} w-full`}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-400">
          <input
            type="checkbox"
            checked={evaluate}
            onChange={(e) => setEvaluate(e.target.checked)}
            className="h-4 w-4 rounded border-ink-500 bg-ink-800"
          />
          Evaluate
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          {busy ? "Comparing…" : "Compare models"}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-rose-400">{error}</p>}
    </Card>
  );
}

export default function Comparisons() {
  const [comparisons, setComparisons] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
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
      .getComparisons({ page, limit: LIMIT, q: query }, { signal: ctrl.signal })
      .then((res) => {
        setComparisons(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => {
        if (e.name !== "AbortError" && !ctrl.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
  }, [page, query, reloadKey]);

  const refresh = () => {
    setPage(1);
    setReloadKey((k) => k + 1);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Model Comparisons</h1>
        <p className="mt-1 text-sm text-gray-500">
          Run a conversation against multiple models and compare them side by side.
        </p>
      </div>

      <Section title="Run a comparison">
        <NewComparisonForm onCreated={refresh} />
      </Section>

      <div className="flex items-center justify-end">
        <SearchInput value={search} onChange={setSearch} placeholder="Search by model or winner…" />
      </div>

      {loading ? (
        <Loading label="Loading comparisons…" />
      ) : error ? (
        <ErrorState message={`Failed to load comparisons: ${error}. Is the backend running?`} />
      ) : pagination.total === 0 ? (
        <EmptyState
          icon={query ? "⌕" : "⇄"}
          title={query ? "No matching comparisons" : "No comparisons yet"}
          message={
            query
              ? `No comparisons match “${query}”.`
              : "Run a comparison above (or via POST /api/comparisons) to see it here."
          }
        />
      ) : (
        <>
          <div className="space-y-3">
            {comparisons.map((c) => (
              <ComparisonCard key={c.id} comparison={c} />
            ))}
          </div>
          <Pagination
            page={pagination.page}
            pages={pagination.pages}
            total={pagination.total}
            onChange={setPage}
            noun="comparison"
          />
        </>
      )}
    </div>
  );
}
