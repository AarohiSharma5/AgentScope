import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client.js";
import ComparisonCard from "../components/eval/ComparisonCard.jsx";
import SearchInput from "../components/SearchInput.jsx";
import Pagination from "../components/Pagination.jsx";
import Card from "../components/ui/Card.jsx";
import Section from "../components/ui/Section.jsx";
import Loading from "../components/ui/Loading.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import { usePaginatedList } from "../lib/usePaginatedList.js";
import { IS_DEMO } from "../lib/demo.js";

const LIMIT = 20;

function NewComparisonForm({ onCreated, dayConversations, prefillConversationId }) {
  const [conversationId, setConversationId] = useState("");
  const [models, setModels] = useState("gpt-4o, gpt-4o-mini, claude-3-5-sonnet");
  const [evaluate, setEvaluate] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // When the "Investigate" flow supplies a conversation from the changed day,
  // preselect it so isolating a regression is one click, not manual data entry.
  useEffect(() => {
    if (prefillConversationId != null && prefillConversationId !== "") {
      setConversationId(String(prefillConversationId));
    }
  }, [prefillConversationId]);

  const dayList = Array.isArray(dayConversations) ? dayConversations : [];
  const hasDayList = dayList.length > 0;

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
        {hasDayList ? (
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wider text-gray-500">
              Conversation to replay (worst first)
            </span>
            <select
              value={conversationId}
              onChange={(e) => setConversationId(e.target.value)}
              className={`${input} w-full md:w-72`}
            >
              {dayList.map((c) => {
                const time = c.created_at
                  ? new Date(c.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "";
                const tags = [];
                if (c.status === "failed") tags.push("failed");
                if (c.overall_score != null)
                  tags.push(`score ${Math.round(c.overall_score * 100)}%`);
                if (c.total_cost) tags.push(`$${Number(c.total_cost).toFixed(4)}`);
                return (
                  <option key={c.id} value={c.id}>
                    #{c.id} · {c.conversation_name || "conversation"}
                    {time ? ` · ${time}` : ""}
                    {tags.length ? ` · ${tags.join(" · ")}` : ""}
                  </option>
                );
              })}
            </select>
          </label>
        ) : (
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
        )}
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
  const [searchParams, setSearchParams] = useSearchParams();
  // Context passed from an analytics annotation's "Investigate" link.
  const investigateLabel = searchParams.get("label");
  const investigateSince = searchParams.get("since");
  const investigateMetric = searchParams.get("metric");

  // Conversations recorded on the changed day, for one-click isolation.
  const [dayConversations, setDayConversations] = useState(null);
  const [dayLoading, setDayLoading] = useState(false);

  useEffect(() => {
    if (!investigateSince) {
      setDayConversations(null);
      return;
    }
    let cancelled = false;
    setDayLoading(true);
    // Rank that day's conversations worst-first for the regressed metric, so the
    // one most likely showing the change is pre-selected (no manual hunting).
    api
      .getInvestigationConversations({
        on: investigateSince,
        metric: investigateMetric || undefined,
        limit: 25,
      })
      .then((res) => {
        if (!cancelled) setDayConversations(res?.data ?? []);
      })
      .catch(() => {
        if (!cancelled) setDayConversations([]);
      })
      .finally(() => {
        if (!cancelled) setDayLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [investigateSince, investigateMetric]);

  const prefillConversationId = dayConversations?.[0]?.id ?? null;

  const {
    data: comparisons,
    pagination,
    loading,
    error,
    setPage,
    search,
    setSearch,
    query,
    reload,
  } = usePaginatedList(api.getComparisons, { limit: LIMIT, initialSort: null });

  const refresh = () => {
    setPage(1);
    reload();
  };

  const clearInvestigation = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("label");
    next.delete("since");
    setSearchParams(next, { replace: true });
  };

  const fmtDate = (iso) =>
    iso
      ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        })
      : "";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Model Comparisons</h1>
        <p className="mt-1 text-sm text-gray-500">
          Run a conversation against multiple models and compare them side by side.
        </p>
      </div>

      {investigateLabel && (
        <div className="flex items-start justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <span>
            <span className="font-medium">Isolating change:</span> ⚑ {investigateLabel}
            {investigateSince && (
              <span className="opacity-80"> · shipped {fmtDate(investigateSince)}</span>
            )}
            <span className="mt-0.5 block text-xs opacity-70">
              {dayLoading
                ? "Finding that day's most-affected conversations…"
                : dayConversations && dayConversations.length > 0
                ? `Pre-selected the worst${
                    investigateMetric ? ` ${investigateMetric}` : ""
                  } conversation from ${fmtDate(
                    investigateSince
                  )} below — hit “Compare models” to see which variable moved the metric.`
                : "No conversations were recorded that day — enter a conversation ID below to replay it across models."}
            </span>
          </span>
          <button
            type="button"
            onClick={clearInvestigation}
            className="shrink-0 text-xs text-amber-200/80 transition-colors hover:text-amber-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {!IS_DEMO && (
        <Section title="Run a comparison">
          <NewComparisonForm
            onCreated={refresh}
            dayConversations={dayConversations}
            prefillConversationId={prefillConversationId}
          />
        </Section>
      )}

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
