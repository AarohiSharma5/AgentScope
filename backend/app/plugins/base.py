"""Core plugin contracts: metadata, capabilities, lifecycle base class.

A plugin is any subclass of :class:`PluginBase` that declares a
:class:`PluginMetadata`. Defining such a subclass **automatically registers**
its class for discovery (via ``__init_subclass__``) — importing a plugin module
is all it takes to make the plugin installable, so there are no hardcoded
provider lists anywhere.

Plugins contribute extensions (tools, evaluators, memories, retrievers, LLM
providers, UI extensions) by implementing :meth:`PluginBase.register` and
calling the ``register_*`` methods on the :class:`PluginContext` handed to them
when they are enabled.
"""
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # avoid a runtime import cycle with registry.py
    from .registry import PluginRegistry

logger = logging.getLogger("agentscope")


# -- Exceptions -------------------------------------------------------------


class PluginError(Exception):
    """Base class for all plugin-system errors."""


class PluginValidationError(PluginError):
    """Raised when plugin metadata is missing or malformed."""


class PluginNotFoundError(PluginError):
    """Raised when an operation targets an unknown plugin."""


class DuplicatePluginError(PluginError):
    """Raised when installing a plugin whose name is already installed."""


class PluginDependencyError(PluginError):
    """Raised when a plugin's declared dependencies are unmet."""


class PluginStateError(PluginError):
    """Raised on an illegal lifecycle transition."""


# -- Capabilities & lifecycle states ---------------------------------------


class Capability:
    """The extension categories a plugin may contribute to."""

    TOOL = "tool"
    EVALUATOR = "evaluator"
    MEMORY = "memory"
    RETRIEVER = "retriever"
    LLM_PROVIDER = "llm_provider"
    UI_EXTENSION = "ui_extension"


ALL_CAPABILITIES = frozenset(
    v for k, v in vars(Capability).items() if k.isupper() and isinstance(v, str)
)


class PluginState:
    """Lifecycle states a plugin moves through."""

    INSTALLED = "installed"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


# -- Metadata ---------------------------------------------------------------


@dataclass
class PluginMetadata:
    """Declarative description of a plugin.

    ``dependencies`` are other **plugins** (by name, optionally version-pinned,
    e.g. ``"sample-tools>=1.0"``); ``requires`` are external **Python packages**
    checked against the installed environment.
    """

    name: str
    version: str
    author: Optional[str] = None
    description: Optional[str] = None
    capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    homepage: Optional[str] = None
    license: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Raise :class:`PluginValidationError` if the metadata is unusable."""
        if not self.name or not isinstance(self.name, str):
            raise PluginValidationError("plugin metadata requires a non-empty 'name'")
        if not self.version or not isinstance(self.version, str):
            raise PluginValidationError(f"plugin '{self.name}' requires a 'version'")
        unknown = set(self.capabilities) - ALL_CAPABILITIES
        if unknown:
            raise PluginValidationError(
                f"plugin '{self.name}' declares unknown capabilities: {sorted(unknown)}"
            )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "dependencies": list(self.dependencies),
            "requires": list(self.requires),
            "homepage": self.homepage,
            "license": self.license,
            "tags": list(self.tags),
        }


# -- Contribution & context -------------------------------------------------


@dataclass
class Contribution:
    """A single extension registered by a plugin into the registry."""

    capability: str
    name: str
    obj: Any
    plugin: str
    metadata: dict = field(default_factory=dict)


class PluginContext:
    """Handed to :meth:`PluginBase.register`; records contributions by owner.

    Every ``register_*`` call is attributed to the owning plugin so the whole
    contribution set can be withdrawn atomically on disable/uninstall.
    """

    def __init__(self, registry: "PluginRegistry", plugin_name: str) -> None:
        self._registry = registry
        self._plugin_name = plugin_name

    def _add(self, capability: str, name: str, obj: Any, **metadata) -> None:
        self._registry.add_contribution(
            Contribution(
                capability=capability,
                name=name,
                obj=obj,
                plugin=self._plugin_name,
                metadata=metadata,
            )
        )

    def register_tool(self, name: str, tool: Any, **metadata) -> None:
        """Contribute a callable tool discoverable by ``name``."""
        self._add(Capability.TOOL, name, tool, **metadata)

    def register_evaluator(self, name: str, evaluator: Any, **metadata) -> None:
        """Contribute an evaluator (an ``app.evaluation.evaluators.Evaluator``)."""
        self._add(Capability.EVALUATOR, name, evaluator, **metadata)

    def register_memory(self, name: str, memory: Any, **metadata) -> None:
        """Contribute a memory backend/callable."""
        self._add(Capability.MEMORY, name, memory, **metadata)

    def register_retriever(self, name: str, retriever: Any, **metadata) -> None:
        """Contribute a retriever (e.g. an ``EmbeddingProvider``/``VectorStore``)."""
        self._add(Capability.RETRIEVER, name, retriever, **metadata)

    def register_llm_provider(self, name: str, provider: Any, **metadata) -> None:
        """Contribute an LLM provider callable/adapter."""
        self._add(Capability.LLM_PROVIDER, name, provider, **metadata)

    def register_ui_extension(self, name: str, descriptor: dict, **metadata) -> None:
        """Contribute a UI-extension descriptor (JSON the frontend can consume)."""
        self._add(Capability.UI_EXTENSION, name, descriptor, **metadata)


# -- Auto-registration discovery table --------------------------------------

_DISCOVERED: dict[str, type] = {}


def register_plugin_class(cls: type) -> None:
    """Record a concrete plugin class for discovery (called automatically)."""
    metadata = getattr(cls, "metadata", None)
    if not isinstance(metadata, PluginMetadata):
        return
    _DISCOVERED[metadata.name] = cls
    logger.debug("discovered plugin class %s (%s)", cls.__name__, metadata.name)


def discovered_plugin_classes() -> dict[str, type]:
    """A snapshot of all auto-discovered plugin classes, keyed by plugin name."""
    return dict(_DISCOVERED)


def clear_discovered() -> None:
    """Clear the discovery table (primarily for tests)."""
    _DISCOVERED.clear()


# -- Plugin base class ------------------------------------------------------


class PluginBase:
    """Base class for all plugins.

    Subclasses set a class-level :attr:`metadata` and override :meth:`register`
    plus any lifecycle hooks they care about. Defining a subclass with concrete
    metadata registers it for discovery automatically.

    Set ``abstract = True`` on an intermediate subclass to opt it out of
    discovery (useful for shared plugin base classes).
    """

    #: Concrete subclasses MUST override this with a PluginMetadata instance.
    metadata: PluginMetadata = None  # type: ignore[assignment]
    #: Intermediate base classes set this True to skip auto-registration.
    abstract: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "abstract", False):
            return
        register_plugin_class(cls)

    # -- Contribution ------------------------------------------------------

    def register(self, context: PluginContext) -> None:
        """Register this plugin's contributions. Override in subclasses."""

    # -- Lifecycle hooks (all optional) ------------------------------------

    def on_install(self) -> None:
        """Called once when the plugin is installed."""

    def on_load(self) -> None:
        """Called when the plugin is loaded (instantiated)."""

    def on_enable(self) -> None:
        """Called when the plugin is enabled (after contributions register)."""

    def on_disable(self) -> None:
        """Called when the plugin is disabled (after contributions withdraw)."""

    def on_uninstall(self) -> None:
        """Called when the plugin is uninstalled."""

    def on_reload(self) -> None:
        """Called after the plugin is reloaded."""
