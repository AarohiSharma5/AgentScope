// Thin REST client for the AgentScope backend.
const BASE = "/api";

async function request(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    // Surface the backend's consistent { error } envelope when available.
    let detail = `request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && body.error) detail = body.error;
    } catch {
      /* non-JSON response; fall back to the status message */
    }
    throw new Error(detail);
  }
  return res.json();
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
  // v0.1 — LLM request traces
  getStats: () => request("/stats"),
  getTraces: () => request("/traces"),
  getTrace: (id) => request(`/traces/${id}`),

  // v0.2 — agent execution tracing
  getAgentRuns: (params) => request(`/agent-runs${buildQuery(params)}`),
  getAgentRun: (id) => request(`/agent-runs/${id}`),
  getRequestAgentRuns: (requestId) => request(`/requests/${requestId}/agent-runs`),
  getAgentMetrics: () => request("/dashboard/agent-metrics"),

  // v0.3 — RAG / retrieval / prompt assembly
  getRetrievals: (params) => request(`/retrievals${buildQuery(params)}`),
  getRetrieval: (id) => request(`/retrievals/${id}`),
  getPrompt: (id) => request(`/prompts/${id}`),
  getRagMetrics: () => request("/dashboard/rag-metrics"),
};
