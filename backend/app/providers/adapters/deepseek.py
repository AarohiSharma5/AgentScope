"""DeepSeek provider adapter (OpenAI-compatible API)."""
from ..base import Capability
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"
    api_key_env = "DEEPSEEK_API_KEY"
    base_url = "https://api.deepseek.com/v1"
    base_url_env = "DEEPSEEK_BASE_URL"
    default_model = "deepseek-chat"
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.TOOLS, Capability.JSON_MODE}
    models = ["deepseek-chat", "deepseek-reasoner"]
    pricing = {
        "deepseek-chat": (0.00027, 0.0011),
        "deepseek-reasoner": (0.00055, 0.00219),
    }
