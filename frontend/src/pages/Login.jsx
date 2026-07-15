import { useState } from "react";
import { useAuth } from "../lib/AuthContext.jsx";

// Sign-in screen shown when the backend requires authentication (a request
// returned 401), or when the user explicitly chooses to sign in. In open mode
// (AUTH_ENABLED=false) this is never surfaced automatically.
export default function Login({ onCancel }) {
  const { login, dismissLogin } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err) {
      setError(err.message || "Sign in failed");
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = () => {
    dismissLogin();
    onCancel?.();
  };

  return (
    <div className="mx-auto max-w-sm">
      <div className="rounded-2xl border border-ink-500 bg-ink-800 p-6 shadow-lg">
        <h1 className="text-lg font-semibold text-gray-100">Sign in to AgentScope</h1>
        <p className="mt-1 text-sm text-gray-500">
          This instance requires authentication.
        </p>

        <form onSubmit={submit} className="mt-5 space-y-4">
          <div>
            <label htmlFor="email" className="text-xs uppercase tracking-wider text-gray-500">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-ink-500 bg-ink-900 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent"
            />
          </div>
          <div>
            <label htmlFor="password" className="text-xs uppercase tracking-wider text-gray-500">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-lg border border-ink-500 bg-ink-900 px-3 py-2 text-sm text-gray-200 outline-none focus:border-accent"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-rose-400">
              {error}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-60"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </button>
            {onCancel && (
              <button
                type="button"
                onClick={cancel}
                className="rounded-lg border border-ink-500 bg-ink-700 px-4 py-2 text-sm text-gray-300 transition-colors hover:bg-ink-600"
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
