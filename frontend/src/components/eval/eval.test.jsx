import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import MetricCard from "./MetricCard.jsx";
import SideBySide from "./SideBySide.jsx";
import DiffTable from "./DiffTable.jsx";
import ComparisonCard from "./ComparisonCard.jsx";
import ReplaysTable from "./ReplaysTable.jsx";
import EvaluationsTable from "./EvaluationsTable.jsx";
import BarChart from "../charts/BarChart.jsx";
import LineChart from "../charts/LineChart.jsx";
import RadarChart from "../charts/RadarChart.jsx";

const withRouter = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

const PROFILE_A = {
  model: "gpt-4o",
  output: "Paris.",
  latency_ms: 120,
  total_tokens: 150,
  cost: 0.01,
  evaluation_score: 0.9,
  tool_calls: { success_rate: 1.0 },
  memory_usage: { used_rate: 1.0 },
  retriever: { precision: 0.5 },
};
const PROFILE_B = {
  model: "gpt-4o-mini",
  output: "It is Paris.",
  latency_ms: 90,
  total_tokens: 150,
  cost: 0.002,
  evaluation_score: 0.8,
  tool_calls: { success_rate: 1.0 },
  memory_usage: { used_rate: 1.0 },
  retriever: { precision: 0.5 },
};

describe("MetricCard", () => {
  it("renders a humanized name, score and weight", () => {
    render(<MetricCard metric={{ metric_name: "context_recall", metric_value: 0.75, weight: 2 }} />);
    expect(screen.getByText("Context Recall")).toBeInTheDocument();
    expect(screen.getByText("0.750")).toBeInTheDocument();
    expect(screen.getByText(/weight 2/)).toBeInTheDocument();
  });
});

describe("SideBySide", () => {
  it("shows both models, outputs, metrics and the winner", () => {
    render(<SideBySide left={PROFILE_A} right={PROFILE_B} winner="gpt-4o-mini" />);
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("Paris.")).toBeInTheDocument();
    expect(screen.getByText("It is Paris.")).toBeInTheDocument();
    expect(screen.getByText("Cost")).toBeInTheDocument();
    expect(screen.getByText("Winner")).toBeInTheDocument();
  });
});

describe("DiffTable", () => {
  it("renders original, replay and a signed diff", () => {
    render(
      <DiffTable
        original={{ cost: 0.01, tokens: 150, latency_ms: 120, output: "orig" }}
        replay={{ cost: 0.002, tokens: 150, latency_ms: 90, output: "new" }}
      />
    );
    expect(screen.getByText("orig")).toBeInTheDocument();
    expect(screen.getByText("new")).toBeInTheDocument();
    expect(screen.getByText("Cost")).toBeInTheDocument();
    // original - replay latency = +30ms
    expect(screen.getByText("+30ms")).toBeInTheDocument();
  });
});

describe("ComparisonCard", () => {
  const comparison = {
    id: 1,
    model_a: "gpt-4o",
    model_b: "gpt-4o-mini",
    winner: "gpt-4o-mini",
    cost_difference: 0.008,
    latency_difference: 30,
    token_difference: 0,
    created_at: "2026-01-01T00:00:00Z",
    metadata: { baseline: PROFILE_A, variant: PROFILE_B },
  };

  it("renders the header and expands to a side-by-side view", () => {
    render(<ComparisonCard comparison={comparison} />);
    expect(screen.getByText(/gpt-4o-mini wins/)).toBeInTheDocument();
    // Outputs are hidden until expanded.
    expect(screen.queryByText("It is Paris.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("vs"));
    expect(screen.getByText("It is Paris.")).toBeInTheDocument();
  });
});

describe("ReplaysTable", () => {
  const replays = [
    {
      id: 5,
      replayed_model: "gpt-4o-mini",
      status: "success",
      latency_ms: 90,
      cost: 0.002,
      original_conversation_run_id: 2,
      created_at: "2026-01-01T00:00:00Z",
    },
  ];

  it("renders rows and fires the replay-again callback", () => {
    const onReplayAgain = vi.fn();
    withRouter(<ReplaysTable replays={replays} onReplayAgain={onReplayAgain} />);
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Replay again"));
    expect(onReplayAgain).toHaveBeenCalledWith(replays[0]);
  });
});

describe("EvaluationsTable", () => {
  it("renders evaluation rows", () => {
    withRouter(
      <EvaluationsTable
        evaluations={[
          {
            id: 3,
            evaluation_type: "rule_based",
            overall_score: 0.82,
            status: "success",
            metrics: [{}, {}],
            conversation_run_id: 1,
            created_at: "2026-01-01T00:00:00Z",
          },
        ]}
      />
    );
    expect(screen.getByText("rule_based")).toBeInTheDocument();
    expect(screen.getByText("0.820")).toBeInTheDocument();
  });
});

describe("charts", () => {
  it("BarChart renders values and an empty state", () => {
    const { rerender } = render(
      <BarChart data={[{ label: "Jul 1", value: 10 }]} format={(v) => `${v}`} />
    );
    // The label appears both in the visual (aria-hidden) chart and the
    // screen-reader data-table fallback.
    expect(screen.getAllByText("Jul 1").length).toBeGreaterThanOrEqual(1);
    rerender(<BarChart data={[]} emptyMessage="Nothing" />);
    expect(screen.getByText("Nothing")).toBeInTheDocument();
  });

  it("LineChart shows an empty state with no data", () => {
    render(<LineChart data={[]} emptyMessage="No points" />);
    expect(screen.getByText("No points")).toBeInTheDocument();
  });

  it("RadarChart needs at least three axes", () => {
    render(<RadarChart axes={[{ label: "a", value: 0.5 }]} emptyMessage="Too few" />);
    expect(screen.getByText("Too few")).toBeInTheDocument();
  });
});
