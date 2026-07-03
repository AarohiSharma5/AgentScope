"""Mistral provider adapter (OpenAI-compatible API)."""
from ..base import Capability
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    api_key_env = "MISTRAL_API_KEY"
    base_url = "https://api.mistral.ai/v1"
    base_url_env = "MISTRAL_BASE_URL"
    default_model = "mistral-large-latest"
    embedding_model = "mistral-embed"
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.EMBEDDING, Capability.TOOLS}
    models = [
        "mistral-large-latest",
        "mistral-small-latest",
        "open-mistral-nemo",
        "mistral-embed",
    ]
    pricing = {
        "mistral-large-latest": (0.002, 0.006),
        "mistral-small-latest": (0.0002, 0.0006),
        "open-mistral-nemo": (0.00015, 0.00015),
        "mistral-embed": 0.0001,
    }
