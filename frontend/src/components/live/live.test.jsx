import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  initialLiveState,
  liveReducer,
  selectAgentRows,
  selectAverageLatency,
  selectConversationRows,
  selectCounts,
} from "../../lib/liveState.js";
import { describeEvent } from "../../lib/liveEvents.js";
import ConnectionPill from "./ConnectionPill.jsx";
import LiveTable from "./LiveTable.jsx";

function feed(state, type, data) {
  return liveReducer(state, {
    type: "event",
    event: { type, data, timestamp: new Date().toISOString() },
  });
}

describe("liveReducer", () => {
  it("tracks running vs finished agents", () => {
    let s = initialLiveState;
    s = feed(s, "agent.started", { run_id: 1, agent_name: "Planner", agent_type: "planner" });
    s = feed(s, "agent.started", { run_id: 2, agent_name: "Researcher", parent_run_id: 1 });
    expect(selectCounts(s).runningAgents).toBe(2);

    s = feed(s, "agent.finished", { run_id: 1, agent_name: "Planner", status: "success", latency_ms: 120 });
    const counts = selectCounts(s);
    expect(counts.runningAgents).toBe(1);
    expect(selectAgentRows(s)).toHaveLength(2);
  });

  it("tracks running conversations from workflow events", () => {
    let s = initialLiveState;
    s = feed(s, "workflow.updated", { conversation_run_id: 5, conversation_name: "demo", phase: "started", status: "running" });
    expect(selectCounts(s).runningConversations).toBe(1);
    expect(selectConversationRows(s)[0].name).toBe("demo");

    s = feed(s, "workflow.updated", { conversation_run_id: 5, phase: "finished", status: "success" });
    expect(selectCounts(s).runningConversations).toBe(0);
  });

  it("aggregates tokens, cost and latency from finished steps", () => {
    let s = initialLiveState;
    s = feed(s, "step.started", { step_id: 1 });
    s = feed(s, "step.finished", { step_id: 1, latency_ms: 100, token_usage: { total: 30 }, cost: 0.01 });
    s = feed(s, "step.finished", { step_id: 2, latency_ms: 300, token_usage: { input: 10, output: 5 }, cost: 0.02 });
    expect(s.totals.tokens).toBe(45);
    expect(s.totals.cost).toBeCloseTo(0.03);
    expect(selectAverageLatency(s)).toBe(200);
  });

  it("seeds and decrements running evaluations", () => {
    let s = liveReducer(initialLiveState, { type: "seed", replays: 2, evaluations: 3 });
    expect(selectCounts(s).runningReplays).toBe(2);
    expect(selectCounts(s).runningEvaluations).toBe(3);
    s = feed(s, "evaluation.finished", { evaluation_run_id: 9, overall_score: 0.8 });
    expect(selectCounts(s).runningEvaluations).toBe(2);
  });

  it("clear keeps running rows and seeds but drops the feed", () => {
    let s = initialLiveState;
    s = liveReducer(s, { type: "seed", replays: 1, evaluations: 1 });
    s = feed(s, "agent.started", { run_id: 1, agent_name: "A" });
    s = feed(s, "agent.finished", { run_id: 2, agent_name: "B", status: "success" });
    s = liveReducer(s, { type: "clear" });
    expect(s.feed).toHaveLength(0);
    expect(selectAgentRows(s)).toHaveLength(1); // only the still-running agent
    expect(selectCounts(s).runningReplays).toBe(1);
  });
});

describe("describeEvent", () => {
  it("summarizes common event types", () => {
    expect(describeEvent("agent.started", { agent_name: "Planner" })).toMatch(/Planner/);
    expect(describeEvent("tool.finished", { tool_name: "search", status: "success" })).toMatch(/search/);
  });
});

describe("ConnectionPill", () => {
  it("labels each connection status", () => {
    const { rerender } = render(<ConnectionPill status="open" />);
    expect(screen.getByText("Live")).toBeInTheDocument();
    rerender(<ConnectionPill status="paused" />);
    expect(screen.getByText("Paused")).toBeInTheDocument();
    rerender(<ConnectionPill status="error" />);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });
});

describe("LiveTable", () => {
  const columns = [
    { key: "id", label: "ID", render: (r) => `#${r.id}` },
    { key: "name", label: "Name" },
  ];

  it("renders rows from a column config", () => {
    render(<LiveTable columns={columns} rows={[{ id: 1, name: "Planner", updatedAt: "a" }]} />);
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Planner")).toBeInTheDocument();
  });

  it("shows an empty state when there are no rows", () => {
    render(<LiveTable columns={columns} rows={[]} empty="nothing running" />);
    expect(screen.getByText("nothing running")).toBeInTheDocument();
  });
});
