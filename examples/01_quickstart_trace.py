"""Quickstart: trace code three ways with the agentscope-lite SDK.

Runs standalone with no server — finished traces are collected in memory and
printed. Run it from the repo root:

    python examples/01_quickstart_trace.py

(With `pip install agentscope-lite` you would not need the sys.path shim below.)
"""
import os
import sys

# Allow running from the repo without installing the SDK.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import agentscope
from agentscope import trace
from agentscope.exporters import MemoryExporter


def main() -> None:
    memory = MemoryExporter()
    agentscope.configure(service_name="quickstart", console=True)
    trace.add_exporter(memory)

    # 1) Decorator — every call is traced automatically.
    @trace("generate", kind="llm", model="gpt-4o")
    def generate(prompt: str) -> str:
        return f"Answer to: {prompt}"

    generate("What is AgentScope?")

    # 2) Context manager — scope an arbitrary block and attach data.
    with trace("retrieval", kind="retriever") as span:
        docs = ["doc:a", "doc:b"]
        span.set_output(docs)

    # 3) Manual — full control over the span lifecycle.
    span = trace.start("generation", kind="llm", model="gpt-4o")
    span.set_output("Hello!").set_tokens(input=12, output=40).set_cost(0.001)
    trace.end(span)

    print("\nFinished traces:")
    for t in trace.finished():
        print(f"  {t.name:12} status={t.status} "
              f"latency_ms={t.latency_ms} tokens={t.total_tokens()} cost={t.total_cost()}")


if __name__ == "__main__":
    main()
