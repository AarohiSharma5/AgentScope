import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the API client so pages can be tested without a backend. Every list page
// helper resolves the shared `{data, pagination}` envelope.
vi.mock("../api/client.js", () => ({
  api: {
    getStats: vi.fn(),
    getTraces: vi.fn(),
    getAgentRuns: vi.fn(),
    // Filter facets load on mount for these pages; default to empty so tests
    // that don't care about filtering still render.
    getTraceFacets: vi.fn(() => Promise.resolve({ areas: [], models: [], statuses: [] })),
    getAgentRunFacets: vi.fn(() => Promise.resolve({ areas: [], statuses: [] })),
  },
}));

import { api } from "../api/client.js";
import Dashboard from "./Dashboard.jsx";
import AgentRuns from "./AgentRuns.jsx";

const renderPage = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

const STATS = {
  total_requests: 3,
  avg_latency_ms: 120,
  avg_tokens: 200,
  avg_cost: 0.001,
  success_rate: 100,
};

const TRACE = {
  id: 1,
  model_name: "gpt-4o",
  user_prompt: "hello there",
  status: "success",
  total_tokens: 150,
  latency_ms: 120,
  estimated_cost: 0.001,
  timestamp: "2026-01-01T00:00:00Z",
};

const RUN = {
  id: 7,
  agent_name: "Planner",
  agent_type: "planner",
  status: "success",
  latency_ms: 120,
  start_time: "2026-01-01T00:00:00Z",
  end_time: "2026-01-01T00:00:01Z",
  request_id: 1,
};

describe("Dashboard page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders stats and recent traces after loading", async () => {
    api.getStats.mockResolvedValue(STATS);
    api.getTraces.mockResolvedValue({ data: [TRACE], pagination: { total: 1 } });

    renderPage(<Dashboard />);

    expect(await screen.findByText("Total Requests")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    // The trace row rendered its model and prompt.
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("hello there")).toBeInTheDocument();
  });

  it("shows an empty state when there are no traces", async () => {
    api.getStats.mockResolvedValue(STATS);
    api.getTraces.mockResolvedValue({ data: [], pagination: { total: 0 } });

    renderPage(<Dashboard />);

    expect(await screen.findByText("No requests yet")).toBeInTheDocument();
  });

  it("surfaces a load failure via an alert", async () => {
    api.getStats.mockRejectedValue(new Error("backend down"));
    api.getTraces.mockResolvedValue({ data: [], pagination: { total: 0 } });

    renderPage(<Dashboard />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/backend down/);
  });
});

describe("AgentRuns page", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads and renders agent-run rows", async () => {
    api.getAgentRuns.mockResolvedValue({
      data: [RUN],
      pagination: { page: 1, pages: 1, total: 1 },
    });

    renderPage(<AgentRuns />);

    expect(await screen.findByText("Planner")).toBeInTheDocument();
    expect(api.getAgentRuns).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, limit: 20 }),
      expect.objectContaining({ signal: expect.anything() })
    );
  });

  it("shows an empty state when there are no runs", async () => {
    api.getAgentRuns.mockResolvedValue({
      data: [],
      pagination: { page: 1, pages: 1, total: 0 },
    });

    renderPage(<AgentRuns />);

    expect(await screen.findByText("No agent runs yet")).toBeInTheDocument();
  });

  it("debounces the search box and refetches with the query", async () => {
    api.getAgentRuns.mockResolvedValue({
      data: [RUN],
      pagination: { page: 1, pages: 1, total: 1 },
    });

    renderPage(<AgentRuns />);
    await screen.findByText("Planner");

    fireEvent.change(
      screen.getByPlaceholderText(/Filter by agent/i),
      { target: { value: "plan" } }
    );

    await waitFor(() =>
      expect(api.getAgentRuns).toHaveBeenCalledWith(
        expect.objectContaining({ q: "plan" }),
        expect.anything()
      )
    );
  });
});
