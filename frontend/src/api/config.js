// Base URL for the REST API and the SSE stream.
//
// Defaults to the same-origin `/api` (served via the Vite dev proxy in
// development and a reverse proxy in production). Override it at build time with
// `VITE_API_BASE_URL` for split deployments where the API lives on a different
// origin (e.g. "https://api.example.com/api"). Both the REST client and the
// EventSource stream derive their URLs from this single value so they can never
// drift apart.
const raw =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL) ||
  "/api";

// Normalize away a trailing slash so callers can safely concatenate `/path`.
export const API_BASE = raw.replace(/\/+$/, "");

// The Server-Sent Events endpoint, kept in lockstep with the REST base.
export const STREAM_URL = `${API_BASE}/stream`;
