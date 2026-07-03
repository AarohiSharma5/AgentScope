"""``PluginRegistry`` — the runtime lookup surface for plugin contributions.

Only **enabled** plugins have contributions here. The rest of the platform asks
the registry for extensions by capability + name (e.g. ``get_evaluator("bleu")``)
instead of importing providers directly — this is what keeps the platform free
of hardcoded providers. Lifecycle/ownership is managed by :class:`PluginManager`.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .base import ALL_CAPABILITIES, Capability, Contribution, PluginError

logger = logging.getLogger("agentscope")


class PluginRegistry:
    """Thread-safe store of contributions, indexed by capability then name."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_capability: dict[str, dict[str, Contribution]] = {
            capability: {} for capability in ALL_CAPABILITIES
        }

    # -- Mutation ----------------------------------------------------------

    def add_contribution(self, contribution: Contribution) -> None:
        """Register one contribution (called via :class:`PluginContext`)."""
        if contribution.capability not in self._by_capability:
            raise PluginError(f"unknown capability: {contribution.capability!r}")
        with self._lock:
            bucket = self._by_capability[contribution.capability]
            existing = bucket.get(contribution.name)
            if existing is not None and existing.plugin != contribution.plugin:
                raise PluginError(
                    f"{contribution.capability} '{contribution.name}' already "
                    f"provided by plugin '{existing.plugin}'"
                )
            bucket[contribution.name] = contribution
        logger.debug(
            "registered %s '%s' from plugin '%s'",
            contribution.capability, contribution.name, contribution.plugin,
        )

    def remove_plugin(self, plugin_name: str) -> int:
        """Withdraw every contribution owned by ``plugin_name``. Returns count."""
        removed = 0
        with self._lock:
            for bucket in self._by_capability.values():
                for name in [n for n, c in bucket.items() if c.plugin == plugin_name]:
                    del bucket[name]
                    removed += 1
        if removed:
            logger.debug("withdrew %s contribution(s) from plugin '%s'", removed, plugin_name)
        return removed

    # -- Lookup ------------------------------------------------------------

    def get(self, capability: str, name: str) -> Optional[Any]:
        """Return the contributed object for ``capability``/``name``, or None."""
        with self._lock:
            contribution = self._by_capability.get(capability, {}).get(name)
            return contribution.obj if contribution else None

    def get_contribution(self, capability: str, name: str) -> Optional[Contribution]:
        with self._lock:
            return self._by_capability.get(capability, {}).get(name)

    def list(self, capability: str) -> dict[str, Any]:
        """Return ``{name: obj}`` for a capability (a copy, safe to iterate)."""
        with self._lock:
            return {name: c.obj for name, c in self._by_capability.get(capability, {}).items()}

    def names(self, capability: str) -> list[str]:
        with self._lock:
            return sorted(self._by_capability.get(capability, {}))

    def all_contributions(self) -> list[Contribution]:
        with self._lock:
            return [c for bucket in self._by_capability.values() for c in bucket.values()]

    def clear(self) -> None:
        """Remove all contributions (primarily for tests)."""
        with self._lock:
            for bucket in self._by_capability.values():
                bucket.clear()

    # -- Typed convenience accessors --------------------------------------

    def get_tool(self, name: str) -> Optional[Any]:
        return self.get(Capability.TOOL, name)

    def get_evaluator(self, name: str) -> Optional[Any]:
        return self.get(Capability.EVALUATOR, name)

    def get_memory(self, name: str) -> Optional[Any]:
        return self.get(Capability.MEMORY, name)

    def get_retriever(self, name: str) -> Optional[Any]:
        return self.get(Capability.RETRIEVER, name)

    def get_llm_provider(self, name: str) -> Optional[Any]:
        return self.get(Capability.LLM_PROVIDER, name)

    def get_ui_extension(self, name: str) -> Optional[Any]:
        return self.get(Capability.UI_EXTENSION, name)

    def list_tools(self) -> dict[str, Any]:
        return self.list(Capability.TOOL)

    def list_evaluators(self) -> dict[str, Any]:
        return self.list(Capability.EVALUATOR)

    def list_memories(self) -> dict[str, Any]:
        return self.list(Capability.MEMORY)

    def list_retrievers(self) -> dict[str, Any]:
        return self.list(Capability.RETRIEVER)

    def list_llm_providers(self) -> dict[str, Any]:
        return self.list(Capability.LLM_PROVIDER)

    def list_ui_extensions(self) -> dict[str, Any]:
        return self.list(Capability.UI_EXTENSION)


#: Process-wide default registry.
plugin_registry = PluginRegistry()
