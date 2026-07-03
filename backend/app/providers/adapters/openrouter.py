"""OpenRouter provider adapter (OpenAI-compatible aggregator API)."""
from ..base import Capability
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    api_key_env = "OPENROUTER_API_KEY"
    base_url = "https://openrouter.ai/api/v1"
    base_url_env = "OPENROUTER_BASE_URL"
    default_model = "openai/gpt-4o-mini"
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.TOOLS}
    models = [
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "anthropic/claude-3.5-sonnet",
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.3-70b-instruct",
    ]
    # OpenRouter prices vary per upstream model and are returned per-response;
    # leave unpriced so cost is reported by the API rather than guessed.
    pricing = {}
