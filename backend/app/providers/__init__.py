"""Provider abstraction (v0.6): vendor-neutral access to external services.

Defines the provider interfaces (:class:`LLMProvider`, :class:`EmbeddingProvider`,
:class:`RetrieverProvider`, :class:`MemoryProvider`, :class:`ToolProvider`), the
shared value objects (chat/embedding results, token usage, health status), and a
:class:`ProviderRegistry` that discovers and instantiates providers by name.

Importing this package registers all built-in adapters (OpenAI, Anthropic,
Gemini, Ollama, OpenRouter, Azure OpenAI, Groq, DeepSeek, Mistral). New providers
are added by writing an adapter and registering it — the core never changes.
"""
from .base import (
    Capability,
    ChatChunk,
    ChatMessage,
    ChatResult,
    EmbeddingProvider,
    EmbeddingResult,
    HealthStatus,
    LLMProvider,
    MemoryProvider,
    ProviderCapabilityError,
    ProviderConfigError,
    ProviderError,
    ProviderInfo,
    ProviderNotFoundError,
    ProviderRequestError,
    RetrieverProvider,
    Role,
    TokenUsage,
    ToolProvider,
)
from .http import HttpClient, HttpResponse, UrllibHttpClient, default_http_client
from .registry import ProviderRegistry, provider_registry, register_provider

# Import adapters for their registration side effects.
from . import adapters  # noqa: E402,F401

__all__ = [
    "Capability",
    "ChatChunk",
    "ChatMessage",
    "ChatResult",
    "EmbeddingProvider",
    "EmbeddingResult",
    "HealthStatus",
    "HttpClient",
    "HttpResponse",
    "LLMProvider",
    "MemoryProvider",
    "ProviderCapabilityError",
    "ProviderConfigError",
    "ProviderError",
    "ProviderInfo",
    "ProviderNotFoundError",
    "ProviderRegistry",
    "ProviderRequestError",
    "RetrieverProvider",
    "Role",
    "TokenUsage",
    "ToolProvider",
    "UrllibHttpClient",
    "default_http_client",
    "provider_registry",
    "register_provider",
]
