"""Provider abstraction: interfaces, value objects and capability taxonomy.

This defines a vendor-neutral contract for the external services the platform
talks to — LLMs, embedding models, retrievers, memories and tools. Concrete
adapters (OpenAI, Anthropic, Gemini, ...) implement these interfaces and
self-register with the :class:`~app.providers.registry.ProviderRegistry`, so new
providers are added purely by writing an adapter — the core never changes.

Every provider exposes discoverable capabilities, token counting, cost
estimation and a health check; LLM providers additionally expose ``chat`` and
``stream``, and embedding-capable providers expose ``embed``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Union

from ..utils.tokens import estimate_tokens
from .pricing import estimate_cost as _estimate_cost


# -- Exceptions -------------------------------------------------------------


class ProviderError(Exception):
    """Base class for provider errors."""


class ProviderNotFoundError(ProviderError):
    """Raised when an unknown provider is requested."""


class ProviderCapabilityError(ProviderError):
    """Raised when a provider is asked to do something it does not support."""


class ProviderConfigError(ProviderError):
    """Raised when a provider is missing required configuration (e.g. API key)."""


class ProviderRequestError(ProviderError):
    """Raised when an upstream provider call fails."""


# -- Capability taxonomy ----------------------------------------------------


class Capability:
    """Discoverable provider capabilities."""

    CHAT = "chat"
    STREAMING = "streaming"
    EMBEDDING = "embedding"
    TOOLS = "tools"
    VISION = "vision"
    JSON_MODE = "json_mode"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"


class Role:
    """Canonical chat roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# -- Value objects ----------------------------------------------------------


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class TokenUsage:
    """Token accounting for a request."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ChatResult:
    """The result of a (non-streaming) chat completion."""

    text: str
    model: str
    provider: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: Optional[float] = None
    finish_reason: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "usage": self.usage.to_dict(),
            "cost": self.cost,
            "finish_reason": self.finish_reason,
        }


@dataclass
class ChatChunk:
    """One incremental delta from a streaming chat completion."""

    delta: str
    model: str
    provider: str
    index: int = 0
    finish_reason: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class EmbeddingResult:
    """The result of an embedding call (one vector per input text)."""

    vectors: list[list[float]]
    model: str
    provider: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost: Optional[float] = None
    dimension: Optional[int] = None

    def __post_init__(self) -> None:
        if self.dimension is None and self.vectors:
            self.dimension = len(self.vectors[0])

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "count": len(self.vectors),
            "dimension": self.dimension,
            "usage": self.usage.to_dict(),
            "cost": self.cost,
        }


@dataclass
class HealthStatus:
    """The outcome of a provider health check."""

    healthy: bool
    configured: bool
    detail: str = ""
    latency_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "configured": self.configured,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
        }


@dataclass
class ProviderInfo:
    """Discoverable, static description of a provider (no instantiation needed)."""

    name: str
    kind: str
    capabilities: list[str]
    models: list[str]
    default_model: Optional[str]
    requires_api_key: bool
    api_key_env: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "capabilities": self.capabilities,
            "models": self.models,
            "default_model": self.default_model,
            "requires_api_key": self.requires_api_key,
            "api_key_env": self.api_key_env,
        }


Messages = Union[str, list["ChatMessage"], list[dict]]


def normalize_messages(messages: Messages) -> list[dict]:
    """Coerce a string / ChatMessage list / dict list into a dict list."""
    if isinstance(messages, str):
        return [{"role": Role.USER, "content": messages}]
    normalized: list[dict] = []
    for message in messages:
        if isinstance(message, ChatMessage):
            normalized.append(message.to_dict())
        elif isinstance(message, dict) and "role" in message and "content" in message:
            normalized.append({"role": message["role"], "content": message["content"]})
        else:
            raise ProviderError(f"invalid chat message: {message!r}")
    return normalized


# -- Interfaces -------------------------------------------------------------


class Provider(ABC):
    """Common contract shared by every provider kind.

    Class-level attributes describe the provider statically so its capabilities
    and models can be discovered without instantiating it (and thus without
    credentials).
    """

    #: Unique provider identifier (e.g. ``"openai"``).
    name: str = "provider"
    #: One of: ``llm``, ``embedding``, ``retriever``, ``memory``, ``tool``.
    kind: str = "provider"
    #: Static capability set (see :class:`Capability`).
    capabilities: set[str] = set()
    #: Known model identifiers (informational).
    models: list[str] = []
    #: Default model used when a call omits ``model``.
    default_model: Optional[str] = None
    #: Whether an API key is required to use this provider.
    requires_api_key: bool = True
    #: Environment variable the API key is read from, if any.
    api_key_env: Optional[str] = None
    #: Price table: ``{model: (input_per_1k, output_per_1k)}`` (USD).
    pricing: dict = {}

    def get_capabilities(self) -> set[str]:
        """Return the capabilities this provider supports."""
        return set(self.capabilities)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def is_configured(self) -> bool:
        """Whether the provider has what it needs to make calls."""
        return True

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            kind=self.kind,
            capabilities=sorted(self.capabilities),
            models=list(self.models),
            default_model=self.default_model,
            requires_api_key=self.requires_api_key,
            api_key_env=self.api_key_env,
        )

    def count_tokens(self, text: Optional[str], *, model: Optional[str] = None) -> int:
        """Estimate the token count of ``text`` (heuristic by default)."""
        return estimate_tokens(text)

    def estimate_cost(self, usage: TokenUsage, *, model: Optional[str] = None) -> Optional[float]:
        """Estimate USD cost for ``usage`` using this provider's price table."""
        return _estimate_cost(self.pricing, model or self.default_model, usage.input_tokens, usage.output_tokens)

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Return the provider's current health/reachability."""


class LLMProvider(Provider):
    """A chat/completions provider."""

    kind = "llm"

    @abstractmethod
    def chat(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> ChatResult:
        """Return a single completion for ``messages``."""

    @abstractmethod
    def stream(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> Iterator[ChatChunk]:
        """Yield incremental :class:`ChatChunk`s for ``messages``."""

    def embed(self, texts: Union[str, list[str]], *, model: Optional[str] = None) -> EmbeddingResult:
        """Embed text(s). Only valid when the provider supports EMBEDDING."""
        raise ProviderCapabilityError(f"provider '{self.name}' does not support embeddings")


class EmbeddingProvider(Provider):
    """An embedding provider."""

    kind = "embedding"

    @abstractmethod
    def embed(self, texts: Union[str, list[str]], *, model: Optional[str] = None) -> EmbeddingResult:
        """Return embeddings for ``texts``."""


class RetrieverProvider(Provider):
    """A retrieval provider (vector search / knowledge lookup)."""

    kind = "retriever"

    @abstractmethod
    def retrieve(self, query: str, *, top_k: int = 5, **kwargs) -> list[dict]:
        """Return up to ``top_k`` documents relevant to ``query``."""


class MemoryProvider(Provider):
    """A memory provider (read/write agent memory)."""

    kind = "memory"

    @abstractmethod
    def read(self, query: str, **kwargs) -> dict:
        """Look up a memory for ``query``."""

    @abstractmethod
    def write(self, key: str, value: Any, **kwargs) -> None:
        """Persist a memory value under ``key``."""


class ToolProvider(Provider):
    """A tool provider (exposes callable tools)."""

    kind = "tool"

    @abstractmethod
    def list_tools(self) -> list[dict]:
        """Return descriptors of the tools this provider exposes."""

    @abstractmethod
    def invoke(self, name: str, arguments: dict) -> Any:
        """Invoke tool ``name`` with ``arguments`` and return its result."""
