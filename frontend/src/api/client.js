// Thin REST client for the AgentScope backend.
const BASE = "/api";

// Surface the backend's consistent { error } envelope when available.
async function unwrap(res) {
  if (!res.ok) {
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

async function request(path) {
  return unwrap(await fetch(`${BASE}${path}`));
}

async function post(path, body = {}) {
  return unwrap(
    await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
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

  // v0.4 — multi-agent workflows, conversations and messages
  getWorkflows: (params) => request(`/workflows${buildQuery(params)}`),
  getWorkflow: (id) => request(`/workflows/${id}`),
  getConversations: (params) => request(`/conversations${buildQuery(params)}`),
  getConversation: (id) => request(`/conversations/${id}`),
  getMessages: (params) => request(`/messages${buildQuery(params)}`),
  getWorkflowMetrics: () => request("/dashboard/workflow-metrics"),

  // v0.5 — replay, evaluation and model comparison
  getReplays: (params) => request(`/replays${buildQuery(params)}`),
  getReplay: (id) => request(`/replays/${id}`),
  createReplay: (body) => post("/replays", body),
  getEvaluations: (params) => request(`/evaluations${buildQuery(params)}`),
  getEvaluation: (id) => request(`/evaluations/${id}`),
  createEvaluation: (body) => post("/evaluations", body),
  getComparisons: (params) => request(`/comparisons${buildQuery(params)}`),
  createComparison: (body) => post("/comparisons", body),
  getEvaluationMetrics: () => request("/dashboard/evaluation-metrics"),
  getEvaluationAnalytics: () => request("/dashboard/evaluation-analytics"),

  // v0.5 — prompt versions, prompt diff and trace diff
  getPromptVersions: (params) => request(`/prompt-versions${buildQuery(params)}`),
  getPromptVersion: (id) => request(`/prompt-versions/${id}`),
  getPromptDiff: (a, b) => request(`/prompt-diff${buildQuery({ a, b })}`),
  getTraceDiff: (a, b) => request(`/trace-diff${buildQuery({ a, b })}`),
};
