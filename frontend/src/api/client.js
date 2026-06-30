// Thin REST client for the AgentScope backend.
const BASE = "/api";

async function request(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  getStats: () => request("/stats"),
  getTraces: () => request("/traces"),
  getTrace: (id) => request(`/traces/${id}`),
};
