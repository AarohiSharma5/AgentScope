import EmptyState from "../ui/EmptyState.jsx";

// Recursively render a node into ASCII-tree lines with proper guides.
function renderNode(node, prefix, isLast, isRoot, key) {
  const connector = isRoot ? "" : isLast ? "└── " : "├── ";
  const line = (
    <div key={key} className="whitespace-pre font-mono text-sm leading-6">
      <span className="text-gray-600">
        {prefix}
        {connector}
      </span>
      <span className="text-gray-200">{node.label}</span>
      {node.meta != null && (
        <span className="ml-2 text-xs text-gray-500">{node.meta}</span>
      )}
    </div>
  );

  const childPrefix = prefix + (isRoot ? "" : isLast ? "    " : "│   ");
  const children = node.children || [];
  const childLines = children.map((child, i) =>
    renderNode(child, childPrefix, i === children.length - 1, false, `${key}-${i}`)
  );

  return [line, ...childLines];
}

export default function ExecutionTree({ root }) {
  if (!root || !(root.children && root.children.length)) {
    return <EmptyState message="No execution tree available for this run." />;
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-800 p-4">
      {renderNode(root, "", true, true, "root")}
    </div>
  );
}
