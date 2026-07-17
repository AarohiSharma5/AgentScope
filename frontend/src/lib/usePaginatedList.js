import { useCallback, useEffect, useRef, useState } from "react";
import { useDebouncedValue } from "./useDebouncedValue.js";

// Shared plumbing for every paginated, searchable, sortable list page.
//
// Before this hook each list page (Agent Runs, Workflows, Evaluations,
// Retrievals, Conversations, Replays, Comparisons) hand-rolled the same ~40
// lines: search-box debounce, reset-to-page-1, an AbortController-guarded fetch,
// and loading/error/pagination state — and they had already drifted apart. This
// centralizes it so every list behaves identically and there is one place to fix
// bugs.
//
// `fetcher(params, opts)` must return `{ data, pagination }` and forward
// `opts.signal` to the request (all `api.get*` list helpers already do). Any
// value in `extraParams` is merged into the query and, when it changes,
// re-fetches from page 1 (e.g. a status filter). `reloadKey` bumps to force a
// refetch after a mutation.
export function usePaginatedList(
  fetcher,
  { limit = 20, initialSort = "-created_at", extraParams = null } = {}
) {
  const [page, setPage] = useState(1);
  const [sort, setSortState] = useState(initialSort);
  const [search, setSearch] = useState("");
  const query = useDebouncedValue(search.trim(), 300);
  const [reloadKey, setReloadKey] = useState(0);

  const [data, setData] = useState([]);
  const [pagination, setPagination] = useState({ page: 1, pages: 1, total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // A filter/search/sort change should always restart at page 1, but not on the
  // initial mount (that would clobber a deep-linked page). Serialize
  // `extraParams` so an object literal created each render doesn't loop.
  const extraKey = extraParams ? JSON.stringify(extraParams) : "";
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    setPage(1);
  }, [query, sort, extraKey]);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    // `sort` is omitted entirely when there is none (e.g. Comparisons), so we
    // never send an empty sort a backend might reject.
    const params = { page, limit, q: query, ...(extraParams || {}) };
    if (sort) params.sort = sort;
    fetcher(params, { signal: ctrl.signal })
      .then((res) => {
        setData(res.data);
        setPagination(res.pagination);
      })
      .catch((e) => {
        if (e.name !== "AbortError" && !ctrl.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, sort, query, limit, reloadKey, extraKey]);

  // Changing the sort resets to page 1 in the same update so there's no flash of
  // the old page under the new ordering.
  const setSort = useCallback((value) => {
    setSortState(value);
    setPage(1);
  }, []);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  return {
    data,
    pagination,
    loading,
    error,
    page,
    setPage,
    sort,
    setSort,
    search,
    setSearch,
    query,
    reload,
  };
}
