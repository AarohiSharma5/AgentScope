"""The :class:`Agent` — a named, traced unit of reasoning/work.

An agent wraps a handler function; every run is recorded as an ``agent`` span
carrying the agent's role, model and instructions. Tools invoked inside the
handler nest naturally beneath the agent span.

Usage
-----
    from agentscope import Agent

    planner = Agent("Planner", role="planner", model="gpt-4o")

    @planner
    def plan(question: str) -> str:
        ...

    plan("What is the revenue?")     # traced as an agent span
    planner.run("...")                # equivalent, via the stored handler

    # Manual scoping
    with planner.session(input="...") as span:
        span.set_output("done")
"""
from __future__ import annotations

import functools
from typing import Any, Callable, List, Optional

from .api import SpanScope, _wrap
from .errors import ConfigurationError
from .span import SpanKind
from .tool import Tool


class Agent:
    """A named agent that traces each run as an ``agent`` span."""

    def __init__(
        self,
        name: str,
        *,
        role: Optional[str] = None,
        model: Optional[str] = None,
        instructions: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        metadata: Optional[dict] = None,
        func: Optional[Callable] = None,
    ):
        self.name = name
        self.role = role
        self.model = model
        self.instructions = instructions
        self.tools: List[Tool] = list(tools or [])
        self.metadata = dict(metadata or {})
        self._func = func
        self._wrapped: Optional[Callable] = None

    # -- handler registration ----------------------------------------------

    def __call__(self, func: Callable) -> Callable:
        """Decorator: register ``func`` as this agent's handler.

        Returns a wrapped callable that traces every invocation as an agent span.
        """
        self._func = func
        self._wrapped = _wrap(func, name=self.name, kind=SpanKind.AGENT, attributes=self._attrs())
        functools.update_wrapper(self, func, updated=[])
        return self._wrapped

    def run(self, *args, **kwargs) -> Any:
        """Execute the registered handler inside an agent span."""
        if self._func is None:
            raise ConfigurationError(
                f"Agent '{self.name}' has no handler; decorate a function with @{self.name} "
                f"or pass func= to Agent(...)."
            )
        if self._wrapped is None:
            self._wrapped = _wrap(self._func, name=self.name, kind=SpanKind.AGENT, attributes=self._attrs())
        return self._wrapped(*args, **kwargs)

    def session(self, input: Any = None, **attributes) -> SpanScope:  # noqa: A002 - public API
        """Return a context manager scoping a manual agent span."""
        return SpanScope(self.name, SpanKind.AGENT, {**self._attrs(), **attributes}, input=input)

    # -- tools --------------------------------------------------------------

    def add_tool(self, tool: Tool) -> Tool:
        """Attach an existing :class:`Tool` to this agent."""
        self.tools.append(tool)
        return tool

    def tool(self, func: Optional[Callable] = None, *, name: Optional[str] = None, description: Optional[str] = None):
        """Decorator that creates a :class:`Tool` and attaches it to the agent."""
        if func is None:
            return functools.partial(self.tool, name=name, description=description)
        created = Tool(func, name=name, description=description)
        self.tools.append(created)
        return created

    # -- internals ----------------------------------------------------------

    def _attrs(self) -> dict:
        attrs = dict(self.metadata)
        if self.role is not None:
            attrs["role"] = self.role
        if self.model is not None:
            attrs["model"] = self.model
        if self.instructions is not None:
            attrs["instructions"] = self.instructions
        if self.tools:
            attrs["tools"] = [t.name for t in self.tools]
        return attrs

    def __repr__(self) -> str:
        return f"<Agent name={self.name!r} role={self.role!r}>"
