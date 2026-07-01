import EmptyState from "../ui/EmptyState.jsx";
import { fmtLatency, fmtTime } from "../../lib/format.js";

// Color accent per message type.
const TYPE_STYLE = {
  instruction: "text-indigo-300",
  question: "text-sky-300",
  answer: "text-emerald-300",
  observation: "text-violet-300",
  critique: "text-rose-300",
  tool_result: "text-amber-300",
  memory_result: "text-teal-300",
};

// A single chat bubble. Messages sent by the "primary" sender align right.
function Bubble({ message, alignRight }) {
  const typeClass = TYPE_STYLE[message.message_type] || "text-gray-300";
  return (
    <div className={`flex ${alignRight ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[75%]">
        <div
          className={`mb-1 flex items-center gap-2 text-xs text-gray-500 ${
            alignRight ? "justify-end" : "justify-start"
          }`}
        >
          <span className="font-medium text-gray-400">{message.sender || "—"}</span>
          <span aria-hidden>→</span>
          <span>{message.receiver || "broadcast"}</span>
        </div>
        <div
          className={`rounded-2xl border px-4 py-2.5 ${
            alignRight
              ? "rounded-tr-sm border-accent/30 bg-accent/10"
              : "rounded-tl-sm border-ink-500 bg-ink-700"
          }`}
        >
          <div className={`mb-1 text-[10px] font-medium uppercase tracking-wider ${typeClass}`}>
            {message.message_type}
            {message.reply_to_id && (
              <span className="ml-2 text-gray-500">↳ reply to #{message.reply_to_id}</span>
            )}
          </div>
          <p className="whitespace-pre-wrap break-words text-sm text-gray-200">
            {message.content || <span className="text-gray-600">(no content)</span>}
          </p>
        </div>
        <div
          className={`mt-1 flex gap-3 text-[11px] text-gray-500 ${
            alignRight ? "justify-end" : "justify-start"
          }`}
        >
          <span>{fmtTime(message.timestamp)}</span>
          {message.latency_ms != null && (
            <span className="font-mono">{fmtLatency(message.latency_ms)}</span>
          )}
          {message.token_usage?.total != null && (
            <span className="font-mono">{message.token_usage.total} tok</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MessageViewer({ messages }) {
  if (!messages || messages.length === 0) {
    return <EmptyState message="No messages exchanged in this conversation." />;
  }
  // Right-align messages from the earliest sender for a chat-like feel.
  const primary = messages[0].sender_node_id;
  return (
    <div className="space-y-4 rounded-xl border border-ink-500 bg-ink-800/50 p-4">
      {messages.map((m) => (
        <Bubble key={m.id} message={m} alignRight={m.sender_node_id === primary} />
      ))}
    </div>
  );
}
