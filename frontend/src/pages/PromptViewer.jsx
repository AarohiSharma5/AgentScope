import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { fmtNumber } from "../lib/format.js";

import Skeleton from "../components/ui/Skeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import PromptSections from "../components/rag/PromptSections.jsx";

export default function PromptViewer() {
  const { id } = useParams();
  const [prompt, setPrompt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setPrompt(null);
    api
      .getPrompt(id)
      .then((data) => active && setPrompt(data))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  return (
    <div className="space-y-6">
      <Link to="/retrievals" className="text-sm text-accent hover:text-accent-hover">
        ← Back to RAG Observatory
      </Link>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : error ? (
        <ErrorState message={`Failed to load this prompt: ${error}`} />
      ) : !prompt ? (
        <EmptyState
          icon="?"
          title="Prompt not found"
          message="This prompt assembly may have been deleted, or the id is incorrect."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">
                Prompt #{prompt.id}
              </h1>
              {prompt.tokens?.total != null && (
                <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                  {fmtNumber(prompt.tokens.total)} tokens
                </span>
              )}
            </div>
            {prompt.agent_run_id && (
              <Link
                to={`/agent-runs/${prompt.agent_run_id}`}
                className="text-xs text-accent hover:text-accent-hover"
              >
                Agent Run #{prompt.agent_run_id} →
              </Link>
            )}
          </div>

          <PromptSections prompt={prompt} />
        </>
      )}
    </div>
  );
}
