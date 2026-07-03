"""Example TOOL plugin: registers a couple of simple, callable tools."""
from ..base import Capability, PluginBase, PluginContext, PluginMetadata


def _echo(text: str = "", **_kwargs) -> str:
    """Return the input unchanged (a trivial demonstration tool)."""
    return text


def _word_count(text: str = "", **_kwargs) -> int:
    """Return the number of whitespace-delimited words in ``text``."""
    return len((text or "").split())


class SampleToolsPlugin(PluginBase):
    """Contributes ``echo`` and ``word_count`` tools."""

    metadata = PluginMetadata(
        name="sample-tools",
        version="1.0.0",
        author="AgentScope",
        description="Reference tool plugin providing echo and word_count.",
        capabilities=[Capability.TOOL],
        tags=["example", "tools"],
        license="MIT",
    )

    def register(self, context: PluginContext) -> None:
        context.register_tool("echo", _echo, description="Return the input text unchanged.")
        context.register_tool(
            "word_count", _word_count, description="Count words in the input text."
        )
