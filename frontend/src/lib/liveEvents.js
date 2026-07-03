// Streaming event taxonomy (mirrors backend app/streaming/events.py) plus the
// per-topic presentation metadata shared by the live dashboard components.

// Coarse topics usable as the ?events= subscription filter.
export const TOPICS = [
  { key: "trace", label: "Requests", color: "#818cf8" },
  { key: "agent", label: "Agents", color: "#34d399" },
  { key: "step", label: "Steps", color: "#38bdf8" },
  { key: "tool", label: "Tools", color: "#f59e0b" },
  { key: "retriever", label: "Retrievers", color: "#a78bfa" },
  { key: "memory", label: "Memory", color: "#f472b6" },
  { key: "workflow", label: "Workflows", color: "#22d3ee" },
  { key: "evaluation", label: "Evaluations", color: "#fb7185" },
];

// Every broadcastable (non-heartbeat) event type. The SSE transport sets each
// event's name to its type, so the client must listen for these explicitly.
export const EVENT_TYPES = [
  "trace.started",
  "trace.updated",
  "trace.finished",
  "agent.started",
  "agent.finished",
  "step.started",
  "step.finished",
  "tool.started",
  "tool.finished",
  "retriever.started",
  "retriever.finished",
  "memory.started",
  "memory.finished",
  "workflow.updated",
  "evaluation.finished",
];

const TOPIC_COLOR = Object.fromEntries(TOPICS.map((t) => [t.key, t.color]));

export const topicOf = (type) => (type || "").split(".")[0];

export const colorForType = (type) => TOPIC_COLOR[topicOf(type)] || "#9ca3af";

// A short, human-readable summary of an event for the timeline / feed.
export function describeEvent(type, data = {}) {
  switch (type) {
    case "trace.started":
      return `Request #${data.trace_id} started (${data.model_name || "model"})`;
    case "trace.updated":
      return `Request #${data.trace_id} updated`;
    case "trace.finished":
      return `Request #${data.trace_id} ${data.status || "finished"}`;
    case "agent.started":
      return `Agent "${data.agent_name}" started`;
    case "agent.finished":
      return `Agent "${data.agent_name}" ${data.status || "finished"}`;
    case "step.started":
      return `Step ${data.name || data.step_type || ""} started`;
    case "step.finished":
      return `Step ${data.step_type || ""} ${data.status || "finished"}`;
    case "tool.started":
      return `Tool "${data.tool_name}" called`;
    case "tool.finished":
      return `Tool "${data.tool_name}" ${data.status || "finished"}`;
    case "retriever.started":
      return "Retrieval started";
    case "retriever.finished":
      return `Retrieval finished (${data.num_documents ?? 0} docs)`;
    case "memory.started":
      return "Memory lookup started";
    case "memory.finished":
      return `Memory lookup ${data.used ? "used" : "finished"}`;
    case "workflow.updated":
      return `Conversation #${data.conversation_run_id} ${data.phase || data.status || "updated"}`;
    case "evaluation.finished":
      return `Evaluation #${data.evaluation_run_id} finished (${
        data.overall_score != null ? data.overall_score : "n/a"
      })`;
    default:
      return type;
  }
}
