"""Tests for the v0.6 provider abstraction.

All network I/O goes through an injected fake HTTP client, so these tests are
hermetic (no keys, no network). Covered:

* OpenAI-compatible chat / stream / embed / token counting / cost / health.
* Azure URL + auth-header specialization.
* Anthropic (system split, chat, stream) and Gemini (chat, embed) adapters.
* Registry discovery, capability discovery and runtime extensibility
  (registering a brand-new provider without touching core code).
* The /api/providers REST surface.
"""
import json

import pytest

from app.providers import (
    Capability,
    ChatMessage,
    HttpClient,
    HttpResponse,
    LLMProvider,
    ProviderConfigError,
    ProviderNotFoundError,
    Role,
    provider_registry,
)
from app.providers.adapters.anthropic import AnthropicProvider
from app.providers.adapters.azure_openai import AzureOpenAIProvider
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.openai import OpenAIProvider
from app.providers.base import HealthStatus


class FakeHttp(HttpClient):
    """A scripted HTTP client that records calls and returns canned data."""

    def __init__(self, body=None, status=200, stream_lines=None):
        self.body = body or {}
        self.status = status
        self.stream_lines = stream_lines or []
        self.calls = []

    def request(self, method, url, *, headers=None, payload=None, timeout=30.0) -> HttpResponse:
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "payload": payload})
        return HttpResponse(status=self.status, text=json.dumps(self.body))

    def stream(self, method, url, *, headers=None, payload=None, timeout=30.0):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "payload": payload, "stream": True})
        yield from self.stream_lines


# -- OpenAI-compatible ------------------------------------------------------


