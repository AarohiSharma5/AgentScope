import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import WorkflowsTable from "../components/workflow/WorkflowsTable.jsx";
import { INTERACTIVE_ROW_CLASS, ROW_LINK_CLASS } from "./rowInteraction.js";

describe("row interaction helpers", () => {
  it("exports class strings for the row affordance and the primary link", () => {
    expect(INTERACTIVE_ROW_CLASS).toContain("hover:bg-ink-600");
    // The link, not the row, carries the keyboard focus ring.
    expect(ROW_LINK_CLASS).toContain("focus-visible:ring-accent");
  });

  it("navigates via a real <Link> in the primary cell, not a role=button row", () => {
    render(
      <MemoryRouter>
        <WorkflowsTable
          workflows={[
            { id: 7, workflow_name: "research", version: "v1", execution_count: 3, updated_at: null },
          ]}
        />
      </MemoryRouter>
    );

    // The row keeps native table-row semantics (no role="button").
    const row = screen.getByRole("row", { name: /open workflow 7/i });
    expect(row.tagName).toBe("TR");
    expect(row).not.toHaveAttribute("role", "button");

    // The primary cell holds a genuine navigational link to the detail view.
    const link = within(row).getByRole("link", { name: /open workflow 7/i });
    expect(link).toHaveAttribute("href", "/workflows/7");
  });
});
