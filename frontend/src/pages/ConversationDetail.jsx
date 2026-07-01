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
import StepCard from "../components/agent/StepCard.jsx";

import AgentTree from "../components/workflow/AgentTree.jsx";
import ConversationTimeline from "../components/workflow/ConversationTimeline.jsx";
import MessageViewer from "../components/workflow/MessageViewer.jsx";

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export default function ConversationDetail() {
  const { id } = useParams();
  const [conversation, setConversation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setConversation(null);
    api
      .getConversation(id)
      .then((data) => active && setConversation(data))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  return (
    <div className="space-y-6">
      <Link to="/conversations" className="text-sm text-accent hover:text-accent-hover">
        ← Back to conversations
      </Link>

      {loading ? (
        <DetailSkeleton />
      ) : error ? (
        <ErrorState message={`Failed to load this conversation: ${error}`} />
      ) : !conversation ? (
        <EmptyState
          icon="?"
          title="Conversation not found"
          message="This conversation may have been deleted, or the id is incorrect."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">
                {conversation.conversation_name || `Conversation #${conversation.id}`}
              </h1>
              <span className="font-mono text-sm text-gray-500">#{conversation.id}</span>
            </div>
            <StatusBadge status={conversation.status} />
          </div>

          <Section title="General Information">
            <Card className="grid grid-cols-2 gap-4 p-5 md:grid-cols-4">
              <Field label="Conversation ID" value={`#${conversation.id}`} />
              <Field label="Request">
                {conversation.request_trace_id ? (
                  <Link
                    to={`/traces/${conversation.request_trace_id}`}
                    className="font-mono text-accent hover:text-accent-hover"
                  >
                    #{conversation.request_trace_id}
                  </Link>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </Field>
              <Field label="Agents" value={conversation.agent_count} />
              <Field label="Messages" value={conversation.message_count} />
              <Field label="Latency" value={fmtLatency(conversation.latency_ms)} />
              <Field label="Started" value={fmtTime(conversation.started_at)} />
              <Field label="Finished" value={fmtTime(conversation.finished_at)} />
              <Field
                label="Workflow Exec"
                value={
                  conversation.workflow_execution
                    ? `#${conversation.workflow_execution.id}`
                    : null
                }
              />
            </Card>
          </Section>

          {/* Execution Tree — nested Agent Cards */}
          <Section title="Execution Tree">
            <AgentTree
              tree={conversation.agent_tree}
              selectedId={selectedNode}
              onSelect={(node) =>
                setSelectedNode((cur) => (cur === node.id ? null : node.id))
              }
            />
          </Section>

          {/* Timeline */}
          <Section title="Timeline" count={conversation.timeline?.length}>
            <Card className="p-5">
              <ConversationTimeline events={conversation.timeline} />
            </Card>
          </Section>

          {/* Messages — chat-like viewer */}
          <Section title="Messages" count={conversation.messages?.length}>
            <MessageViewer messages={conversation.messages} />
          </Section>

          {/* Steps */}
          <Section title="Steps" count={conversation.steps?.length}>
            {conversation.steps && conversation.steps.length ? (
              <div className="space-y-4">
                {conversation.steps.map((step) => (
                  <StepCard key={step.id} step={step} />
                ))}
              </div>
            ) : (
              <EmptyState message="No agent steps recorded in this conversation." />
            )}
          </Section>
        </>
      )}
    </div>
  );
}
