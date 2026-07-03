"""Shared pytest fixtures: reset the global tracer between tests."""
import pytest

import agentscope
from agentscope import trace


@pytest.fixture(autouse=True)
def fresh_tracer():
    """Give every test a clean, local-only tracer (no network/console)."""
    agentscope.configure(
        enabled=True,
        endpoint=None,
        api_key=None,
        console=False,
        log=False,
        default_model=None,
    )
    trace.clear()
    yield
    trace.clear()
