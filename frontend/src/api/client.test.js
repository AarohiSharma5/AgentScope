import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, request, post, setUnauthorizedHandler } from "./client.js";
import { clearTokens, getAccessToken, setTokens } from "./authStore.js";

const jsonRes = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

beforeEach(() => {
  clearTokens();
  setUnauthorizedHandler(null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("sends no auth header when there is no token, and Bearer when there is", async () => {
    let headers;
    global.fetch = vi.fn(async (_url, init) => {
      headers = init.headers;
      return jsonRes({ ok: true });
    });

    await request("/stats");
    expect(headers.Authorization).toBeUndefined();

    setTokens({ access_token: "tok123" });
    await request("/stats");
    expect(headers.Authorization).toBe("Bearer tok123");
  });

  it("surfaces the backend { error } envelope", async () => {
    global.fetch = vi.fn(async () => jsonRes({ error: "bad thing" }, 400));
    await expect(request("/stats")).rejects.toThrow("bad thing");
    expect(global.fetch).toHaveBeenCalledTimes(1); // 400 is not retried
  });

  it("retries idempotent GETs on 5xx, then succeeds", async () => {
    let n = 0;
    global.fetch = vi.fn(async () => {
      n += 1;
      return n < 2 ? jsonRes({ error: "flaky" }, 503) : jsonRes({ ok: 1 });
    });
    const data = await request("/stats");
    expect(data).toEqual({ ok: 1 });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it("never retries a POST on 5xx", async () => {
    global.fetch = vi.fn(async () => jsonRes({ error: "boom" }, 500));
    await expect(post("/replays", {})).rejects.toThrow("boom");
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("refreshes the token once on 401 and replays the request", async () => {
    setTokens({ access_token: "old", refresh_token: "r1" });
    let dataCalls = 0;
    global.fetch = vi.fn(async (url, init) => {
      if (url.endsWith("/auth/refresh")) {
        return jsonRes({ tokens: { access_token: "new", refresh_token: "r2" } });
      }
      dataCalls += 1;
      if (dataCalls === 1) return jsonRes({ error: "unauthorized" }, 401);
      expect(init.headers.Authorization).toBe("Bearer new"); // replayed with fresh token
      return jsonRes({ ok: true });
    });

    const data = await request("/stats");
    expect(data).toEqual({ ok: true });
    expect(getAccessToken()).toBe("new");
  });

  it("clears the session and notifies when a 401 cannot be refreshed", async () => {
    setTokens({ access_token: "only-access" }); // no refresh token
    const onUnauth = vi.fn();
    setUnauthorizedHandler(onUnauth);
    global.fetch = vi.fn(async () => jsonRes({ error: "nope" }, 401));

    await expect(request("/stats")).rejects.toMatchObject({ status: 401 });
    expect(onUnauth).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });

  it("propagates caller cancellation without retrying", async () => {
    global.fetch = vi.fn(async (_url, init) => {
      if (init.signal?.aborted) {
        const err = new Error("aborted");
        err.name = "AbortError";
        throw err;
      }
      return jsonRes({ ok: true });
    });

    const controller = new AbortController();
    controller.abort();
    await expect(request("/stats", { signal: controller.signal })).rejects.toHaveProperty(
      "name",
      "AbortError"
    );
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it("login posts credentials and returns the token payload", async () => {
    global.fetch = vi.fn(async (url, init) => {
      expect(url).toContain("/auth/login");
      expect(JSON.parse(init.body)).toEqual({ email: "a@b.co", password: "pw" });
      return jsonRes({ user: { email: "a@b.co" }, tokens: { access_token: "t" } });
    });
    const res = await api.login("a@b.co", "pw");
    expect(res.user.email).toBe("a@b.co");
  });
});
