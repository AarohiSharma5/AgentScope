"""Built-in provider adapters.

Importing this package imports every adapter module, which registers each
provider with the default :class:`~app.providers.registry.ProviderRegistry` via
the ``@register_provider`` decorator. Adding a new provider means dropping a new
module here (or registering one from anywhere else) — no core code changes.
"""
from . import (  # noqa: F401 - imported for their registration side effects
    anthropic,
    azure_openai,
    deepseek,
    gemini,
    groq,
    mistral,
    ollama,
    openai,
    openrouter,
)
