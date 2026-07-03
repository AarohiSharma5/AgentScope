"""Example UI_EXTENSION plugin.

Contributes a UI-extension descriptor (plain JSON a frontend can fetch via the
plugins API and render). It also declares a dependency on ``sample-tools`` to
demonstrate the manager's dependency + version checking: this plugin cannot be
enabled unless ``sample-tools>=1.0.0`` is installed and enabled first.
"""
from ..base import Capability, PluginBase, PluginContext, PluginMetadata


class SampleUIPlugin(PluginBase):
    """Contributes a 'Tools' panel descriptor; depends on ``sample-tools``."""

    metadata = PluginMetadata(
        name="sample-ui",
        version="1.0.0",
        author="AgentScope",
        description="Reference UI-extension plugin (adds a Tools panel).",
        capabilities=[Capability.UI_EXTENSION],
        dependencies=["sample-tools>=1.0.0"],
        tags=["example", "ui"],
        license="MIT",
    )

    def register(self, context: PluginContext) -> None:
        context.register_ui_extension(
            "tools-panel",
            {
                "slot": "sidebar",
                "title": "Tools",
                "icon": "wrench",
                "route": "/plugins/tools",
                "component": "ToolsPanel",
            },
            description="Sidebar panel listing plugin-provided tools.",
        )