def test_openai_chat():
    http = FakeHttp(
        body={
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    )
    provider = OpenAIProvider(api_key="sk-test", http_client=http)
    result = provider.chat([ChatMessage(Role.USER, "hi")])

    assert result.text == "Hello!"
    assert result.provider == "openai"
    assert result.usage.input_tokens == 10 and result.usage.output_tokens == 5
    assert result.usage.total_tokens == 15
    assert result.finish_reason == "stop"
    # cost = 10/1k*0.00015 + 5/1k*0.0006
    assert result.cost == pytest.approx(0.0000045)
    assert http.calls[0]["url"].endswith("/chat/completions")
    assert http.calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_chat_accepts_plain_string():
    http = FakeHttp(body={"choices": [{"message": {"content": "ok"}}], "usage": {}})
    provider = OpenAIProvider(api_key="k", http_client=http)
    result = provider.chat("just a string prompt")
    assert http.calls[0]["payload"]["messages"] == [{"role": "user", "content": "just a string prompt"}]
    assert result.text == "ok"


def test_openai_stream():
    http = FakeHttp(
        stream_lines=[
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
        ]
    )
    provider = OpenAIProvider(api_key="k", http_client=http)
    chunks = list(provider.stream("hi"))
    assert [c.delta for c in chunks] == ["Hel", "lo"]
    assert http.calls[0]["payload"]["stream"] is True


def test_openai_embed():
    http = FakeHttp(
        body={
            "model": "text-embedding-3-small",
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
            "usage": {"prompt_tokens": 3},
        }
    )
    provider = OpenAIProvider(api_key="k", http_client=http)
    result = provider.embed("embed me")
    assert result.vectors == [[0.1, 0.2, 0.3]]
    assert result.dimension == 3
    assert result.usage.input_tokens == 3
    assert http.calls[0]["url"].endswith("/embeddings")


def test_embed_unsupported_capability_raises():
    provider = AnthropicProvider(api_key="k", http_client=FakeHttp())
    with pytest.raises(Exception):
        provider.embed("nope")


def test_token_counting_and_cost():
    provider = OpenAIProvider(api_key="k", http_client=FakeHttp())
    assert provider.count_tokens("abcd" * 4) > 0
    from app.providers.base import TokenUsage

    assert provider.estimate_cost(TokenUsage(1000, 1000), model="gpt-4o") == pytest.approx(0.0125)
    # Unknown model -> no price.
    assert provider.estimate_cost(TokenUsage(1000, 1000), model="mystery") is None


def test_health_unconfigured_without_key():
    provider = OpenAIProvider(http_client=FakeHttp())  # no api key
    status = provider.health_check()
    assert isinstance(status, HealthStatus)
    assert status.configured is False and status.healthy is False


def test_health_ok_when_configured():
    provider = OpenAIProvider(api_key="k", http_client=FakeHttp(status=200))
    status = provider.health_check()
    assert status.configured is True and status.healthy is True
    assert status.latency_ms is not None


def test_chat_requires_api_key():
    provider = OpenAIProvider(http_client=FakeHttp())
    with pytest.raises(ProviderConfigError):
        provider.chat("hi")


# -- Azure specialization ---------------------------------------------------


def test_azure_url_and_auth_header():
    http = FakeHttp(body={"choices": [{"message": {"content": "x"}}], "usage": {}})
    provider = AzureOpenAIProvider(
        api_key="azkey", base_url="https://res.openai.azure.com", http_client=http, api_version="2024-06-01"
    )
    provider.chat("hi", model="my-deployment")
    call = http.calls[0]
    assert "/openai/deployments/my-deployment/chat/completions?api-version=2024-06-01" in call["url"]
    assert call["headers"]["api-key"] == "azkey"
    assert "model" not in call["payload"]  # deployment encoded in URL


# -- Anthropic --------------------------------------------------------------


def test_anthropic_chat_splits_system():
    http = FakeHttp(
        body={
            "model": "claude-3-5-sonnet-latest",
            "content": [{"type": "text", "text": "Hi there"}],
            "usage": {"input_tokens": 8, "output_tokens": 2},
            "stop_reason": "end_turn",
        }
    )
    provider = AnthropicProvider(api_key="k", http_client=http)
    result = provider.chat(
        [ChatMessage(Role.SYSTEM, "Be terse"), ChatMessage(Role.USER, "hello")]
    )
    assert result.text == "Hi there"
    assert result.usage.input_tokens == 8 and result.usage.output_tokens == 2
    payload = http.calls[0]["payload"]
    assert payload["system"] == "Be terse"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert http.calls[0]["headers"]["x-api-key"] == "k"


def test_anthropic_stream():
    http = FakeHttp(
        stream_lines=[
            'data: {"type":"content_block_delta","delta":{"text":"He"}}',
            'data: {"type":"content_block_delta","delta":{"text":"llo"}}',
            'data: {"type":"message_stop"}',
        ]
    )
    provider = AnthropicProvider(api_key="k", http_client=http)
    assert [c.delta for c in provider.stream("hi")] == ["He", "llo"]


# -- Gemini -----------------------------------------------------------------


def test_gemini_chat():
    http = FakeHttp(
        body={
            "candidates": [{"content": {"parts": [{"text": "Yo"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 6, "candidatesTokenCount": 3},
        }
    )
    provider = GeminiProvider(api_key="k", http_client=http)
    result = provider.chat([ChatMessage(Role.SYSTEM, "sys"), ChatMessage(Role.USER, "hi")])
    assert result.text == "Yo"
    assert result.usage.input_tokens == 6 and result.usage.output_tokens == 3
    assert ":generateContent?key=k" in http.calls[0]["url"]
    assert http.calls[0]["payload"]["systemInstruction"]["parts"][0]["text"] == "sys"


def test_gemini_embed():
    http = FakeHttp(body={"embedding": {"values": [0.5, 0.6]}})
    provider = GeminiProvider(api_key="k", http_client=http)
    result = provider.embed("hello")
    assert result.vectors == [[0.5, 0.6]]
    assert result.dimension == 2


# -- Registry & discovery ---------------------------------------------------

EXPECTED_PROVIDERS = {
    "openai", "azure-openai", "ollama", "openrouter", "groq",
    "deepseek", "mistral", "anthropic", "google-gemini",
}


def test_all_adapters_registered():
    assert EXPECTED_PROVIDERS <= set(provider_registry.names())


def test_registry_describe_and_filter():
    embedding_providers = {p["name"] for p in provider_registry.describe(capability=Capability.EMBEDDING)}
    assert "openai" in embedding_providers
    assert "groq" not in embedding_providers  # groq has no embeddings here


def test_registry_by_capability_and_map():
    assert "anthropic" in provider_registry.by_capability(Capability.VISION)
    caps = provider_registry.capabilities()
    assert set(caps[Capability.CHAT]) >= EXPECTED_PROVIDERS


def test_registry_create_and_unknown():
    provider = provider_registry.create("openai", api_key="k", http_client=FakeHttp())
    assert isinstance(provider, OpenAIProvider)
    with pytest.raises(ProviderNotFoundError):
        provider_registry.create("nonexistent")


def test_can_add_provider_without_core_changes():
    """A brand-new provider is usable purely by registering an adapter."""

    class CustomProvider(LLMProvider):
        name = "test-custom-llm"
        requires_api_key = False
        capabilities = {Capability.CHAT}
        models = ["custom-1"]
        default_model = "custom-1"

        def chat(self, messages, *, model=None, **kwargs):
            from app.providers.base import ChatResult

            return ChatResult(text="custom", model="custom-1", provider=self.name)

        def stream(self, messages, *, model=None, **kwargs):
            yield from ()

        def health_check(self):
            return HealthStatus(healthy=True, configured=True, detail="ok")

    provider_registry.register(CustomProvider)
    try:
        assert "test-custom-llm" in provider_registry.names()
        assert "test-custom-llm" in provider_registry.by_capability(Capability.CHAT)
        instance = provider_registry.create("test-custom-llm")
        assert instance.chat("hi").text == "custom"
    finally:
        provider_registry.unregister("test-custom-llm")


# -- REST API ---------------------------------------------------------------


def test_api_list_providers(client):
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.get_json()["providers"]}
    assert EXPECTED_PROVIDERS <= names


def test_api_list_providers_filter_capability(client):
    resp = client.get("/api/providers?capability=embedding")
    names = {p["name"] for p in resp.get_json()["providers"]}
    assert "openai" in names and "groq" not in names


def test_api_get_provider(client):
    resp = client.get("/api/providers/anthropic")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["name"] == "anthropic"
    assert body["requires_api_key"] is True
    assert "streaming" in body["capabilities"]


def test_api_get_provider_404(client):
    assert client.get("/api/providers/nope").status_code == 404


def test_api_capabilities(client):
    resp = client.get("/api/providers/capabilities")
    assert resp.status_code == 200
    caps = resp.get_json()["capabilities"]
    assert "openai" in caps["chat"]


def test_api_provider_health_unconfigured(client):
    # anthropic without a key configured -> unconfigured, 503, no network.
    resp = client.get("/api/providers/anthropic/health")
    body = resp.get_json()
    assert body["provider"] == "anthropic"
    assert "healthy" in body and "configured" in body
    assert resp.status_code in (200, 503)
