import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, setUnauthorizedHandler } from "../api/client.js";
import { clearTokens, getAccessToken, setTokens } from "../api/authStore.js";

// Session state for the app.
//
//   status: "loading"  -> a stored token is being verified
//           "anonymous"-> no (valid) session; open mode still renders
//           "authenticated" -> a user session is active
//   authRequired: the backend demanded auth (a request 401'd unrecoverably),
//                 so the login gate should be shown. Kept separate from status
//                 so open mode (AUTH_ENABLED=false) never forces a login.
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(() =>
    getAccessToken() ? "loading" : "anonymous"
  );
  const [authRequired, setAuthRequired] = useState(false);

  // The client calls this when a request is unauthorized and refresh failed.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setStatus("anonymous");
      setAuthRequired(true);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  // Verify a stored token on boot (and hydrate the user), if present.
  useEffect(() => {
    let active = true;
    if (!getAccessToken()) {
      setStatus("anonymous");
      return () => {
        active = false;
      };
    }
    api
      .me()
      .then((res) => {
        if (!active) return;
        setUser(res.user || res.identity || null);
        setStatus("authenticated");
        setAuthRequired(false);
      })
      .catch(() => {
        // Token invalid/expired and refresh failed: fall back to open/anonymous.
        if (active) setStatus("anonymous");
      });
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (email, password) => {
    const res = await api.login(email, password);
    setTokens(res.tokens);
    setUser(res.user || null);
    setStatus("authenticated");
    setAuthRequired(false);
    return res;
  }, []);

  const logout = useCallback(() => {
    clearTokens();
    setUser(null);
    setStatus("anonymous");
    setAuthRequired(false);
  }, []);

  // Let the header offer an explicit "Sign in" affordance in open mode.
  const requestLogin = useCallback(() => setAuthRequired(true), []);
  const dismissLogin = useCallback(() => setAuthRequired(false), []);

  const value = useMemo(
    () => ({ user, status, authRequired, login, logout, requestLogin, dismissLogin }),
    [user, status, authRequired, login, logout, requestLogin, dismissLogin]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
