"""Tests for the v0.6 plugin system.

Covered:
* Version parsing + dependency/constraint matching.
* Automatic self-registration of PluginBase subclasses.
* Full lifecycle: install / load / enable / disable / uninstall / reload,
  with contributions appearing in and disappearing from the registry.
* Metadata validation, duplicate installs, plugin + Python-package dependency
  checking, and dependency-ordered bulk enable.
* Loader discovery (package + drop-in directory).
* The /api/plugins REST surface (list, get, extensions, lifecycle, errors).
"""
import textwrap

import pytest

from app.plugins import (
    Capability,
    Contribution,
    DuplicatePluginError,
    PluginBase,
    PluginContext,
    PluginDependencyError,
    PluginError,
    PluginLoader,
    PluginManager,
    PluginMetadata,
    PluginNotFoundError,
    PluginRegistry,
    PluginState,
    PluginValidationError,
    discovered_plugin_classes,
)
from app.plugins.registry import PluginRegistry as Registry
from app.plugins.versioning import Requirement, parse_version, satisfies


# -- Module-level example plugins (benign; safe for global auto-install) ----


class AlphaPlugin(PluginBase):
    metadata = PluginMetadata(
        name="test-alpha",
        version="1.2.0",
        capabilities=[Capability.TOOL],
    )

    def register(self, context: PluginContext) -> None:
        context.register_tool("t_alpha", lambda **_: "alpha")


class BetaPlugin(PluginBase):
    """Depends on test-alpha to exercise dependency ordering/checking."""

    metadata = PluginMetadata(
        name="test-beta",
        version="1.0.0",
        capabilities=[Capability.EVALUATOR],
        dependencies=["test-alpha>=1.0.0"],
    )

    def register(self, context: PluginContext) -> None:
        context.register_evaluator("t_beta", object())


class GammaPlugin(PluginBase):
    """Depends on test-beta (which depends on test-alpha) for transitive tests."""

    metadata = PluginMetadata(
        name="test-gamma",
        version="1.0.0",
        capabilities=[Capability.MEMORY],
        dependencies=["test-beta>=1.0.0"],
    )

    def register(self, context: PluginContext) -> None:
        context.register_memory("t_gamma", object())


@pytest.fixture()
def manager():
    """A fresh manager bound to an isolated registry (no global state)."""
    return PluginManager(PluginRegistry())


# -- Versioning -------------------------------------------------------------


def test_parse_version():
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("2") == (2,)
    assert parse_version("1.4.0rc1") == (1, 4, 0)


@pytest.mark.parametrize(
    "version,spec,expected",
    [
        ("1.2.0", "test>=1.0.0", True),
        ("1.2.0", "test>=1.3.0", False),
        ("1.2.0", "test==1.2.0", True),
        ("1.2.0", "test!=1.2.0", False),
        ("1.2.0", "test<2.0.0", True),
        ("1.5.0", "test>=1.0,<2.0", True),
        ("2.0.0", "test>=1.0,<2.0", False),
        ("1.4.5", "test~=1.4.0", True),
        ("1.5.0", "test~=1.4.0", False),
        ("1.4.0", "test", True),
    ],
)
def test_requirement_matching(version, spec, expected):
    assert Requirement.parse(spec).is_satisfied_by(version) is expected


def test_requirement_missing_version_fails_constraint():
    assert Requirement.parse("test>=1.0").is_satisfied_by(None) is False


def test_satisfies_helper():
    assert satisfies("1.2.0", ">=1.0") is True
    assert satisfies("1.2.0", "<1.0") is False


# -- Auto-registration ------------------------------------------------------


def test_subclasses_auto_register():
    discovered = discovered_plugin_classes()
    assert discovered.get("test-alpha") is AlphaPlugin
    assert discovered.get("test-beta") is BetaPlugin


def test_abstract_subclass_not_registered():
    class AbstractThing(PluginBase):
        abstract = True

    assert "AbstractThing" not in [c.__name__ for c in discovered_plugin_classes().values()]


