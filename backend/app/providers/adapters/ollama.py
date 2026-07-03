"""Ollama provider adapter (local, OpenAI-compatible endpoint).

Runs against a local Ollama server, so no API key is required and inference is
free (pricing is zero).
"""
from ..base import Capability
from ..registry import register_provider
from .openai_compatible import OpenAICompatibleProvider


@register_provider
class OllamaProvider(OpenAICompatibleProvider):
    name = "ollama"
    requires_api_key = False
    api_key_env = None
    base_url = "http://localhost:11434/v1"
    base_url_env = "OLLAMA_BASE_URL"
    default_model = "llama3.2"
    embedding_model = "nomic-embed-text"
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.EMBEDDING, Capability.TOOLS}
    models = ["llama3.2", "llama3.1", "qwen2.5", "mistral", "nomic-embed-text"]
    pricing = {}  # local inference is free
