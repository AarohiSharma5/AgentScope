"""The :class:`Workflow` — compose steps into a single traced execution.

A workflow runs its steps in order (with optional parallel groups), threading
each step's output into the next. The whole run is a ``workflow`` span; each
step nests beneath it. Steps may be plain callables, :class:`~agentscope.Agent`
instances, :class:`~agentscope.Tool` instances, or ``@trace``-decorated
functions.

Usage
-----
    from agentscope import Workflow

    wf = Workflow("rag-pipeline")
    wf.add(retrieve).add(generate).add(review)

    # or with the decorator form
    @wf.step
    def retrieve(q): ...

    # parallel fan-out
    wf.parallel(research_a, research_b, research_c)

    answer = wf.run("What is AgentScope?")
"""
from __future__ import annotations

import concurrent.futures
import contextvars
from typing import Any, Callable, List, Optional, Union

from .agent import Agent
from .api import SpanScope
from .span import SpanKind
from .tool import Tool

Step = Union[Callable, Agent, Tool]


def _target_name(target: Step) -> str:
    if isinstance(target, (Agent, Tool)):
        return target.name
    return getattr(target, "__name__", None) or "step"


def _invoke(target: Step, data: Any, fallback_name: str) -> Any:
    """Execute one step, ensuring it is represented by a span."""
    if isinstance(target, Agent):
        return target.run(data)
    if isinstance(target, Tool):
        return target.invoke(data)
    if getattr(target, "__agentscope_traced__", False):
        # Already opens its own span when called.
        return target(data)
    with SpanScope(fallback_name, SpanKind.STEP, {}, input=data) as span:
        result = target(data)
        span.set_output(result)
        return result


class _Step:
    """A single sequential workflow step."""

    def __init__(self, target: Step, name: Optional[str] = None):
        self.target = target
        self.name = name or _target_name(target)

    def execute(self, data: Any) -> Any:
        return _invoke(self.target, data, self.name)


class _ParallelStep:
    """A fan-out group whose targets run concurrently on copied contexts."""

    def __init__(self, targets: List[Step], name: str = "parallel"):
        self.substeps = [_Step(t) for t in targets]
        self.name = name

    def execute(self, data: Any) -> List[Any]:
        results: List[Any] = [None] * len(self.substeps)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.substeps)) as pool:
            futures = {}
            for index, step in enumerate(self.substeps):
                # Copy the current context so each thread sees the workflow span
                # as its parent, keeping the span tree correct across threads.
                ctx = contextvars.copy_context()
                futures[pool.submit(ctx.run, step.execute, data)] = index
            for future in concurrent.futures.as_completed(futures):
                results[futures[future]] = future.result()
        return results


class Workflow:
    """An ordered pipeline of steps, executed as a single traced run."""

    def __init__(self, name: str, *, metadata: Optional[dict] = None):
        self.name = name
        self.metadata = dict(metadata or {})
        self._steps: List[Any] = []

    # -- composition --------------------------------------------------------

    def add(self, target: Step, name: Optional[str] = None) -> "Workflow":
        """Append a sequential step. Returns ``self`` for chaining."""
        self._steps.append(_Step(target, name=name))
        return self

    def parallel(self, *targets: Step, name: str = "parallel") -> "Workflow":
        """Append a group of steps that run concurrently and yield a list."""
        if not targets:
            raise ValueError("parallel() requires at least one step")
        self._steps.append(_ParallelStep(list(targets), name=name))
        return self

    def step(self, func: Optional[Callable] = None, *, name: Optional[str] = None):
        """Decorator that appends the decorated function as a step."""
        if func is None:
            def decorator(f):
                self.add(f, name=name)
                return f
            return decorator
        self.add(func, name=name)
        return func

    # -- execution ----------------------------------------------------------

    def run(self, input: Any = None) -> Any:  # noqa: A002 - public API
        """Execute every step in order, threading output → input."""
        attributes = {**self.metadata, "steps": [s.name for s in self._steps]}
        with SpanScope(self.name, SpanKind.WORKFLOW, attributes, input=input) as span:
            data = input
            for step in self._steps:
                data = step.execute(data)
            span.set_output(data)
            return data

    def __call__(self, input: Any = None) -> Any:  # noqa: A002 - convenience
        return self.run(input)

    def __repr__(self) -> str:
        return f"<Workflow name={self.name!r} steps={len(self._steps)}>"
