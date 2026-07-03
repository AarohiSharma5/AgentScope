"""``PluginLoader`` — discovers plugin classes by importing code.

Because :class:`~app.plugins.base.PluginBase` subclasses auto-register on
definition, "discovery" is simply "import the module(s)". The loader supports
four sources so third parties can ship plugins however they like — there are no
hardcoded providers:

* a dotted module path (``app.plugins.builtins.sample_tools``),
* a Python package (imported recursively),
* a filesystem directory of ``*.py`` files (dropped-in plugins),
* installed **entry points** (the standard mechanism for pip-installed plugins).
"""
import importlib
import importlib.util
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Iterable

from .base import discovered_plugin_classes

logger = logging.getLogger("agentscope")

DEFAULT_ENTRY_POINT_GROUP = "agentscope.plugins"


class PluginLoader:
    """Imports plugin-bearing code so classes self-register for discovery."""

    def load_module(self, dotted_path: str) -> None:
        """Import a single module by dotted path (idempotent via importlib)."""
        importlib.import_module(dotted_path)
        logger.debug("loaded plugin module %s", dotted_path)

    def load_package(self, package_name: str) -> list[str]:
        """Import a package and all of its submodules recursively.

        Returns the dotted names of every module imported.
        """
        package = importlib.import_module(package_name)
        imported = [package_name]
        search_paths = getattr(package, "__path__", None)
        if not search_paths:
            return imported
        for module_info in pkgutil.walk_packages(search_paths, prefix=f"{package_name}."):
            importlib.import_module(module_info.name)
            imported.append(module_info.name)
        logger.debug("loaded plugin package %s (%s modules)", package_name, len(imported))
        return imported

    def load_directory(self, directory: str) -> list[str]:
        """Import every top-level ``*.py`` file in ``directory`` as a module.

        Enables drop-in plugins that are not part of an installed package.
        Returns the module names imported. Missing directories are ignored.
        """
        path = Path(directory)
        if not path.is_dir():
            logger.debug("plugin directory %s does not exist; skipping", directory)
            return []
        imported: list[str] = []
        for file in sorted(path.glob("*.py")):
            if file.name.startswith("_"):
                continue
            module_name = f"agentscope_plugin_{file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            # Register before exec so the module is reloadable and imports resolve.
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            imported.append(module_name)
        logger.debug("loaded %s plugin file(s) from %s", len(imported), directory)
        return imported

    def load_entry_points(self, group: str = DEFAULT_ENTRY_POINT_GROUP) -> list[str]:
        """Load plugins advertised via installed entry points.

        This is how pip-installed third-party plugins register themselves. Each
        entry point is loaded (which imports its module and triggers
        auto-registration). Returns the entry-point names loaded.
        """
        loaded: list[str] = []
        try:
            from importlib.metadata import entry_points

            selected = entry_points(group=group)
        except Exception:  # pragma: no cover - older importlib.metadata shapes
            return loaded
        for entry_point in selected:
            try:
                entry_point.load()
                loaded.append(entry_point.name)
            except Exception:  # noqa: BLE001 - one bad plugin must not break the rest
                logger.exception("failed to load entry-point plugin %s", entry_point.name)
        if loaded:
            logger.info("loaded %s entry-point plugin(s) from group '%s'", len(loaded), group)
        return loaded

    def discover(
        self,
        packages: Iterable[str] = (),
        directories: Iterable[str] = (),
        modules: Iterable[str] = (),
        entry_point_group: "str | None" = None,
    ) -> dict[str, type]:
        """Import from all configured sources and return discovered classes.

        Each source is best-effort: a failure in one is logged and does not
        prevent the others from loading.
        """
        for module in modules:
            self._safe(self.load_module, module)
        for package in packages:
            self._safe(self.load_package, package)
        for directory in directories:
            self._safe(self.load_directory, directory)
        if entry_point_group:
            self._safe(self.load_entry_points, entry_point_group)
        return discovered_plugin_classes()

    @staticmethod
    def _safe(func, arg) -> None:
        try:
            func(arg)
        except Exception:  # noqa: BLE001 - discovery must be resilient
            logger.exception("plugin discovery failed for %r", arg)
