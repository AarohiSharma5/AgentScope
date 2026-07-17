import { useState } from "react";
import { useLiveState } from "../lib/useLiveState.js";
import {
  selectAgentRows,
  selectAverageLatency,
  selectConversationRows,
  selectCounts,
  selectRunningAgentRows,
} from "../lib/liveState.js";
import { fmtCost, fmtLatency, fmtNumber } from "../lib/format.js";
import Section from "../components/ui/Section.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import LiveControls from "../components/live/LiveControls.jsx";
import LiveStatCard from "../components/live/LiveStatCard.jsx";
import LiveTable from "../components/live/LiveTable.jsx";
import LiveTimeline from "../components/live/LiveTimeline.jsx";
import LiveExecutionGraph from "../components/live/LiveExecutionGraph.jsx";

const CONVERSATION_COLUMNS = [
  { key: "id", label: "Conversation", className: "font-mono text-gray-400", render: (r) => `#${r.id}` },
  {
    key: "name",
    label: "Name",
    className: "text-gray-200",
    render: (r) => r.name || <span className="text-gray-600">—</span>,
  },
  { key: "phase", label: "Phase", className: "text-gray-400", render: (r) => r.phase || "—" },
  { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
  {
    key: "latency_ms",
    label: "Latency",
    className: "font-mono text-gray-300",
    render: (r) => fmtLatency(r.latency_ms),
  },
];

const AGENT_COLUMNS = [
  { key: "id", label: "Run", className: "font-mono text-gray-400", render: (r) => `#${r.id}` },
  { key: "name", label: "Agent", className: "text-gray-200", render: (r) => r.name },
  { key: "type", label: "Type", className: "text-gray-400", render: (r) => r.type || "—" },
  { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status} /> },
  {
    key: "latency_ms",
    label: "Latency",
    className: "font-mono text-gray-300",
    render: (r) => fmtLatency(r.latency_ms),
  },
];

export default function Live() {
  const [paused, setPaused] = useState(false);
  const [topics, setTopics] = useState([]); // [] == all topics

  const { status, state, controls } = useLiveState({ topics, paused });
  const counts = selectCounts(state);
  const conversationRows = selectConversationRows(state);
  const agentRows = selectAgentRows(state);
  const runningAgents = selectRunningAgentRows(state);
  const avgLatency = selectAverageLatency(state);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Live</h1>
          <p className="mt-1 text-sm text-gray-500">
            Real-time view of everything the platform is doing right now — streamed over
            Server-Sent Events.
          </p>
        </div>
        <LiveControls
          status={status}
          paused={paused}
          onTogglePause={() => setPaused((p) => !p)}
          onClear={controls.clear}
          selectedTopics={topics}
          onTopicsChange={setTopics}
        />
      </div>

      {/* Running work */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <LiveStatCard
          label="Running Conversations"
          value={fmtNumber(counts.runningConversations)}
          accent="#22d3ee"
          active={counts.runningConversations > 0}
        />
        <LiveStatCard
          label="Running Agents"
          value={fmtNumber(counts.runningAgents)}
          accent="#34d399"
          active={counts.runningAgents > 0}
        />
        <LiveStatCard
          label="Running Replays"
          value={fmtNumber(counts.runningReplays)}
          accent="#a78bfa"
          active={counts.runningReplays > 0}
        />
        <LiveStatCard
          label="Running Evaluations"
          value={fmtNumber(counts.runningEvaluations)}
          accent="#fb7185"
          active={counts.runningEvaluations > 0}
        />
      </div>

      {/* Session aggregates */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <LiveStatCard label="Live Tokens" value={fmtNumber(state.totals.tokens)} sublabel="this session" />
        <LiveStatCard label="Live Cost" value={fmtCost(state.totals.cost)} sublabel="this session" />
        <LiveStatCard label="Avg Step Latency" value={fmtLatency(avgLatency)} sublabel={`${fmtNumber(state.totals.steps)} steps`} />
        <LiveStatCard label="Events" value={fmtNumber(state.totals.events)} sublabel="received" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="Active Conversations" count={conversationRows.length}>
          <LiveTable
            columns={CONVERSATION_COLUMNS}
            rows={conversationRows}
            empty="No conversations yet — run a workflow to see it live."
          />
        </Section>

        <Section title="Running Agents" count={runningAgents.length}>
          <LiveTable
            columns={AGENT_COLUMNS}
            rows={runningAgents}
            empty="No agents running — active agents will appear here."
          />
        </Section>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="Execution Graph">
          <LiveExecutionGraph agents={agentRows} />
        </Section>

        <Section title="Activity Timeline" count={state.feed.length}>
          <div className="rounded-xl border border-ink-500 bg-ink-700 p-4">
            <LiveTimeline events={state.feed} />
          </div>
        </Section>
      </div>
    </div>
  );
}
