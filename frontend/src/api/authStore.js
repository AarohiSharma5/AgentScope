// Browser-side token storage for the auth/session layer.
//
// Tokens are kept in localStorage so a session survives reloads and is shared
// across tabs. Trade-off: localStorage is readable by JavaScript, so it is
// XSS-exposed — this is mitigated by short-lived access tokens plus refresh
// (see the backend JWT_ACCESS_TTL). Subscribers are notified on any change so
// the auth context / SSE stream can react (e.g. to a login in another tab).
const ACCESS_KEY = "agentscope.access_token";
const REFRESH_KEY = "agentscope.refresh_token";

const listeners = new Set();

function safeGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null; // storage unavailable (private mode / SSR)
  }
}

function safeSet(key, value) {
  try {
    if (value == null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* ignore: storage unavailable */
  }
}

export function getAccessToken() {
  return safeGet(ACCESS_KEY);
}

export function getRefreshToken() {
  return safeGet(REFRESH_KEY);
}

export function hasTokens() {
  return Boolean(getAccessToken());
}

// Persist a token pair as returned by the backend ({ access_token, refresh_token }).
export function setTokens(tokens) {
  safeSet(ACCESS_KEY, tokens?.access_token ?? null);
  if (tokens && "refresh_token" in tokens) {
    safeSet(REFRESH_KEY, tokens.refresh_token ?? null);
  }
  notify();
}

export function clearTokens() {
  safeSet(ACCESS_KEY, null);
  safeSet(REFRESH_KEY, null);
  notify();
}

// Subscribe to token changes; returns an unsubscribe function.
export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify() {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      /* a broken listener must not break the store */
    }
  });
}
