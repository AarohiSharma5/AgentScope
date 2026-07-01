import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { fmtLatency, fmtTime } from "../lib/format.js";

import Card from "../components/ui/Card.jsx";
import Field from "../components/ui/Field.jsx";
import Section from "../components/ui/Section.jsx";
import Skeleton from "../components/ui/Skeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import ExecutionGraph from "../components/workflow/ExecutionGraph.jsx";

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-[460px] w-full" />
    </div>
  );
}

function ExecutionHistory({ history }) {
  if (!history || history.length === 0) {
    return <EmptyState message="This workflow has not been executed yet." />;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full min-w-[560px] text-left text-sm">
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            <th className="px-4 py-3 font-medium">Execution</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Latency</th>
            <th className="px-4 py-3 font-medium">Started</th>
            <th className="px-4 py-3 font-medium">Conversation</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {history.map((e) => (
            <tr key={e.id} className="transition-colors hover:bg-ink-600">
              <td className="px-4 py-3 font-mono text-gray-400">#{e.id}</td>
              <td className="px-4 py-3">
                <StatusBadge status={e.status} />
              </td>
              <td className="px-4 py-3 font-mono text-gray-300">{fmtLatency(e.latency_ms)}</td>
              <td className="px-4 py-3 text-gray-400">{fmtTime(e.started_at)}</td>
              <td className="px-4 py-3">
                {e.conversation_run_id ? (
                  <Link
                    to={`/conversations/${e.conversation_run_id}`}
                    className="font-mono text-accent hover:text-accent-hover"
                  >
                    #{e.conversation_run_id}
                  </Link>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function WorkflowDetail() {
  const { id } = useParams();
  const [workflow, setWorkflow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setWorkflow(null);
    api
      .getWorkflow(id)
      .then((data) => active && setWorkflow(data))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  return (
    <div className="space-y-6">
      <Link to="/workflows" className="text-sm text-accent hover:text-accent-hover">
        ← Back to workflows
      </Link>

      {loading ? (
        <DetailSkeleton />
      ) : error ? (
        <ErrorState message={`Failed to load this workflow: ${error}`} />
      ) : !workflow ? (
        <EmptyState icon="?" title="Workflow not found" message="The id may be incorrect." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">
                {workflow.workflow_name}
              </h1>
              {workflow.version && (
                <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                  v{workflow.version}
                </span>
              )}
            </div>
          </div>

          <Section title="General Information">
            <Card className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
              <Field label="Workflow ID" value={`#${workflow.id}`} />
              <Field label="Entry Node" value={workflow.entry} />
              <Field label="Nodes" value={workflow.nodes?.length} />
              <Field label="Executions" value={workflow.execution_count} />
              <Field label="Created" value={fmtTime(workflow.created_at)} />
              <Field label="Updated" value={fmtTime(workflow.updated_at)} />
              <Field label="Description" value={workflow.description} className="col-span-2" />
            </Card>
          </Section>

          <Section title="Execution Graph">
            <ExecutionGraph
              nodes={workflow.nodes}
              edges={workflow.edges}
              entry={workflow.entry}
            />
          </Section>

          <Section title="Execution History" count={workflow.execution_history?.length}>
            <ExecutionHistory history={workflow.execution_history} />
          </Section>
        </>
      )}
    </div>
  );
}
