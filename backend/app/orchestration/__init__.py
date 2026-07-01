"""Multi-Agent SDK (v0.4).

A thin, lightweight orchestration layer over the v0.4 workflow models and the
v0.2 :class:`~app.utils.trace_recorder.TraceRecorder`. Business logic and all
persistence live in :mod:`app.services.workflow_service`; this package only
orchestrates.

    from app.orchestration import AgentOrchestrator

    orchestrator = AgentOrchestrator()
    planner = orchestrator.create_agent(name="Planner", role="planner")
    researcher = orchestrator.create_agent(name="Researcher", role="researcher")
    planner.send(researcher, message="Research LangSmith.")
    planner.execute()
    researcher.execute()
    orchestrator.finish()
"""
from .agent import Agent
from .context import AgentContext
from .orchestrator import AgentOrchestrator
from .registry import AgentRegistry

__all__ = ["AgentOrchestrator", "Agent", "AgentContext", "AgentRegistry"]
