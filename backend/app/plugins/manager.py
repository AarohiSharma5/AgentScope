"""``PluginManager`` — plugin lifecycle, dependency and version management.

Drives the full lifecycle — install, load, enable, disable, uninstall, reload —
over plugins discovered via auto-registration (see :mod:`app.plugins.base`).
Enabling a plugin verifies its declared plugin dependencies (name + version) and
its external Python-package requirements, then routes its contributions into a
:class:`~app.plugins.registry.PluginRegistry`. Disabling/uninstalling withdraws
them. Nothing about which providers exist is hardcoded here.
"""
import importlib
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional, Union

from .base import (
    DuplicatePluginError,
    PluginBase,
    PluginContext,
    PluginDependencyError,
    PluginMetadata,
    PluginNotFoundError,
    PluginState,
    PluginValidationError,
    discovered_plugin_classes,
)
from .registry import PluginRegistry, plugin_registry
from .versioning import Requirement

logger = logging.getLogger("agentscope")

PluginLike = Union[str, type, PluginBase]


@dataclass
class PluginRecord:
    """Bookkeeping for one managed plugin."""

    name: str
    cls: type
    metadata: PluginMetadata
    instance: Optional[PluginBase] = None
    state: str = PluginState.INSTALLED
    module: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        data = self.metadata.to_dict()
        data.update({"state": self.state, "module": self.module, "error": self.error})
        return data


