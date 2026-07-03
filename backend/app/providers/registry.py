"""``ProviderRegistry`` — discover and instantiate providers by name.

Adapters register their **class** here (via :func:`register_provider`), so the
platform can enumerate providers and their capabilities without instantiating
them (no credentials needed for discovery) and construct a configured instance
on demand. Adding a provider is just defining + registering an adapter — no core
code changes.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from .base import Provider, ProviderInfo, ProviderNotFoundError

logger = logging.getLogger("agentscope")


class ProviderRegistry:
    """Thread-safe registry of provider classes keyed by ``name``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, type[Provider]] = {}

    def register(self, provider_cls: type[Provider]) -> type[Provider]:
        """Register a provider class. Usable as a decorator."""
        name = getattr(provider_cls, "name", None)
        if not name or name == "provider":
            raise ValueError(f"provider class {provider_cls.__name__} must define a unique 'name'")
        with self._lock:
            self._providers[name] = provider_cls
        logger.debug("registered provider '%s' (%s)", name, provider_cls.__name__)
        return provider_cls

    def unregister(self, name: str) -> None:
        with self._lock:
            self._providers.pop(name, None)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._providers

    def get_class(self, name: str) -> type[Provider]:
        with self._lock:
            if name not in self._providers:
                raise ProviderNotFoundError(f"no provider named '{name}'")
            return self._providers[name]

    def names(self, kind: Optional[str] = None) -> list[str]:
        with self._lock:
            items = self._providers.items()
            return sorted(n for n, cls in items if kind is None or cls.kind == kind)

    def create(self, name: str, **config) -> Provider:
        """Instantiate a configured provider by name."""
        return self.get_class(name)(**config)

    def info(self, name: str) -> ProviderInfo:
        """Static description of one provider (no instantiation)."""
        return self._describe_class(self.get_class(name))

    def describe(self, kind: Optional[str] = None, capability: Optional[str] = None) -> list[dict]:
        """Return static descriptions of registered providers, optionally filtered."""
        with self._lock:
            classes = list(self._providers.values())
        result = []
        for cls in classes:
            if kind is not None and cls.kind != kind:
                continue
            if capability is not None and capability not in cls.capabilities:
                continue
            result.append(self._describe_class(cls).to_dict())
        return sorted(result, key=lambda d: d["name"])

    def by_capability(self, capability: str) -> list[str]:
        """Provider names that advertise ``capability``."""
        with self._lock:
            return sorted(n for n, cls in self._providers.items() if capability in cls.capabilities)

    def capabilities(self) -> dict[str, list[str]]:
        """Map each capability to the providers that support it."""
        mapping: dict[str, list[str]] = {}
        with self._lock:
            for name, cls in self._providers.items():
                for capability in cls.capabilities:
                    mapping.setdefault(capability, []).append(name)
        return {cap: sorted(names) for cap, names in sorted(mapping.items())}

    @staticmethod
    def _describe_class(cls: type[Provider]) -> ProviderInfo:
        return ProviderInfo(
            name=cls.name,
            kind=cls.kind,
            capabilities=sorted(cls.capabilities),
            models=list(cls.models),
            default_model=cls.default_model,
            requires_api_key=cls.requires_api_key,
            api_key_env=cls.api_key_env,
        )

    def clear(self) -> None:
        with self._lock:
            self._providers.clear()


#: Process-wide default registry.
provider_registry = ProviderRegistry()


def register_provider(provider_cls: type[Provider]) -> type[Provider]:
    """Register a provider class with the default registry (decorator-friendly)."""
    return provider_registry.register(provider_cls)
