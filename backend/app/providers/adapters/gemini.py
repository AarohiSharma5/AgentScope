"""Google Gemini provider adapter — Generative Language API.

Gemini uses ``:generateContent`` endpoints, a ``contents``/``parts`` payload
shape and an API key passed as a query parameter, so it is a bespoke adapter. It
supports both chat and embeddings.
"""
from __future__ import annotations

import json
import os
import time
from typing import Iterator, Optional, Union

from ..base import (
    Capability,
    ChatChunk,
    ChatResult,
    EmbeddingResult,
    HealthStatus,
    LLMProvider,
    Messages,
    ProviderConfigError,
    ProviderRequestError,
    Role,
    TokenUsage,
    normalize_messages,
)
from ..http import HttpClient, default_http_client
from ..registry import register_provider


@register_provider
class GeminiProvider(LLMProvider):
    name = "google-gemini"
    api_key_env = "GEMINI_API_KEY"
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    default_model = "gemini-2.0-flash"
    embedding_model = "text-embedding-004"
    capabilities = {
        Capability.CHAT,
        Capability.STREAMING,
        Capability.EMBEDDING,
        Capability.VISION,
        Capability.TOOLS,
    }
    models = ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "text-embedding-004"]
    pricing = {
        "gemini-2.0-flash": (0.0001, 0.0004),
        "gemini-1.5-pro": (0.00125, 0.005),
        "gemini-1.5-flash": (0.000075, 0.0003),
        "text-embedding-004": 0.0,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        http_client: Optional[HttpClient] = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.getenv(self.api_key_env) or os.getenv("GOOGLE_API_KEY")
        self.base_url = (base_url or os.getenv("GEMINI_BASE_URL") or self.base_url).rstrip("/")
        if default_model:
            self.default_model = default_model
        self.http = http_client or default_http_client
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _require(self) -> None:
        if not self.api_key:
            raise ProviderConfigError(f"provider 'google-gemini' requires {self.api_key_env}")

    @staticmethod
    def _to_contents(messages: Messages):
        """Convert chat messages into Gemini ``contents`` + ``systemInstruction``."""
        normalized = normalize_messages(messages)
        system = None
        contents = []
        for message in normalized:
            if message["role"] == Role.SYSTEM:
                system = message["content"]
                continue
            role = "model" if message["role"] == Role.ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        return contents, system

    def _body(self, messages: Messages, **kwargs) -> dict:
        contents, system = self._to_contents(messages)
        body: dict = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        generation_config = {}
        if kwargs.get("temperature") is not None:
            generation_config["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens") is not None:
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]
        if generation_config:
            body["generationConfig"] = generation_config
        return body

    @staticmethod
    def _extract_text(body: dict) -> str:
        candidates = body.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts)

    def _usage(self, body: dict, text: str, model: str) -> TokenUsage:
        meta = body.get("usageMetadata") or {}
        usage = TokenUsage(
            input_tokens=meta.get("promptTokenCount", 0),
            output_tokens=meta.get("candidatesTokenCount", 0),
        )
        if usage.total_tokens == 0 and text:
            usage.output_tokens = self.count_tokens(text)
        return usage

    def chat(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> ChatResult:
        self._require()
        model = model or self.default_model
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
        response = self.http.post_json(url, {}, self._body(messages, **kwargs), timeout=self.timeout)
        if not response.ok:
            raise ProviderRequestError(f"gemini chat failed [{response.status}]: {response.text[:300]}")
        body = response.json()
        text = self._extract_text(body)
        usage = self._usage(body, text, model)
        finish = (body.get("candidates") or [{}])[0].get("finishReason")
        return ChatResult(
            text=text, model=model, provider=self.name, usage=usage,
            cost=self.estimate_cost(usage, model=model), finish_reason=finish, raw=body,
        )

    def stream(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> Iterator[ChatChunk]:
        self._require()
        model = model or self.default_model
        url = f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
        index = 0
        for line in self.http.stream("POST", url, headers={}, payload=self._body(messages, **kwargs), timeout=self.timeout):
            if not line.startswith("data:"):
                continue
            try:
                chunk = json.loads(line[len("data:"):].strip())
            except json.JSONDecodeError:
                continue
            delta = self._extract_text(chunk)
            if delta:
                yield ChatChunk(delta=delta, model=model, provider=self.name, index=index, raw=chunk)
                index += 1

    def embed(self, texts: Union[str, list[str]], *, model: Optional[str] = None) -> EmbeddingResult:
        self._require()
        model = model or self.embedding_model
        inputs = [texts] if isinstance(texts, str) else list(texts)
        vectors: list[list[float]] = []
        for text in inputs:
            url = f"{self.base_url}/models/{model}:embedContent?key={self.api_key}"
            payload = {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}
            response = self.http.post_json(url, {}, payload, timeout=self.timeout)
            if not response.ok:
                raise ProviderRequestError(f"gemini embed failed [{response.status}]: {response.text[:300]}")
            vectors.append((response.json().get("embedding") or {}).get("values", []))
        usage = TokenUsage(input_tokens=sum(self.count_tokens(t) for t in inputs))
        return EmbeddingResult(
            vectors=vectors, model=model, provider=self.name, usage=usage,
            cost=self.estimate_cost(usage, model=model),
        )

    def health_check(self) -> HealthStatus:
        if not self.is_configured():
            return HealthStatus(healthy=False, configured=False, detail=f"missing API key ({self.api_key_env})")
        start = time.monotonic()
        try:
            response = self.http.get(f"{self.base_url}/models?key={self.api_key}", {}, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(healthy=False, configured=True, detail=f"unreachable: {exc}")
        latency = round((time.monotonic() - start) * 1000, 2)
        return HealthStatus(
            healthy=response.ok, configured=True,
            detail="ok" if response.ok else f"status {response.status}", latency_ms=latency,
        )