class PluginManager:
    """Manages the lifecycle of a set of plugins against a registry."""

    def __init__(self, registry: Optional[PluginRegistry] = None) -> None:
        self.registry = registry or plugin_registry
        self._records: dict[str, PluginRecord] = {}
        self._lock = threading.RLock()

    # -- Resolution --------------------------------------------------------

    @staticmethod
    def _resolve(plugin: PluginLike) -> tuple[type, Optional[PluginBase], PluginMetadata]:
        """Resolve name/class/instance -> (class, instance_or_None, metadata)."""
        if isinstance(plugin, str):
            discovered = discovered_plugin_classes()
            if plugin not in discovered:
                raise PluginNotFoundError(f"no discovered plugin named '{plugin}'")
            cls = discovered[plugin]
            instance = None
        elif isinstance(plugin, PluginBase):
            cls, instance = type(plugin), plugin
        elif isinstance(plugin, type) and issubclass(plugin, PluginBase):
            cls, instance = plugin, None
        else:
            raise PluginValidationError(f"cannot resolve plugin from {plugin!r}")

        metadata = getattr(cls, "metadata", None)
        if not isinstance(metadata, PluginMetadata):
            raise PluginValidationError(f"plugin class {cls.__name__} has no PluginMetadata")
        metadata.validate()
        return cls, instance, metadata

    # -- Introspection -----------------------------------------------------

    def is_installed(self, name: str) -> bool:
        with self._lock:
            return name in self._records

    def get(self, name: str) -> PluginRecord:
        with self._lock:
            if name not in self._records:
                raise PluginNotFoundError(f"plugin '{name}' is not installed")
            return self._records[name]

    def state(self, name: str) -> str:
        return self.get(name).state

    def list_plugins(self) -> list[PluginRecord]:
        with self._lock:
            return list(self._records.values())

    # -- Lifecycle ---------------------------------------------------------

    def install(self, plugin: PluginLike) -> PluginRecord:
        """Register a plugin as installed after validating its requirements."""
        cls, instance, metadata = self._resolve(plugin)
        with self._lock:
            if metadata.name in self._records:
                raise DuplicatePluginError(f"plugin '{metadata.name}' is already installed")
            self._check_python_requires(metadata)
            record = PluginRecord(
                name=metadata.name,
                cls=cls,
                metadata=metadata,
                instance=instance,
                state=PluginState.INSTALLED,
                module=cls.__module__,
            )
            self._records[metadata.name] = record
        self._instance(record).on_install()
        logger.info("installed plugin '%s' v%s", metadata.name, metadata.version)
        return record

    def load(self, name: str) -> PluginRecord:
        """Instantiate the plugin (if needed) and mark it loaded."""
        record = self.get(name)
        with self._lock:
            self._instance(record).on_load()
            if record.state == PluginState.INSTALLED:
                record.state = PluginState.LOADED
        logger.info("loaded plugin '%s'", name)
        return record

    def enable(self, name: str) -> PluginRecord:
        """Enable a plugin: verify dependencies, then register contributions."""
        record = self.get(name)
        if record.state == PluginState.ENABLED:
            return record
        self._check_dependencies(record.metadata)
        with self._lock:
            instance = self._instance(record)
            if record.state == PluginState.INSTALLED:
                instance.on_load()
            context = PluginContext(self.registry, record.name)
            instance.register(context)
            instance.on_enable()
            record.state = PluginState.ENABLED
            record.error = None
        logger.info("enabled plugin '%s'", name)
        return record

    def disable(self, name: str) -> PluginRecord:
        """Disable a plugin: withdraw its contributions from the registry."""
        record = self.get(name)
        if record.state != PluginState.ENABLED:
            return record
        with self._lock:
            self.registry.remove_plugin(record.name)
            if record.instance is not None:
                record.instance.on_disable()
            record.state = PluginState.DISABLED
        logger.info("disabled plugin '%s'", name)
        return record

    def uninstall(self, name: str) -> None:
        """Fully remove a plugin (disabling it first if enabled)."""
        record = self.get(name)
        if record.state == PluginState.ENABLED:
            self.disable(name)
        with self._lock:
            self.registry.remove_plugin(record.name)
            if record.instance is not None:
                record.instance.on_uninstall()
            record.state = PluginState.UNINSTALLED
            self._records.pop(name, None)
        logger.info("uninstalled plugin '%s'", name)

    def reload(self, name: str) -> PluginRecord:
        """Re-import the plugin's module and re-instantiate, restoring state.

        Lets developers iterate on a plugin without restarting the server.
        """
        record = self.get(name)
        previous_state = record.state
        module_name = record.module

        if record.state == PluginState.ENABLED:
            self.disable(name)

        if module_name and module_name in sys.modules:
            reloaded = self._reimport(sys.modules[module_name])
            refreshed = getattr(reloaded, record.cls.__name__, None)
            if refreshed is not None:
                record.cls = refreshed
                new_meta = getattr(refreshed, "metadata", None)
                if isinstance(new_meta, PluginMetadata):
                    new_meta.validate()
                    record.metadata = new_meta

        with self._lock:
            record.instance = None  # force re-instantiation from the fresh class
            record.state = PluginState.INSTALLED
        self._instance(record).on_reload()

        if previous_state == PluginState.ENABLED:
            self.enable(name)
        elif previous_state in (PluginState.LOADED, PluginState.DISABLED):
            self.load(name)
            if previous_state == PluginState.DISABLED:
                record.state = PluginState.DISABLED
        logger.info("reloaded plugin '%s'", name)
        return record

    # -- Bulk helpers ------------------------------------------------------

    def install_all(self, names: Optional[list[str]] = None) -> list[str]:
        """Install all (or the named) discovered plugins, skipping installed."""
        discovered = discovered_plugin_classes()
        targets = names if names is not None else list(discovered)
        installed: list[str] = []
        for name in targets:
            if self.is_installed(name):
                continue
            try:
                self.install(name)
                installed.append(name)
            except Exception:  # noqa: BLE001 - one failure shouldn't stop the rest
                logger.exception("failed to install plugin '%s'", name)
        return installed

    def enable_all(self) -> list[str]:
        """Enable installed plugins in dependency order (multi-pass).

        Plugins whose dependencies cannot be satisfied are left disabled and a
        warning is logged, rather than raising.
        """
        enabled: list[str] = []
        pending = [r.name for r in self.list_plugins() if r.state != PluginState.ENABLED]
        progress = True
        while pending and progress:
            progress = False
            for name in list(pending):
                try:
                    self._check_dependencies(self.get(name).metadata)
                except PluginDependencyError:
                    continue
                try:
                    self.enable(name)
                    enabled.append(name)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("failed to enable plugin '%s'", name)
                    self.get(name).error = str(exc)
                pending.remove(name)
                progress = True
        for name in pending:
            logger.warning("plugin '%s' left disabled: unmet dependencies", name)
        return enabled

    # -- Dependency & version checks --------------------------------------

    def _check_dependencies(self, metadata: PluginMetadata) -> None:
        """Ensure every declared plugin dependency is installed, enabled, in-range."""
        for spec in metadata.dependencies:
            requirement = Requirement.parse(spec)
            with self._lock:
                dep = self._records.get(requirement.name)
            if dep is None:
                raise PluginDependencyError(
                    f"plugin '{metadata.name}' requires '{requirement.name}', which is not installed"
                )
            if dep.state != PluginState.ENABLED:
                raise PluginDependencyError(
                    f"plugin '{metadata.name}' requires '{requirement.name}' to be enabled"
                )
            if not requirement.is_satisfied_by(dep.metadata.version):
                raise PluginDependencyError(
                    f"plugin '{metadata.name}' requires '{spec}', but '{requirement.name}' "
                    f"is v{dep.metadata.version}"
                )

    @staticmethod
    def _check_python_requires(metadata: PluginMetadata) -> None:
        """Ensure required external Python packages are installed and in-range."""
        if not metadata.requires:
            return
        from importlib.metadata import PackageNotFoundError, version as pkg_version

        for spec in metadata.requires:
            requirement = Requirement.parse(spec)
            try:
                installed = pkg_version(requirement.name)
            except PackageNotFoundError as exc:
                raise PluginDependencyError(
                    f"plugin '{metadata.name}' requires Python package '{requirement.name}', "
                    "which is not installed"
                ) from exc
            if not requirement.is_satisfied_by(installed):
                raise PluginDependencyError(
                    f"plugin '{metadata.name}' requires '{spec}', but '{requirement.name}' "
                    f"is v{installed}"
                )

    # -- Internal ----------------------------------------------------------

    def _instance(self, record: PluginRecord) -> PluginBase:
        """Return the plugin instance, creating it on first use."""
        if record.instance is None:
            record.instance = record.cls()
        return record.instance

    @staticmethod
    def _reimport(module):
        """Re-execute a module in place, working for both importable and
        file-based (drop-in) modules that ``importlib.reload`` cannot locate.

        Normal importable modules use ``importlib.reload``; drop-in file modules
        (not on ``sys.path``) are re-executed from fresh source, bypassing any
        bytecode cache so edits are always picked up.
        """
        try:
            return importlib.reload(module)
        except (ModuleNotFoundError, ImportError):
            file = getattr(module, "__file__", None)
            if file and os.path.exists(file):
                with open(file, "r", encoding="utf-8") as handle:
                    code = compile(handle.read(), file, "exec")
                exec(code, module.__dict__)
            return module


#: Process-wide default manager bound to the default registry.
plugin_manager = PluginManager(plugin_registry)
