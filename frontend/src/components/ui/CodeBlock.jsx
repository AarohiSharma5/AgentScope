export default function CodeBlock({ value }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-gray-600">—</span>;
  }
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-ink-500 bg-ink-800 p-3 font-mono text-xs text-gray-300">
      {text}
    </pre>
  );
}