# -- Metadata validation ----------------------------------------------------


def test_metadata_validation_rejects_bad_capability():
    with pytest.raises(PluginValidationError):
        PluginMetadata(name="x", version="1.0", capabilities=["not-real"]).validate()


def test_metadata_validation_requires_name_and_version():
    with pytest.raises(PluginValidationError):
        PluginMetadata(name="", version="1.0").validate()
    with pytest.raises(PluginValidationError):
        PluginMetadata(name="x", version="").validate()


# -- Lifecycle --------------------------------------------------------------


def test_install_load_enable_registers_contribution(manager):
    manager.install(AlphaPlugin)
    assert manager.state("test-alpha") == PluginState.INSTALLED

    manager.enable("test-alpha")
    assert manager.state("test-alpha") == PluginState.ENABLED
    tool = manager.registry.get_tool("t_alpha")
    assert callable(tool) and tool() == "alpha"


def test_disable_withdraws_contributions(manager):
    manager.install(AlphaPlugin)
    manager.enable("test-alpha")
    manager.disable("test-alpha")
    assert manager.state("test-alpha") == PluginState.DISABLED
    assert manager.registry.get_tool("t_alpha") is None


def test_uninstall_removes_plugin_and_contributions(manager):
    manager.install(AlphaPlugin)
    manager.enable("test-alpha")
    manager.uninstall("test-alpha")
    assert manager.registry.get_tool("t_alpha") is None
    with pytest.raises(PluginNotFoundError):
        manager.get("test-alpha")


def test_duplicate_install_raises(manager):
    manager.install(AlphaPlugin)
    with pytest.raises(DuplicatePluginError):
        manager.install(AlphaPlugin)


def test_lifecycle_hooks_fire(manager):
    events = []

    class HookPlugin(PluginBase):
        metadata = PluginMetadata(name="test-hooks", version="1.0", capabilities=[])

        def on_install(self):
            events.append("install")

        def on_enable(self):
            events.append("enable")

        def on_disable(self):
            events.append("disable")

        def on_uninstall(self):
            events.append("uninstall")

    manager.install(HookPlugin)
    manager.enable("test-hooks")
    manager.disable("test-hooks")
    manager.uninstall("test-hooks")
    assert events == ["install", "enable", "disable", "uninstall"]


# -- Dependency checking ----------------------------------------------------


def test_enable_fails_when_dependency_not_enabled(manager):
    manager.install(AlphaPlugin)
    manager.install(BetaPlugin)
    with pytest.raises(PluginDependencyError):
        manager.enable("test-beta")  # test-alpha installed but not enabled


def test_enable_fails_when_dependency_missing(manager):
    manager.install(BetaPlugin)  # test-alpha not installed at all
    with pytest.raises(PluginDependencyError):
        manager.enable("test-beta")


def test_enable_succeeds_after_dependency_enabled(manager):
    manager.install(AlphaPlugin)
    manager.install(BetaPlugin)
    manager.enable("test-alpha")
    manager.enable("test-beta")
    assert manager.state("test-beta") == PluginState.ENABLED


def test_dependency_version_mismatch(manager):
    class NeedsNewAlpha(PluginBase):
        metadata = PluginMetadata(
            name="test-needs-new-alpha",
            version="1.0",
            capabilities=[],
            dependencies=["test-alpha>=2.0.0"],
        )

    manager.install(AlphaPlugin)  # v1.2.0
    manager.enable("test-alpha")
    manager.install(NeedsNewAlpha)
    with pytest.raises(PluginDependencyError):
        manager.enable("test-needs-new-alpha")


def test_python_requires_missing_package_fails_install(manager):
    class NeedsMissing(PluginBase):
        metadata = PluginMetadata(
            name="test-needs-missing-pkg",
            version="1.0",
            capabilities=[],
            requires=["a-package-that-does-not-exist-xyz>=1.0"],
        )

    with pytest.raises(PluginDependencyError):
        manager.install(NeedsMissing)


