// REST client for the AgentScope backend.
//
// Responsibilities beyond a plain fetch:
//   * Auth injection — attaches `Authorization: Bearer <access>` (or a static
//     `X-API-Key` via VITE_API_KEY) so the dashboard keeps working once the
//     backend runs with AUTH_ENABLED=true. When no token exists, no auth header
//     is sent, preserving the zero-config open mode.
//   * Timeout + cancellation — every request has an internal timeout, and
//     callers may pass their own AbortSignal (e.g. to cancel on fast
//     navigation). The two are combined so either can abort the request.
//   * Retry with backoff — transient failures (network error, timeout, 5xx)
//     are retried for idempotent GETs only; writes (POST) are never retried.
//   * 401 handling — a single-flight refresh is attempted once; on success the
//     original request is retried, otherwise the session is cleared and the
//     registered handler is notified so the app can show a login screen.
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "./authStore.js";
import { API_BASE } from "./config.js";

const BASE = API_BASE;
const DEFAULT_TIMEOUT_MS = 15000;
const MAX_GET_RETRIES = 2; // up to 3 attempts total for GETs
const RETRY_BASE_MS = 300;

// Optional build-time API key, as an alternative to an interactive login.
const API_KEY =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_KEY) || null;

// Callback invoked when a request is unauthorized and cannot be recovered
// (no/expired refresh token). Wired by the auth context to reveal the login UI.
let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function authHeaders() {
  const token = getAccessToken();
  if (token) return { Authorization: `Bearer ${token}` };
  if (API_KEY) return { "X-API-Key": API_KEY };
  return {};
}

