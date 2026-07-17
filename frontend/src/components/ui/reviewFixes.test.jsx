import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ErrorState from "./ErrorState.jsx";
import BarChart from "../charts/BarChart.jsx";
import { API_BASE, STREAM_URL } from "../../api/config.js";

describe("ErrorState", () => {
  it("announces via role=alert and offers a retry action", () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Boom" onRetry={onRetry} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Boom");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders no retry button when no handler is supplied", () => {
    render(<ErrorState message="Boom" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("chart accessibility", () => {
  it("exposes a data-table fallback alongside the visual bars", () => {
    render(
      <BarChart
        data={[{ label: "Mon", value: 3 }]}
        format={(v) => `${v}`}
        label="Weekly totals"
      />
    );
    // Labeled as a group for assistive tech...
    expect(screen.getByRole("group", { name: "Weekly totals" })).toBeInTheDocument();
    // ...and the underlying values are available as a real table.
    const table = screen.getByRole("table", { hidden: true });
    expect(table).toHaveTextContent("Mon");
    expect(table).toHaveTextContent("3");
  });
});

describe("api config", () => {
  it("derives the SSE stream URL from the shared API base", () => {
    expect(STREAM_URL).toBe(`${API_BASE}/stream`);
    // Defaults to the same-origin proxy path when VITE_API_BASE_URL is unset.
    expect(API_BASE).toBe("/api");
  });
});