def test_python_requires_present_package_installs(manager):
    class NeedsFlask(PluginBase):
        metadata = PluginMetadata(
            name="test-needs-flask",
            version="1.0",
            capabilities=[],
            requires=["flask>=2.0"],
        )

    manager.install(NeedsFlask)  # flask is installed -> no error
    assert manager.is_installed("test-needs-flask")


def test_disable_cascades_to_dependents(manager):
    manager.install(AlphaPlugin)
    manager.install(BetaPlugin)
    manager.enable("test-alpha")
    manager.enable("test-beta")

    manager.disable("test-alpha")
    # The dependent is disabled too, so nothing enabled relies on a disabled dep.
    assert manager.state("test-alpha") == PluginState.DISABLED
    assert manager.state("test-beta") == PluginState.DISABLED
    assert manager.registry.get_evaluator("t_beta") is None


def test_disable_cascade_can_be_opted_out(manager):
    manager.install(AlphaPlugin)
    manager.install(BetaPlugin)
    manager.enable("test-alpha")
    manager.enable("test-beta")

    manager.disable("test-alpha", cascade=False)
    assert manager.state("test-alpha") == PluginState.DISABLED
    assert manager.state("test-beta") == PluginState.ENABLED  # left as-is


def test_disable_cascade_is_transitive(manager):
    for plugin in (AlphaPlugin, BetaPlugin, GammaPlugin):
        manager.install(plugin)
    manager.enable_all()
    assert manager.state("test-gamma") == PluginState.ENABLED

    manager.disable("test-alpha")
    assert manager.state("test-beta") == PluginState.DISABLED
    assert manager.state("test-gamma") == PluginState.DISABLED


def test_uninstall_cascades_disable_to_dependents(manager):
    manager.install(AlphaPlugin)
    manager.install(BetaPlugin)
    manager.enable("test-alpha")
    manager.enable("test-beta")

    manager.uninstall("test-alpha")
    assert not manager.is_installed("test-alpha")
    assert manager.state("test-beta") == PluginState.DISABLED


def test_enable_all_respects_dependency_order(manager):
    # Install beta before alpha; enable_all must still order them correctly.
    manager.install(BetaPlugin)
    manager.install(AlphaPlugin)
    enabled = manager.enable_all()
    assert set(enabled) == {"test-alpha", "test-beta"}
    assert manager.state("test-beta") == PluginState.ENABLED


# -- Registry ---------------------------------------------------------------


def test_registry_rejects_name_collision_across_plugins():
    registry = Registry()
    registry.add_contribution(
        Contribution(capability=Capability.TOOL, name="dup", obj=1, plugin="p1")
    )
    with pytest.raises(PluginError):
        registry.add_contribution(
            Contribution(capability=Capability.TOOL, name="dup", obj=2, plugin="p2")
        )


# -- Loader -----------------------------------------------------------------


def test_loader_discovers_builtin_package():
    loader = PluginLoader()
    modules = loader.load_package("app.plugins.builtins")
    assert any("sample_tools" in m for m in modules)
    assert "sample-tools" in discovered_plugin_classes()


def test_loader_directory_dropins(tmp_path, manager):
    plugin_file = tmp_path / "dropin_plugin.py"
    plugin_file.write_text(
        textwrap.dedent(
            '''
            from app.plugins.base import Capability, PluginBase, PluginContext, PluginMetadata

            class DropInPlugin(PluginBase):
                metadata = PluginMetadata(
                    name="test-dropin", version="1.0.0", capabilities=[Capability.TOOL]
                )
                def register(self, context: PluginContext) -> None:
                    context.register_tool("dropin_tool", lambda **_: "ok")
            '''
        )
    )
    loader = PluginLoader()
    loader.load_directory(str(tmp_path))
    assert "test-dropin" in discovered_plugin_classes()

    manager.install("test-dropin")
    manager.enable("test-dropin")
    assert manager.registry.get_tool("dropin_tool")() == "ok"


