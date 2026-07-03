import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock the API client so the page can be tested without a backend.
vi.mock("../api/client.js", () => ({
  api: {
    getPromptDiff: vi.fn(),
    getTraceDiff: vi.fn(),
    getPromptVersions: vi.fn(),
  },
}));

import { api } from "../api/client.js";
import Diffs from "./Diffs.jsx";

const PROMPT_DIFF = {
  a: { id: 1, agent_run_id: 1, version: "v1", hash: "aaa111" },
  b: { id: 2, agent_run_id: 1, version: "v2", hash: "bbb222" },
  identical: false,
  segments: [
    { op: "equal", a: "hello ", b: "hello " },
    { op: "modified", a: "world", b: "there" },
  ],
  stats: { added: 0, removed: 0, modified: 1, unchanged: 1 },
};

const TRACE_DIFF = {
  a: { conversation_run_id: 1 },
  b: { conversation_run_id: 2 },
  metrics: [{ metric: "cost", a: 0.01, b: 0.02, delta: -0.01 }],
  counts: [{ metric: "nodes", a: 1, b: 1, delta: 0 }],
  nodes: [
    {
      index: 0,
      changed: false,
      a: { node_id: 1, name: "Responder", steps: 1, cost: 0.01, tokens: 150, output: "x" },
      b: { node_id: 2, name: "Responder", steps: 1, cost: 0.02, tokens: 150, output: "x" },
      output_diff: null,
    },
  ],
};

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Diffs />
    </MemoryRouter>
  );

describe("Diffs page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getPromptDiff.mockResolvedValue(PROMPT_DIFF);
    api.getTraceDiff.mockResolvedValue(TRACE_DIFF);
    api.getPromptVersions.mockResolvedValue({ data: [], pagination: { total: 0 } });
  });

  it("auto-loads a prompt diff from query params", async () => {
    renderAt("/diffs?tab=prompt&a=2&b=1");
    await waitFor(() => expect(api.getPromptDiff).toHaveBeenCalledWith(2, 1));
    expect(await screen.findByText("1 modified")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
  });

  it("shows an empty state when no ids are provided", () => {
    renderAt("/diffs?tab=prompt");
    expect(screen.getByText("Nothing to compare yet")).toBeInTheDocument();
    expect(api.getPromptDiff).not.toHaveBeenCalled();
  });

  it("loads a trace diff on the trace tab", async () => {
    renderAt("/diffs?tab=trace&a=1&b=2");
    await waitFor(() => expect(api.getTraceDiff).toHaveBeenCalledWith(1, 2));
    expect(await screen.findByText("Cost")).toBeInTheDocument();
    expect(screen.getByText(/Nodes \(1\)/)).toBeInTheDocument();
  });

  it("switches tabs via the toggle", () => {
    renderAt("/diffs?tab=prompt");
    fireEvent.click(screen.getByText("Trace Diff"));
    // Trace tab hides the prompt-version browser.
    expect(screen.queryByText("Browse prompt versions")).not.toBeInTheDocument();
  });
});
