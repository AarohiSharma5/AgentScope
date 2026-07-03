"""Agents, Tools and Workflows with the agentscope-lite SDK.

Composes a small RAG-style pipeline: an agent that calls a tool, then a workflow
that runs steps sequentially and in parallel. Runs standalone (no server):

    python examples/02_agent_tool_workflow.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import agentscope
from agentscope import Agent, Tool, Workflow, trace


def main() -> None:
    agentscope.configure(service_name="agent-demo", console=True)

    # A tool is a traced, callable wrapper around a function.
    search = Tool(lambda q: [f"doc:{q}-1", f"doc:{q}-2"], name="search")

    # An agent is a named, traced unit of work that can call tools.
    planner = Agent("Planner", role="planner", model="gpt-4o")

    @planner
    def plan(question: str):
        return search(question)          # nested TOOL span, automatically

    # A workflow composes steps; each step's output feeds the next.
    wf = Workflow("rag-pipeline")
    wf.add(plan).add(lambda docs: f"answer built from {len(docs)} docs")

    answer = wf.run("What is AgentScope?")
    print("\nWorkflow result:", answer)

    # Fan-out: run independent tools concurrently (spans stay nested correctly).
    # Each branch receives the workflow input, so the tools accept one argument.
    parallel_wf = Workflow("fan-out")
    parallel_wf.parallel(
        Tool(lambda q: f"a:{q}", name="branch_a"),
        Tool(lambda q: f"b:{q}", name="branch_b"),
        Tool(lambda q: f"c:{q}", name="branch_c"),
    )
    parallel_wf.run("query")

    print("\nFinished traces:", [t.name for t in trace.finished()])


if __name__ == "__main__":
    main()
