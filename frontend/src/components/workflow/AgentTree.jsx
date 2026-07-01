import AgentCard from "./AgentCard.jsx";
import EmptyState from "../ui/EmptyState.jsx";

// Recursively render the agent tree as indented AgentCards connected by guides.
function TreeNode({ node, depth, selectedId, onSelect }) {
  const children = node.children || [];
  return (
    <div className={depth > 0 ? "border-l border-ink-500 pl-4" : ""}>
      <AgentCard
        node={node}
        selected={selectedId === node.id}
        onSelect={onSelect}
      />
      {children.length > 0 && (
        <div className="mt-3 space-y-3">
          {children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function AgentTree({ tree, selectedId, onSelect }) {
  if (!tree || tree.length === 0) {
    return <EmptyState message="No agents in this conversation." />;
  }
  return (
    <div className="space-y-3">
      {tree.map((root) => (
        <TreeNode
          key={root.id}
          node={root}
          depth={0}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
