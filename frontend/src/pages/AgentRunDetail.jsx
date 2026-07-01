import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { buildExecutionTree } from "../lib/agentTree.js";
import { fmtLatency, fmtTime } from "../lib/format.js";

import Card from "../components/ui/Card.jsx";
import Field from "../components/ui/Field.jsx";
import CodeBlock from "../components/ui/CodeBlock.jsx";
import Section from "../components/ui/Section.jsx";
import Skeleton from "../components/ui/Skeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

import Timeline from "../components/agent/Timeline.jsx";
import ExecutionTree from "../components/agent/ExecutionTree.jsx";
import StepCard from "../components/agent/StepCard.jsx";
import ToolCard from "../components/agent/ToolCard.jsx";
import MemoryCard from "../components/agent/MemoryCard.jsx";
import RetrieverCard from "../components/agent/RetrieverCard.jsx";

// Render a list of cards, or an empty state when there are none.
function CardList({ items, empty, render, className = "space-y-4" }) {
  if (!items || items.length === 0) return <EmptyState message={empty} />;
  return <div className={className}>{items.map(render)}</div>;
}

// Content-shaped placeholder shown while the run detail loads.
function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-4 w-24" />
      </div>
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

export default function AgentRunDetail() {
  const { id } = useParams();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setRun(null);
    api
      .getAgentRun(id)
      .then((data) => active && setRun(data))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  const tree = useMemo(() => buildExecutionTree(run), [run]);

  return (
    <div className="space-y-6">
      <Link to="/agent-runs" className="text-sm text-accent hover:text-accent-hover">
        ← Back to agent runs
      </Link>

      {loading ? (
        <DetailSkeleton />
      ) : error ? (
        <ErrorState message={`Failed to load this agent run: ${error}`} />
      ) : !run ? (
        <EmptyState
          icon="?"
          title="Agent run not found"
          message="This run may have been deleted, or the id is incorrect."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">
                Agent Run #{run.id}
              </h1>
              <span className="text-sm text-gray-400">{run.agent_name}</span>
              {run.agent_type && (
                <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                  {run.agent_type}
                </span>
              )}
            </div>
            <StatusBadge status={run.status} />
          </div>

          {/* General Information */}
          <Section title="General Information">
            <Card className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
              <Field label="Run ID" value={`#${run.id}`} />
              <Field label="Request ID">
                <Link
                  to={`/traces/${run.request_id}`}
                  className="font-mono text-accent hover:text-accent-hover"
                >
                  #{run.request_id}
                </Link>
              </Field>
              <Field
                label="Parent Run"
                value={run.parent_run_id ? `#${run.parent_run_id}` : null}
              />
              <Field label="Steps" value={run.step_count} />
              <Field label="Latency" value={fmtLatency(run.latency_ms)} />
              <Field label="Started" value={fmtTime(run.start_time)} />
              <Field label="Ended" value={fmtTime(run.end_time)} />
              <Field label="Created" value={fmtTime(run.created_at)} />
            </Card>
          </Section>

          {/* Timeline */}
          <Section title="Timeline" count={run.timeline?.length}>
            {run.timeline && run.timeline.length ? (
              <Card className="p-5">
                <Timeline events={run.timeline} />
              </Card>
            ) : (
              <EmptyState message="No timeline events for this run." />
            )}
          </Section>

          {/* Execution Tree */}
          <Section title="Execution Tree">
            <ExecutionTree root={tree} />
          </Section>

          {/* Steps */}
          <Section title="Steps" count={run.steps?.length}>
            <CardList
              items={run.steps}
              empty="No steps recorded for this run."
              render={(step) => <StepCard key={step.id} step={step} />}
            />
          </Section>

          {/* Tools */}
          <Section title="Tools" count={run.tool_executions?.length}>
            <CardList
              items={run.tool_executions}
              empty="No tool executions in this run."
              render={(tool) => <ToolCard key={tool.id} tool={tool} />}
            />
          </Section>

          {/* Memory */}
          <Section title="Memory" count={run.memory_accesses?.length}>
            <CardList
              items={run.memory_accesses}
              empty="No memory accesses in this run."
              render={(memory) => <MemoryCard key={memory.id} memory={memory} />}
            />
          </Section>

          {/* Retriever */}
          <Section title="Retriever" count={run.retriever_traces?.length}>
            <CardList
              items={run.retriever_traces}
              empty="No retriever calls in this run."
              render={(retriever) => (
                <RetrieverCard key={retriever.id} retriever={retriever} />
              )}
            />
          </Section>

          {/* Metadata */}
          <Section title="Metadata">
            <Card className="p-5">
              <CodeBlock value={run.metadata} />
            </Card>
          </Section>
        </>
      )}
    </div>
  );
}
