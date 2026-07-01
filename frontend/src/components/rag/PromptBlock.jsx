import { useState } from "react";

// Lightweight, dependency-free "syntax" highlighting for prompt text:
// - a leading role label (System:, User:, Assistant:, Tool:, Context:, Memory:)
// - {placeholder} / {{template}} / [bracket] tokens
const ROLE_RE = /^(\s*)(system|user|assistant|human|ai|tool|function|context|memory)(\s*[:>\-])/i;
const TOKEN_RE = /(\{\{[^}]*\}\}|\{[^}]*\}|\[[^\]]*\])/g;

function highlightInline(text, keyPrefix) {
  const parts = text.split(TOKEN_RE);
  return parts.map((part, i) => {
    if (!part) return null;
    if (i % 2 === 1) {
      return (
        <span key={`${keyPrefix}-t${i}`} className="text-amber-300">
          {part}
        </span>
      );
    }
    return <span key={`${keyPrefix}-s${i}`}>{part}</span>;
  });
}

function highlightLine(line, key) {
  const match = line.match(ROLE_RE);
  if (match) {
    const [, lead, role, tail] = match;
    const rest = line.slice(match[0].length);
    return (
      <span key={key}>
        {lead}
        <span className="font-semibold text-accent">{role}</span>
        <span className="text-gray-500">{tail}</span>
        {highlightInline(rest, key)}
      </span>
    );
  }
  return <span key={key}>{highlightInline(line, key)}</span>;
}

function Highlighted({ text }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <div key={i}>
          {highlightLine(line, `l${i}`) || "\u00a0"}
        </div>
      ))}
    </>
  );
}

export default function PromptBlock({
  label,
  text,
  tokens,
  open,
  onToggle,
  accent = false,
}) {
  const [internalOpen, setInternalOpen] = useState(true);
  const [copied, setCopied] = useState(false);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : internalOpen;
  const hasText = text != null && text !== "";

  const toggle = () => (isControlled ? onToggle?.() : setInternalOpen((v) => !v));

  const copy = async () => {
    if (!hasText) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable; no-op */
    }
  };

  return (
    <div
      className={`overflow-hidden rounded-xl border bg-ink-700 ${
        accent ? "border-accent/40" : "border-ink-500"
      }`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-ink-500 bg-ink-600/60 px-4 py-2">
        <button
          onClick={toggle}
          className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-gray-400 hover:text-gray-200"
        >
          <span
            className={`inline-block transition-transform ${isOpen ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          {label}
          {tokens != null && (
            <span className="rounded-md bg-ink-500 px-1.5 py-0.5 font-mono text-[10px] normal-case text-gray-400">
              {tokens} tok
            </span>
          )}
        </button>
        <button
          onClick={copy}
          disabled={!hasText}
          className="rounded-md border border-ink-500 px-2 py-1 text-xs text-gray-400 transition-colors enabled:hover:bg-ink-500 enabled:hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {isOpen && (
        <div className="px-4 py-3">
          {hasText ? (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-gray-300">
              <Highlighted text={text} />
            </pre>
          ) : (
            <p className="text-sm text-gray-600">Not provided.</p>
          )}
        </div>
      )}
    </div>
  );
}
