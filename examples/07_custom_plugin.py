"""Author a plugin that contributes a custom tool.

Defining a `PluginBase` subclass with concrete metadata auto-registers it for
discovery. This example instantiates the plugin, registers its contributions
into a registry, and looks the tool back up. Run inside the backend environment:

    cd backend && source .venv/bin/activate
    python ../examples/07_custom_plugin.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main() -> None:
    from app.plugins import (
        Capability,
        PluginBase,
        PluginContext,
        PluginMetadata,
        PluginRegistry,
    )

    class WeatherToolPlugin(PluginBase):
        metadata = PluginMetadata(
            name="weather-tools",
            version="1.0.0",
            author="Aarohi Sharma",
            description="Adds a weather-lookup tool.",
            capabilities=[Capability.TOOL],
            tags=["tools", "weather"],
        )

        def register(self, context: PluginContext) -> None:
            context.register_tool("weather", self.weather, description="Current weather")

        @staticmethod
        def weather(city: str) -> dict:
            return {"city": city, "temp_c": 21, "conditions": "clear"}

    # Enable the plugin against a registry (the PluginManager does this for you
    # in the real lifecycle: install -> load -> enable).
    registry = PluginRegistry()
    plugin = WeatherToolPlugin()
    plugin.register(PluginContext(registry, plugin.metadata.name))

    tool = registry.get_tool("weather")
    print("Registered tools:", list(registry.list(Capability.TOOL)))
    print("weather('Paris') ->", tool("Paris"))


if __name__ == "__main__":
    main()
