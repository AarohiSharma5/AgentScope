import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { fmtLatency } from "../lib/format.js";

import Card from "../components/ui/Card.jsx";
import Field from "../components/ui/Field.jsx";
import Section from "../components/ui/Section.jsx";
import Skeleton from "../components/ui/Skeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

import EmbeddingCard from "../components/rag/EmbeddingCard.jsx";
import SimilarityChart from "../components/rag/SimilarityChart.jsx";
import DocumentCard from "../components/rag/DocumentCard.jsx";
import RetrievalTimeline from "../components/rag/RetrievalTimeline.jsx";
import PromptSections from "../components/rag/PromptSections.jsx";

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Skeleton className="h-6 w-44" />
        <Skeleton className="h-4 w-20" />
      </div>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-56 w-full" />
    </div>
  );
}

function CardList({ items, empty, render }) {
  if (!items || items.length === 0) return <EmptyState message={empty} />;
  return <div className="space-y-4">{items.map(render)}</div>;
}

export default function RetrievalDetail() {
  const { id } = useParams();
  const [retrieval, setRetrieval] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setRetrieval(null);
    api
      .getRetrieval(id)
      .then((data) => active && setRetrieval(data))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  const status =
    retrieval && retrieval.num_documents ? "success" : retrieval ? "failed" : null;

  return (
    <div className="space-y-6">
      <Link to="/retrievals" className="text-sm text-accent hover:text-accent-hover">
        ← Back to RAG Observatory
      </Link>

      {loading ? (
        <DetailSkeleton />
      ) : error ? (
        <ErrorState message={`Failed to load this retrieval: ${error}`} />
      ) : !retrieval ? (
        <EmptyState
          icon="?"
          title="Retrieval not found"
          message="This retrieval may have been deleted, or the id is incorrect."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">
                Retrieval #{retrieval.id}
              </h1>
              {retrieval.embedding?.embedding_model && (
                <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                  {retrieval.embedding.embedding_model}
                </span>
              )}
            </div>
            <StatusBadge status={status} />
          </div>

          {/* General Information */}
          <Section title="General Information">
            <Card className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
              <Field label="Query" value={retrieval.query} className="col-span-2" />
              <Field label="Documents" value={retrieval.num_documents} />
              <Field
                label="Chunks Used"
                value={retrieval.selected_documents?.length ?? 0}
              />
              <Field label="Embedding Time" value={fmtLatency(retrieval.embedding_time_ms)} />
              <Field label="Retrieval Time" value={fmtLatency(retrieval.retrieval_time_ms)} />
              <Field label="Agent Run">
                {retrieval.agent_run_id ? (
                  <Link
                    to={`/agent-runs/${retrieval.agent_run_id}`}
                    className="font-mono text-accent hover:text-accent-hover"
                  >
                    #{retrieval.agent_run_id}
                  </Link>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </Field>
              <Field label="Step" value={retrieval.step_id ? `#${retrieval.step_id}` : null} />
            </Card>
          </Section>

          {/* Embedding */}
          {retrieval.embedding && (
            <Section title="Embedding">
              <EmbeddingCard embedding={retrieval.embedding} />
            </Section>
          )}

          {/* Similarity Chart */}
          <Section title="Similarity Distribution">
            <SimilarityChart documents={retrieval.documents} />
          </Section>

          {/* Timeline */}
          <Section title="Timeline" count={retrieval.timeline?.length}>
            {retrieval.timeline?.length ? (
              <Card className="p-5">
                <RetrievalTimeline events={retrieval.timeline} />
              </Card>
            ) : (
              <EmptyState message="No timeline events for this retrieval." />
            )}
          </Section>

          {/* Document Viewer */}
          <Section title="Documents" count={retrieval.documents?.length}>
            <CardList
              items={retrieval.documents}
              empty="No documents retrieved."
              render={(doc) => <DocumentCard key={doc.id} document={doc} />}
            />
          </Section>

          {/* Prompt Assembly */}
          <Section
            title="Prompt Assembly"
            action={
              retrieval.prompt_assembly && (
                <Link
                  to={`/prompts/${retrieval.prompt_assembly.id}`}
                  className="text-xs text-accent hover:text-accent-hover"
                >
                  Open in Prompt Viewer →
                </Link>
              )
            }
          >
            {retrieval.prompt_assembly ? (
              <PromptSections prompt={retrieval.prompt_assembly} />
            ) : (
              <EmptyState message="No prompt was assembled for this retrieval's run." />
            )}
          </Section>
        </>
      )}
    </div>
  );
}
