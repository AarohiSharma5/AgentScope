"""Groq provider adapter (OpenAI-compatible API)."""
from ..base import Capability
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    api_key_env = "GROQ_API_KEY"
    base_url = "https://api.groq.com/openai/v1"
    base_url_env = "GROQ_BASE_URL"
    default_model = "llama-3.3-70b-versatile"
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.TOOLS}
    models = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]
    pricing = {
        "llama-3.3-70b-versatile": (0.00059, 0.00079),
        "llama-3.1-8b-instant": (0.00005, 0.00008),
        "mixtral-8x7b-32768": (0.00024, 0.00024),
        "gemma2-9b-it": (0.0002, 0.0002),
    }
