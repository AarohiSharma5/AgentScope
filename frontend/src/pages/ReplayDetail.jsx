import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { fmtCost, fmtLatency, fmtTime } from "../lib/format.js";

import Card from "../components/ui/Card.jsx";
import Field from "../components/ui/Field.jsx";
import Section from "../components/ui/Section.jsx";
import Skeleton from "../components/ui/Skeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import DiffTable from "../components/eval/DiffTable.jsx";

// Aggregate a conversation-detail payload into { cost, tokens, latency_ms, output }.
function conversationSummary(conversation) {
  const steps = conversation?.steps || [];
  let cost = 0;
  let tokens = 0;
  let output = null;
  steps.forEach((s) => {
    cost += s.cost || 0;
    const usage = s.token_usage || {};
    tokens += usage.total || (usage.input || 0) + (usage.output || 0);
    if (s.output != null) output = s.output;
  });
  return {
    cost: cost || null,
    tokens: tokens || null,
    latency_ms: conversation?.latency_ms ?? null,
    output,
  };
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export default function ReplayDetail() {
  const { id } = useParams();
  const [replay, setReplay] = useState(null);
  const [original, setOriginal] = useState(null);
  const [replayConv, setReplayConv] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setReplay(null);

    api
      .getReplay(id)
      .then(async (r) => {
        if (!active) return;
        setReplay(r);
        const replayConvId = r.metadata?.replay_conversation_run_id;
        // Fetch both conversations; tolerate either being unavailable.
        const [orig, rep] = await Promise.all([
          api.getConversation(r.original_conversation_run_id).catch(() => null),
          replayConvId ? api.getConversation(replayConvId).catch(() => null) : null,
        ]);
        if (!active) return;
        setOriginal(orig);
        setReplayConv(rep);
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  return (
    <div className="space-y-6">
      <Link to="/replays" className="text-sm text-accent hover:text-accent-hover">
        ← Back to replays
      </Link>

      {loading ? (
        <DetailSkeleton />
      ) : error ? (
        <ErrorState message={`Failed to load this replay: ${error}`} />
      ) : !replay ? (
        <EmptyState icon="?" title="Replay not found" message="The id may be incorrect." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">Replay #{replay.id}</h1>
              <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                {replay.replayed_model || "—"}
              </span>
              <StatusBadge status={replay.status} />
            </div>
          </div>

          <Section title="General Information">
            <Card className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
              <Field label="Original Conversation">
                <Link
                  to={`/conversations/${replay.original_conversation_run_id}`}
                  className="font-mono text-accent hover:text-accent-hover"
                >
                  #{replay.original_conversation_run_id}
                </Link>
              </Field>
              <Field label="Replay Conversation">
                {replay.metadata?.replay_conversation_run_id ? (
                  <Link
                    to={`/conversations/${replay.metadata.replay_conversation_run_id}`}
                    className="font-mono text-accent hover:text-accent-hover"
                  >
                    #{replay.metadata.replay_conversation_run_id}
                  </Link>
                ) : (
                  "—"
                )}
              </Field>
              <Field label="Temperature" value={replay.temperature} />
              <Field label="Top P" value={replay.top_p} />
              <Field label="Cost" value={fmtCost(replay.cost)} />
              <Field label="Latency" value={fmtLatency(replay.latency_ms)} />
              <Field label="Created" value={fmtTime(replay.created_at)} />
              <Field label="Mode" value={replay.metadata?.live ? "live" : "mock"} />
              {replay.system_prompt_override && (
                <Field
                  label="System Prompt Override"
                  value={replay.system_prompt_override}
                  className="col-span-2 md:col-span-4"
                />
              )}
            </Card>
          </Section>

          <Section
            title="Original vs Replay"
            action={
              replay.metadata?.replay_conversation_run_id ? (
                <Link
                  to={`/diffs?tab=trace&a=${replay.original_conversation_run_id}&b=${replay.metadata.replay_conversation_run_id}`}
                  className="text-sm text-accent hover:text-accent-hover"
                >
                  Full trace diff →
                </Link>
              ) : null
            }
          >
            {original ? (
              <DiffTable
                original={conversationSummary(original)}
                replay={conversationSummary(replayConv)}
              />
            ) : (
              <EmptyState
                message="The original conversation trace is unavailable, so a diff cannot be shown."
              />
            )}
          </Section>
        </>
      )}
    </div>
  );
}
