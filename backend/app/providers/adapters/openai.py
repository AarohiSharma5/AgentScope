"""OpenAI provider adapter."""
from ..base import Capability
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    api_key_env = "OPENAI_API_KEY"
    base_url = "https://api.openai.com/v1"
    base_url_env = "OPENAI_BASE_URL"
    default_model = "gpt-4o-mini"
    embedding_model = "text-embedding-3-small"
    capabilities = {
        Capability.CHAT,
        Capability.STREAMING,
        Capability.EMBEDDING,
        Capability.TOOLS,
        Capability.VISION,
        Capability.JSON_MODE,
    }
    models = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "text-embedding-3-small",
        "text-embedding-3-large",
    ]
    pricing = {
        "gpt-4o": (0.0025, 0.01),
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-4-turbo": (0.01, 0.03),
        "gpt-3.5-turbo": (0.0005, 0.0015),
        "text-embedding-3-small": 0.00002,
        "text-embedding-3-large": 0.00013,
        "text-embedding-ada-002": 0.0001,
    }
