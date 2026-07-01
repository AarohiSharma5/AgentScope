// Build an execution-tree structure from an agent-run detail payload.
// Shape: { label, meta?, children?: [...] } consumed by <ExecutionTree/>.
export function buildExecutionTree(detail) {
  if (!detail) return null;

  const steps = detail.steps || [];

  return {
    label: detail.agent_name || "Agent",
    meta: detail.agent_type || undefined,
    children: steps.map((step) => {
      const children = [];

      if (step.tool_executions?.length) {
        children.push({
          label: "Tool",
          children: step.tool_executions.map((t) => ({ label: t.tool_name })),
        });
      }
      if (step.memory_accesses?.length) {
        children.push({
          label: "Memory",
          children: step.memory_accesses.map((m) => ({
            label: m.memory_type || "memory",
          })),
        });
      }
      if (step.retriever_traces?.length) {
        children.push({
          label: "Retriever",
          children: step.retriever_traces.map((r) => ({
            label:
              r.num_documents != null ? `${r.num_documents} documents` : "retrieval",
          })),
        });
      }

      return {
        label: `#${step.step_number ?? "?"} ${step.name || step.step_type || "step"}`,
        meta: step.status,
        children,
      };
    }),
  };
}
