import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the API client so the context can be tested without a backend.
vi.mock("../api/client.js", () => ({
  api: { me: vi.fn(), login: vi.fn() },
  setUnauthorizedHandler: vi.fn(),
}));

import { api } from "../api/client.js";
import { AuthProvider, useAuth } from "./AuthContext.jsx";
import { clearTokens, getAccessToken } from "../api/authStore.js";

function Probe() {
  const { status, user, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.email || "-"}</span>
      <button onClick={() => login("a@b.co", "pw")}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

const renderProbe = () =>
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );

beforeEach(() => {
  clearTokens();
  vi.clearAllMocks();
});

describe("AuthContext", () => {
  it("starts anonymous (no /auth/me call) when there is no token", async () => {
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(api.me).not.toHaveBeenCalled();
  });

  it("logs in (stores token + user) and logs out (clears)", async () => {
    api.login.mockResolvedValue({
      user: { email: "a@b.co" },
      tokens: { access_token: "t", refresh_token: "r" },
    });
    renderProbe();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));

    await userEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(screen.getByTestId("user").textContent).toBe("a@b.co");
    expect(getAccessToken()).toBe("t");

    await userEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(getAccessToken()).toBeNull();
  });
});
