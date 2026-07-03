import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import DiffSegments from "./DiffSegments.jsx";
import PromptDiff from "./PromptDiff.jsx";
import TraceDiff from "./TraceDiff.jsx";

const SEGMENTS = [
  { op: "equal", a: "the ", b: "the " },
  { op: "modified", a: "quick", b: "slow" },
  { op: "equal", a: " brown fox", b: " brown fox" },
  { op: "added", a: "", b: " jumps" },
  { op: "removed", a: " lazily", b: "" },
];

describe("DiffSegments", () => {
  it("side A shows removed/modified but hides additions", () => {
    const { container } = render(<DiffSegments segments={SEGMENTS} side="a" />);
    expect(container.textContent).toContain("quick");
    expect(container.textContent).toContain("lazily");
    expect(container.textContent).not.toContain("jumps");
  });

  it("side B shows added/modified but hides removals", () => {
    const { container } = render(<DiffSegments segments={SEGMENTS} side="b" />);
    expect(container.textContent).toContain("slow");
    expect(container.textContent).toContain("jumps");
    expect(container.textContent).not.toContain("lazily");
  });

  it("unified view shows both old and new text", () => {
    const { container } = render(<DiffSegments segments={SEGMENTS} side="unified" />);
    expect(container.textContent).toContain("quick");
    expect(container.textContent).toContain("slow");
    expect(container.textContent).toContain("jumps");
  });
});

describe("PromptDiff", () => {
  const diff = {
    a: { id: 1, agent_run_id: 1, version: "v1", hash: "abc123def456" },
    b: { id: 2, agent_run_id: 1, version: "v2", hash: "zzz999yyy888" },
    identical: false,
    segments: SEGMENTS,
    stats: { added: 1, removed: 1, modified: 1, unchanged: 2 },
  };

  it("renders stats and toggles between split and unified", () => {
    render(<PromptDiff diff={diff} />);
    expect(screen.getByText("1 added")).toBeInTheDocument();
    expect(screen.getByText("1 removed")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Unified"));
    // Still shows the modified text after switching views.
    expect(screen.getByText("slow")).toBeInTheDocument();
  });
});

describe("TraceDiff", () => {
  const diff = {
    a: { conversation_run_id: 1 },
    b: { conversation_run_id: 2 },
    metrics: [
      { metric: "latency_ms", a: 120, b: 90, delta: 30 },
      { metric: "cost", a: 0.01, b: 0.02, delta: -0.01 },
      { metric: "total_tokens", a: 150, b: 200, delta: -50 },
    ],
    counts: [
      { metric: "nodes", a: 1, b: 1, delta: 0 },
      { metric: "tools", a: 1, b: 2, delta: -1 },
    ],
    nodes: [
      {
        index: 0,
        changed: true,
        a: { node_id: 1, role: "responder", name: "Responder", steps: 1, cost: 0.01, tokens: 150, output: "A" },
        b: { node_id: 2, role: "responder", name: "Responder", steps: 1, cost: 0.02, tokens: 200, output: "B" },
        output_diff: [
          { op: "removed", a: "A", b: "" },
          { op: "added", a: "", b: "B" },
        ],
      },
    ],
  };

  it("renders metric/count tables and per-node output diff", () => {
    render(<TraceDiff diff={diff} />);
    expect(screen.getByText("Latency")).toBeInTheDocument();
    expect(screen.getByText("Tokens")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();
    expect(screen.getByText("changed")).toBeInTheDocument();
    expect(screen.getByText("Output diff")).toBeInTheDocument();
    // The signed token delta is rendered.
    expect(screen.getByText("-50")).toBeInTheDocument();
  });
});
