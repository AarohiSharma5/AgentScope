"""Plugin system (v0.6): extend the platform without touching the core.

Public surface:

* :class:`PluginBase` / :class:`PluginMetadata` — author a plugin.
* :class:`Capability` — the six extension categories.
* :class:`PluginRegistry` / :data:`plugin_registry` — look up contributions.
* :class:`PluginManager` / :data:`plugin_manager` — drive the lifecycle.
* :class:`PluginLoader` — discover plugins (modules/packages/dirs/entry points).
* :func:`init_plugins` — wire discovery + install + enable into the app factory.
"""
import logging

from .base import (
    ALL_CAPABILITIES,
    Capability,
    Contribution,
    DuplicatePluginError,
    PluginBase,
    PluginContext,
    PluginDependencyError,
    PluginError,
    PluginMetadata,
    PluginNotFoundError,
    PluginState,
    PluginStateError,
    PluginValidationError,
    discovered_plugin_classes,
)
from .loader import DEFAULT_ENTRY_POINT_GROUP, PluginLoader
from .manager import PluginManager, PluginRecord, plugin_manager
from .registry import PluginRegistry, plugin_registry

logger = logging.getLogger("agentscope")

__all__ = [
    "ALL_CAPABILITIES",
    "Capability",
    "Contribution",
    "DuplicatePluginError",
    "PluginBase",
    "PluginContext",
    "PluginDependencyError",
    "PluginError",
    "PluginLoader",
    "PluginManager",
    "PluginMetadata",
    "PluginNotFoundError",
    "PluginRecord",
    "PluginRegistry",
    "PluginState",
    "PluginStateError",
    "PluginValidationError",
    "discovered_plugin_classes",
    "init_plugins",
    "plugin_manager",
    "plugin_registry",
]


def init_plugins(app) -> None:
    """Discover, install and enable plugins according to app config.

    Idempotent and resilient: safe to call on every app creation (skips already
    installed plugins, normalizes discovered plugins to enabled) and never
    raises — a plugin failure is logged and the app still boots.

    Config keys (all optional):
      * ``PLUGINS_AUTOLOAD`` (bool, default True)
      * ``PLUGINS_PACKAGES`` (list[str], default ``["app.plugins.builtins"]``)
      * ``PLUGINS_DIRECTORIES`` (list[str], default ``[]``)
      * ``PLUGINS_MODULES`` (list[str], default ``[]``)
      * ``PLUGINS_ENTRYPOINT_GROUP`` (str|None, default ``"agentscope.plugins"``)
    """
    if not app.config.get("PLUGINS_AUTOLOAD", True):
        logger.info("plugin autoload disabled (PLUGINS_AUTOLOAD=False)")
        return
    try:
        loader = PluginLoader()
        loader.discover(
            packages=app.config.get("PLUGINS_PACKAGES", ["app.plugins.builtins"]),
            directories=app.config.get("PLUGINS_DIRECTORIES", []),
            modules=app.config.get("PLUGINS_MODULES", []),
            entry_point_group=app.config.get(
                "PLUGINS_ENTRYPOINT_GROUP", DEFAULT_ENTRY_POINT_GROUP
            ),
        )
        plugin_manager.install_all()
        plugin_manager.enable_all()
        logger.info(
            "plugins ready: %s installed",
            len(plugin_manager.list_plugins()),
        )
    except Exception:  # noqa: BLE001 - never let plugins break app startup
        logger.exception("plugin initialization failed")
