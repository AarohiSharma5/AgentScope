"""Registry of the agents participating in a conversation.

Keeps insertion order and allows lookup by name, so the orchestrator (and user
code) can retrieve a collaborator without holding a direct reference.
"""
from typing import TYPE_CHECKING, Iterator, Optional

if TYPE_CHECKING:  # avoid a runtime import cycle with agent.py
    from .agent import Agent


class AgentRegistry:
    """An ordered collection of agents, indexed by name."""

    def __init__(self) -> None:
        self._agents: list["Agent"] = []
        self._by_name: dict[str, "Agent"] = {}

    def add(self, agent: "Agent") -> "Agent":
        """Register an agent. Names must be unique within a conversation."""
        if agent.name in self._by_name:
            raise ValueError(f"an agent named {agent.name!r} already exists")
        self._agents.append(agent)
        self._by_name[agent.name] = agent
        return agent

    def get(self, name: str) -> Optional["Agent"]:
        """Return the agent registered under ``name``, or None."""
        return self._by_name.get(name)

    def all(self) -> list["Agent"]:
        """Return all registered agents in insertion order."""
        return list(self._agents)

    def __iter__(self) -> Iterator["Agent"]:
        return iter(self._agents)

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __repr__(self) -> str:
        return f"<AgentRegistry agents={list(self._by_name)}>"
