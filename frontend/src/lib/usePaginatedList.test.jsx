import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { usePaginatedList } from "./usePaginatedList.js";

// A fetcher that echoes the params it was called with, in the {data, pagination}
// envelope every list endpoint returns.
function makeFetcher() {
  return vi.fn((params) =>
    Promise.resolve({
      data: [{ id: 1, q: params.q }],
      pagination: { page: params.page, pages: 1, total: 1 },
    })
  );
}

describe("usePaginatedList", () => {
  it("fetches on mount and exposes the data + pagination envelope", async () => {
    const fetcher = makeFetcher();
    const { result } = renderHook(() => usePaginatedList(fetcher, { limit: 20 }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, limit: 20, sort: "-created_at", q: "" }),
      expect.objectContaining({ signal: expect.any(Object) })
    );
    expect(result.current.data).toHaveLength(1);
    expect(result.current.pagination.total).toBe(1);
  });

  it("debounces the search box and refetches with the query", async () => {
    const fetcher = makeFetcher();
    const { result } = renderHook(() => usePaginatedList(fetcher, { limit: 20 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.setSearch("hello"));
    await waitFor(
      () =>
        expect(fetcher).toHaveBeenLastCalledWith(
          expect.objectContaining({ q: "hello", page: 1 }),
          expect.anything()
        ),
      { timeout: 2000 }
    );
  });

  it("omits sort entirely when initialSort is null", async () => {
    const fetcher = makeFetcher();
    const { result } = renderHook(() =>
      usePaginatedList(fetcher, { limit: 20, initialSort: null })
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher.mock.calls[0][0]).not.toHaveProperty("sort");
  });

  it("reload() forces a refetch", async () => {
    const fetcher = makeFetcher();
    const { result } = renderHook(() => usePaginatedList(fetcher, { limit: 20 }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const before = fetcher.mock.calls.length;
    act(() => result.current.reload());
    await waitFor(() => expect(fetcher.mock.calls.length).toBeGreaterThan(before));
  });
});