// Surface the backend's consistent { error } envelope when available.
async function parseError(res) {
  let detail = `request failed (${res.status})`;
  try {
    const body = await res.json();
    if (body && body.error) detail = body.error;
  } catch {
    /* non-JSON response; fall back to the status message */
  }
  return detail;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Bridge a caller-supplied signal to our internal (timeout) controller so that
// aborting either one aborts the underlying fetch.
function linkSignal(external, internal) {
  if (!external) return;
  if (external.aborted) {
    internal.abort();
    return;
  }
  external.addEventListener("abort", () => internal.abort(), { once: true });
}

// Single-flight token refresh: concurrent 401s share one refresh round-trip.
let refreshPromise = null;
function refreshTokens() {
  if (refreshPromise) return refreshPromise;
  const refresh_token = getRefreshToken();
  if (!refresh_token) return Promise.resolve(false);

  refreshPromise = fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  })
    .then(async (res) => {
      if (!res.ok) throw new Error("refresh failed");
      const body = await res.json();
      setTokens(body.tokens);
      return true;
    })
    .catch(() => {
      clearTokens();
      return false;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

async function core(
  method,
  path,
  { body, signal, timeout = DEFAULT_TIMEOUT_MS, _retriedAuth = false } = {}
) {
  const isGet = method === "GET";
  const maxAttempts = isGet ? MAX_GET_RETRIES + 1 : 1;
  let lastError;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const internal = new AbortController();
    linkSignal(signal, internal);
    const timer = timeout
      ? setTimeout(() => internal.abort(new DOMException("timeout", "TimeoutError")), timeout)
      : null;

    try {
      const res = await fetch(`${BASE}${path}`, {
        method,
        headers: {
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
          ...authHeaders(),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: internal.signal,
      });

      // Try to recover a 401 once via a token refresh, then replay the request.
      if (res.status === 401 && !_retriedAuth) {
        if (timer) clearTimeout(timer);
        const refreshed = await refreshTokens();
        if (refreshed) {
          return core(method, path, { body, signal, timeout, _retriedAuth: true });
        }
        // Unrecoverable: drop the stale session so we stop sending a dead token,
        // and let the app reveal the login screen.
        clearTokens();
        onUnauthorized?.();
        throw new ApiError(await parseError(res), 401);
      }

      if (!res.ok) {
        // Retry idempotent GETs on transient server errors.
        if (isGet && res.status >= 500 && attempt < maxAttempts - 1) {
          lastError = new ApiError(await parseError(res), res.status);
          if (timer) clearTimeout(timer);
          await sleep(RETRY_BASE_MS * 2 ** attempt);
          continue;
        }
        throw new ApiError(await parseError(res), res.status);
      }

      // 204 No Content (e.g. DELETE) has no body to parse.
      if (res.status === 204) {
        if (timer) clearTimeout(timer);
        return null;
      }
      const data = await res.json();
      if (timer) clearTimeout(timer);
      return data;
    } catch (err) {
      if (timer) clearTimeout(timer);

      // A caller-initiated cancellation propagates untouched (no retry).
      if (signal?.aborted) throw err;

      if (err instanceof ApiError && err.status !== 0) {
        // A definite HTTP error already handled above (non-retriable path).
        throw err;
      }

      // Network failure or our own timeout: retry idempotent GETs with backoff.
      if (isGet && attempt < maxAttempts - 1) {
        lastError = err;
        await sleep(RETRY_BASE_MS * 2 ** attempt);
        continue;
      }

      const timedOut = err?.name === "TimeoutError" || err?.name === "AbortError";
      if (err instanceof ApiError) throw err;
      throw new ApiError(timedOut ? "request timed out" : err?.message || "network error", 0);
    }
  }

  throw lastError || new ApiError("request failed", 0);
}

export function request(path, opts) {
  return core("GET", path, opts);
}

export function post(path, body = {}, opts) {
  return core("POST", path, { ...opts, body });
}

export function del(path, opts) {
  return core("DELETE", path, opts);
}

function buildQuery(params = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      q.append(key, value);
    }
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  // Auth / session
  login: (email, password) => post("/auth/login", { email, password }),
  me: (opts) => request("/auth/me", opts),

  // v0.1 — LLM request traces
  getStats: (opts) => request("/stats", opts),
  getTraces: (params, opts) => request(`/traces${buildQuery(params)}`, opts),
  getTraceFacets: (opts) => request("/traces/facets", opts),
  getTrace: (id, opts) => request(`/traces/${id}`, opts),

  // v0.2 — agent execution tracing
  getAgentRuns: (params, opts) => request(`/agent-runs${buildQuery(params)}`, opts),
  getAgentRunFacets: (opts) => request("/agent-runs/facets", opts),
  getAgentRun: (id, opts) => request(`/agent-runs/${id}`, opts),
  getRequestAgentRuns: (requestId, opts) =>
    request(`/requests/${requestId}/agent-runs`, opts),
  getAgentMetrics: (opts) => request("/dashboard/agent-metrics", opts),

  // v0.3 — RAG / retrieval / prompt assembly
  getRetrievals: (params, opts) => request(`/retrievals${buildQuery(params)}`, opts),
  getRetrieval: (id, opts) => request(`/retrievals/${id}`, opts),
  getPrompt: (id, opts) => request(`/prompts/${id}`, opts),
  getRagMetrics: (opts) => request("/dashboard/rag-metrics", opts),

  // v0.4 — multi-agent workflows, conversations and messages
  getWorkflows: (params, opts) => request(`/workflows${buildQuery(params)}`, opts),
  getWorkflow: (id, opts) => request(`/workflows/${id}`, opts),
  getConversations: (params, opts) => request(`/conversations${buildQuery(params)}`, opts),
  getInvestigationConversations: (params, opts) =>
    request(`/conversations/investigate${buildQuery(params)}`, opts),
  getConversation: (id, opts) => request(`/conversations/${id}`, opts),
  getMessages: (params, opts) => request(`/messages${buildQuery(params)}`, opts),
  getWorkflowMetrics: (opts) => request("/dashboard/workflow-metrics", opts),

  // v0.5 — replay, evaluation and model comparison
  getReplays: (params, opts) => request(`/replays${buildQuery(params)}`, opts),
  getReplay: (id, opts) => request(`/replays/${id}`, opts),
  createReplay: (body, opts) => post("/replays", body, opts),
  getEvaluations: (params, opts) => request(`/evaluations${buildQuery(params)}`, opts),
  getEvaluation: (id, opts) => request(`/evaluations/${id}`, opts),
  createEvaluation: (body, opts) => post("/evaluations", body, opts),
  getComparisons: (params, opts) => request(`/comparisons${buildQuery(params)}`, opts),
  createComparison: (body, opts) => post("/comparisons", body, opts),
  getEvaluationMetrics: (opts) => request("/dashboard/evaluation-metrics", opts),
  getEvaluationAnalytics: (params, opts) =>
    request(`/dashboard/evaluation-analytics${buildQuery(params)}`, opts),
  getEvaluationInsights: (params, opts) =>
    request(`/dashboard/evaluation-insights${buildQuery(params)}`, opts),
  getInsightsStatus: (opts) => request("/dashboard/insights-status", opts),

  // Timeline annotations (deploy / change markers)
  getAnnotations: (params, opts) => request(`/annotations${buildQuery(params)}`, opts),
  createAnnotation: (body, opts) => post("/annotations", body, opts),
  deleteAnnotation: (id, opts) => del(`/annotations/${id}`, opts),

  // Budgets / SLOs (cost caps + quality/latency/failure thresholds)
  getBudgets: (opts) => request("/budgets", opts),
  createBudget: (body, opts) => post("/budgets", body, opts),
  deleteBudget: (id, opts) => del(`/budgets/${id}`, opts),

  // Saved analytics views (custom dashboards) + shareable digest report
  getSavedViews: (opts) => request("/saved-views", opts),
  createSavedView: (body, opts) => post("/saved-views", body, opts),
  deleteSavedView: (id, opts) => del(`/saved-views/${id}`, opts),
  getEvaluationReport: (params, opts) =>
    request(`/dashboard/evaluation-report${buildQuery(params)}`, opts),

  // v0.5 — prompt versions, prompt diff and trace diff
  getPromptVersions: (params, opts) => request(`/prompt-versions${buildQuery(params)}`, opts),
  getPromptVersion: (id, opts) => request(`/prompt-versions/${id}`, opts),
  getPromptDiff: (a, b, opts) => request(`/prompt-diff${buildQuery({ a, b })}`, opts),
  getTraceDiff: (a, b, opts) => request(`/trace-diff${buildQuery({ a, b })}`, opts),
};
