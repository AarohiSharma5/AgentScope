import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import AgentCard from "./AgentCard.jsx";
import AgentTree from "./AgentTree.jsx";
import MessageViewer from "./MessageViewer.jsx";
import ConversationTimeline from "./ConversationTimeline.jsx";
import ConversationsTable from "./ConversationsTable.jsx";
import ExecutionGraph from "./ExecutionGraph.jsx";

const NODE = {
  id: 1,
  name: "Planner",
  role: "planner",
  status: "success",
  latency_ms: 120,
  total_tokens: 42,
  cost: 0.0012,
  parent_node_id: null,
  children: [{ id: 2, name: "Researcher" }],
};

describe("AgentCard", () => {
  it("renders role, status, latency, tokens, cost and lineage", () => {
    render(<AgentCard node={NODE} />);
    expect(screen.getByText("Planner")).toBeInTheDocument();
    expect(screen.getByText("planner")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
    expect(screen.getByText("120ms")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("$0.0012")).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument(); // parent
  });

  it("fires onSelect when clicked", () => {
    const onSelect = vi.fn();
    render(<AgentCard node={NODE} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("Planner"));
    expect(onSelect).toHaveBeenCalledWith(NODE);
  });
});

describe("AgentTree", () => {
  it("renders nested nodes", () => {
    render(<AgentTree tree={[NODE]} />);
    expect(screen.getByText("Planner")).toBeInTheDocument();
    expect(screen.getByText("Researcher")).toBeInTheDocument();
  });

  it("shows an empty state when there are no agents", () => {
    render(<AgentTree tree={[]} />);
    expect(screen.getByText(/no agents/i)).toBeInTheDocument();
  });
});

describe("MessageViewer", () => {
  const messages = [
    {
      id: 1,
      sender_node_id: 1,
      sender: "Planner",
      receiver: "Researcher",
      message_type: "question",
      content: "What is LangSmith?",
      timestamp: "2026-01-01T00:00:00Z",
      latency_ms: 5,
    },
    {
      id: 2,
      sender_node_id: 2,
      sender: "Researcher",
      receiver: "Planner",
      message_type: "answer",
      content: "An observability platform.",
      reply_to_id: 1,
      timestamp: "2026-01-01T00:00:01Z",
    },
  ];

  it("renders message content and participants", () => {
    render(<MessageViewer messages={messages} />);
    expect(screen.getByText("What is LangSmith?")).toBeInTheDocument();
    expect(screen.getByText("An observability platform.")).toBeInTheDocument();
    expect(screen.getByText(/reply to #1/)).toBeInTheDocument();
  });

  it("renders an empty state with no messages", () => {
    render(<MessageViewer messages={[]} />);
    expect(screen.getByText(/no messages/i)).toBeInTheDocument();
  });
});

describe("ConversationTimeline", () => {
  it("renders events with from/to", () => {
    render(
      <ConversationTimeline
        events={[
          {
            id: 1,
            message_type: "instruction",
            from: "Planner",
            to: "Researcher",
            timestamp: "2026-01-01T00:00:00Z",
            latency_ms: 3,
          },
        ]}
      />
    );
    expect(screen.getByText("Planner")).toBeInTheDocument();
    expect(screen.getByText("Researcher")).toBeInTheDocument();
    expect(screen.getByText("instruction")).toBeInTheDocument();
  });
});

describe("ConversationsTable", () => {
  it("renders conversation rows", () => {
    render(
      <MemoryRouter>
        <ConversationsTable
          conversations={[
            {
              id: 7,
              conversation_name: "research",
              agent_count: 3,
              status: "success",
              latency_ms: 900,
              started_at: "2026-01-01T00:00:00Z",
              finished_at: "2026-01-01T00:00:01Z",
            },
          ]}
        />
      </MemoryRouter>
    );
    expect(screen.getByText("research")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
  });
});

describe("ExecutionGraph", () => {
  const nodes = [
    { id: "planner", type: "task", role: "plan" },
    { id: "reviewer", type: "task", role: "review" },
  ];
  const edges = [{ from: "planner", to: "reviewer", kind: "next" }];

  it("renders node labels", () => {
    render(<ExecutionGraph nodes={nodes} edges={edges} entry="planner" />);
    expect(screen.getByText("planner")).toBeInTheDocument();
    expect(screen.getByText("reviewer")).toBeInTheDocument();
  });

  it("shows an empty state with no nodes", () => {
    render(<ExecutionGraph nodes={[]} edges={[]} entry={null} />);
    expect(screen.getByText(/no nodes/i)).toBeInTheDocument();
  });

  it("opens a detail panel when a node is clicked", () => {
    render(<ExecutionGraph nodes={nodes} edges={edges} entry="planner" />);
    fireEvent.click(screen.getByText("planner"));
    // The detail panel repeats the node id as a heading.
    expect(screen.getAllByText("planner").length).toBeGreaterThan(1);
  });
});