def test_reload_picks_up_new_version(tmp_path, manager):
    plugin_file = tmp_path / "reloadable_plugin.py"

    def write(version: str):
        plugin_file.write_text(
            textwrap.dedent(
                f'''
                from app.plugins.base import Capability, PluginBase, PluginMetadata

                class ReloadablePlugin(PluginBase):
                    metadata = PluginMetadata(
                        name="test-reloadable", version="{version}", capabilities=[]
                    )
                '''
            )
        )

    loader = PluginLoader()
    write("1.0.0")
    loader.load_directory(str(tmp_path))
    manager.install("test-reloadable")
    manager.enable("test-reloadable")
    assert manager.get("test-reloadable").metadata.version == "1.0.0"

    write("2.0.0")
    manager.reload("test-reloadable")
    assert manager.get("test-reloadable").metadata.version == "2.0.0"
    assert manager.state("test-reloadable") == PluginState.ENABLED


# -- REST API (uses the global app with builtins auto-loaded) ---------------


def test_api_list_plugins(client):
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.get_json()["plugins"]}
    assert {"sample-tools", "sample-evaluators", "sample-backends", "sample-ui"} <= names


def test_api_get_plugin(client):
    resp = client.get("/api/plugins/sample-tools")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "sample-tools"
    assert body["state"] == PluginState.ENABLED
    assert Capability.TOOL in body["capabilities"]


def test_api_get_unknown_plugin_404(client):
    assert client.get("/api/plugins/does-not-exist").status_code == 404


def test_api_extensions_filtered(client):
    resp = client.get("/api/plugins/extensions?capability=tool")
    assert resp.status_code == 200
    names = {e["name"] for e in resp.get_json()["extensions"]}
    assert {"echo", "word_count"} <= names


def test_api_extensions_ui_includes_descriptor(client):
    resp = client.get("/api/plugins/extensions?capability=ui_extension")
    ui = next(e for e in resp.get_json()["extensions"] if e["name"] == "tools-panel")
    assert ui["descriptor"]["slot"] == "sidebar"


def test_api_extensions_bad_capability_400(client):
    assert client.get("/api/plugins/extensions?capability=bogus").status_code == 400


def test_api_disable_enable_roundtrip(client):
    assert client.post("/api/plugins/sample-backends/disable").status_code == 200
    assert client.get("/api/plugins/sample-backends").get_json()["state"] == PluginState.DISABLED
    assert client.post("/api/plugins/sample-backends/enable").status_code == 200
    assert client.get("/api/plugins/sample-backends").get_json()["state"] == PluginState.ENABLED


def test_api_enable_missing_dependency_conflict(client):
    # Disabling sample-tools then sample-ui, re-enabling sample-ui must 409
    # because its dependency (sample-tools) is not enabled.
    client.post("/api/plugins/sample-ui/disable")
    client.post("/api/plugins/sample-tools/disable")
    resp = client.post("/api/plugins/sample-ui/enable")
    assert resp.status_code == 409
    # Restore for other tests sharing the process singleton.
    client.post("/api/plugins/sample-tools/enable")
    client.post("/api/plugins/sample-ui/enable")


def test_api_reload_plugin(client):
    resp = client.post("/api/plugins/sample-tools/reload")
    assert resp.status_code == 200
    assert resp.get_json()["state"] == PluginState.ENABLED


def test_api_disable_cascades_to_dependent(client):
    # sample-ui depends on sample-tools; disabling sample-tools disables sample-ui.
    assert client.post("/api/plugins/sample-tools/disable").status_code == 200
    assert client.get("/api/plugins/sample-ui").get_json()["state"] == PluginState.DISABLED
    # Restore (dependency first, then dependent).
    client.post("/api/plugins/sample-tools/enable")
    client.post("/api/plugins/sample-ui/enable")


def test_api_disable_cascade_false_leaves_dependent(client):
    assert client.post("/api/plugins/sample-tools/disable?cascade=false").status_code == 200
    assert client.get("/api/plugins/sample-ui").get_json()["state"] == PluginState.ENABLED
    client.post("/api/plugins/sample-tools/enable")
