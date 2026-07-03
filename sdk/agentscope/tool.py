"""The :class:`Tool` — a traced, callable wrapper around a function.

A tool records each invocation as a ``tool`` span (arguments in, result out),
nested under whatever agent/workflow span is active.

Usage
-----
    from agentscope import Tool

    # Decorator form
    @Tool(description="Look something up on the web")
    def search(query: str) -> list: ...

    search("agentscope")          # traced automatically

    # Wrapper form
    calc = Tool(lambda a, b: a + b, name="add")
    calc.invoke(2, 3)
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from .api import SpanScope
from .errors import ConfigurationError
from .span import SpanKind


class Tool:
    """A callable, automatically-traced tool."""

    def __init__(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **attributes: Any,
    ):
        self._func = func
        self._explicit_name = name
        self.name = name or (getattr(func, "__name__", None) or "tool")
        self.description = description or (inspect.getdoc(func) if func else None)
        self.attributes = attributes

    def __call__(self, *args, **kwargs):
        # Decorator form: @Tool(...) applied to a function registers it.
        if self._func is None and len(args) == 1 and not kwargs and callable(args[0]):
            func = args[0]
            self._func = func
            if self._explicit_name is None:
                self.name = getattr(func, "__name__", self.name)
            if self.description is None:
                self.description = inspect.getdoc(func)
            return self
        return self.invoke(*args, **kwargs)

    def invoke(self, *args, **kwargs):
        """Execute the wrapped function inside a ``tool`` span."""
        if self._func is None:
            raise ConfigurationError(
                f"Tool '{self.name}' has no function; pass one to Tool(...) or use it as a decorator."
            )
        attrs = dict(self.attributes)
        if self.description:
            attrs.setdefault("description", self.description)
        payload = _arguments(args, kwargs)
        with SpanScope(self.name, SpanKind.TOOL, attrs, input=payload) as span:
            result = self._func(*args, **kwargs)
            span.set_output(result)
            return result

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"


def _arguments(args, kwargs) -> Any:
    """Represent a call's arguments for the span input."""
    if args and kwargs:
        return {"args": list(args), "kwargs": kwargs}
    if args:
        return args[0] if len(args) == 1 else list(args)
    return kwargs or None
