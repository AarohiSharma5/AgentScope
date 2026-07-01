import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import EmbeddingCard from "./EmbeddingCard.jsx";
import DocumentCard from "./DocumentCard.jsx";
import SimilarityChart from "./SimilarityChart.jsx";
import PromptBlock from "./PromptBlock.jsx";
import RetrievalsTable from "./RetrievalsTable.jsx";

describe("EmbeddingCard", () => {
  it("renders model, dimensions, latency and cost", () => {
    render(
      <EmbeddingCard
        embedding={{
          embedding_model: "text-embedding-3-small",
          embedding_dimension: 1536,
          latency_ms: 12,
          cost: 0.0002,
        }}
      />
    );
    expect(screen.getByText("text-embedding-3-small")).toBeInTheDocument();
    expect(screen.getByText("1,536")).toBeInTheDocument();
    expect(screen.getByText("12ms")).toBeInTheDocument();
    expect(screen.getByText("$0.0002")).toBeInTheDocument();
  });

  it("renders nothing when no embedding", () => {
    const { container } = render(<EmbeddingCard embedding={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DocumentCard", () => {
  it("shows a selected badge and a collapsible preview for long text", () => {
    const longText = "x".repeat(500);
    render(
      <DocumentCard
        document={{
          id: 1,
          document_name: "Doc 1",
          similarity_score: 0.87,
          selected: true,
          chunk_text: longText,
        }}
      />
    );
    expect(screen.getByText("Selected")).toBeInTheDocument();
    expect(screen.getByText("0.870")).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: /show more/i });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
  });
});

describe("SimilarityChart", () => {
  const docs = [
    { id: 1, document_name: "A", similarity_score: 0.4, selected: true },
    { id: 2, document_name: "B", similarity_score: 0.6, selected: false },
  ];

  it("shows the average and toggles between bars and histogram", () => {
    render(<SimilarityChart documents={docs} />);
    expect(screen.getByText("avg 0.500")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Histogram" }));
    fireEvent.click(screen.getByRole("button", { name: "Bars" }));
    // Still shows the average after toggling views.
    expect(screen.getByText("avg 0.500")).toBeInTheDocument();
  });

  it("handles an empty document set", () => {
    render(<SimilarityChart documents={[]} />);
    expect(screen.getByText(/no scored documents/i)).toBeInTheDocument();
  });
});

describe("PromptBlock", () => {
  it("copies text to the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue();
    Object.assign(navigator, { clipboard: { writeText } });

    render(<PromptBlock label="System Prompt" text="hello prompt" tokens={3} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("hello prompt");
  });

  it("disables copy and shows a placeholder when empty", () => {
    render(<PromptBlock label="Memory" text={null} />);
    expect(screen.getByRole("button", { name: "Copy" })).toBeDisabled();
    expect(screen.getByText(/not provided/i)).toBeInTheDocument();
  });
});

describe("RetrievalsTable", () => {
  it("renders a row with similarity, documents and status", () => {
    render(
      <MemoryRouter>
        <RetrievalsTable
          retrievals={[
            {
              id: 7,
              query: "apple pie",
              avg_similarity: 0.31,
              num_documents: 4,
              selected_count: 2,
              embedding_time_ms: 5,
              retrieval_time_ms: 10,
              embedding_model: "text-embedding-3-small",
              status: "success",
            },
          ]}
        />
      </MemoryRouter>
    );
    expect(screen.getByText("#7")).toBeInTheDocument();
    expect(screen.getByText("apple pie")).toBeInTheDocument();
    expect(screen.getByText("0.310")).toBeInTheDocument();
    expect(screen.getByText("Success")).toBeInTheDocument();
    expect(screen.getByText("text-embedding-3-small")).toBeInTheDocument();
  });
});
