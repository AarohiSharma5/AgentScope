"""Shared base for OpenAI-compatible chat/embeddings providers.

Many providers (OpenAI, Azure OpenAI, Groq, DeepSeek, Mistral, OpenRouter,
Ollama) speak the same ``/chat/completions`` + ``/embeddings`` wire format. This
base implements ``chat``/``stream``/``embed``/token-counting/cost/health once;
concrete adapters only declare their ``base_url``, API-key env var, models,
capabilities and pricing. Adding another OpenAI-compatible provider therefore
means a ~15-line subclass and nothing else.
"""
from __future__ import annotations

import logging
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
    ProviderCapabilityError,
    ProviderConfigError,
    ProviderRequestError,
    TokenUsage,
    normalize_messages,
)
from ..http import HttpClient, default_http_client

logger = logging.getLogger("agentscope")


class OpenAICompatibleProvider(LLMProvider):
    """Base adapter for OpenAI-style REST APIs."""

    #: Default API base URL (no trailing slash), overridable via env/ctor.
    base_url: str = "https://api.openai.com/v1"
    #: Env var providing the base URL override, if any.
    base_url_env: Optional[str] = None
    #: Default embedding model for providers that support embeddings.
    embedding_model: Optional[str] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        http_client: Optional[HttpClient] = None,
        timeout: float = 30.0,
        extra_headers: Optional[dict] = None,
    ) -> None:
        self.api_key = api_key or (os.getenv(self.api_key_env) if self.api_key_env else None)
        env_base = os.getenv(self.base_url_env) if self.base_url_env else None
        self.base_url = (base_url or env_base or self.base_url).rstrip("/")
        if default_model:
            self.default_model = default_model
        self.http = http_client or default_http_client
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    # -- Configuration -----------------------------------------------------

    def is_configured(self) -> bool:
        return (not self.requires_api_key) or bool(self.api_key)

    def _auth_headers(self) -> dict:
        headers = dict(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _require_config(self) -> None:
        if self.requires_api_key and not self.api_key:
            raise ProviderConfigError(
                f"provider '{self.name}' requires an API key "
                f"({self.api_key_env or 'api_key'} not set)"
            )

    # -- URL construction (overridable, e.g. Azure) ------------------------

    def _chat_url(self, model: str) -> str:
        return f"{self.base_url}/chat/completions"

    def _embeddings_url(self, model: str) -> str:
        return f"{self.base_url}/embeddings"

    def _models_url(self) -> str:
        return f"{self.base_url}/models"

    def _payload_model(self, model: str) -> dict:
        return {"model": model}

    # -- Chat --------------------------------------------------------------

    def chat(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> ChatResult:
        self._require_config()
        model = model or self.default_model
        payload = self._build_chat_payload(messages, model, stream=False, **kwargs)
        response = self.http.post_json(
            self._chat_url(model), self._auth_headers(), payload, timeout=self.timeout
        )
        if not response.ok:
            raise ProviderRequestError(f"{self.name} chat failed [{response.status}]: {response.text[:300]}")
        return self._parse_chat_response(response.json(), model)

    def stream(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> Iterator[ChatChunk]:
        self._require_config()
        model = model or self.default_model
        payload = self._build_chat_payload(messages, model, stream=True, **kwargs)
        index = 0
        for line in self.http.stream(
            "POST", self._chat_url(model), headers=self._auth_headers(), payload=payload, timeout=self.timeout
        ):
            data = self._parse_sse_line(line)
            if data is None:
                continue
            if data == "[DONE]":
                break
            choice = (data.get("choices") or [{}])[0]
            delta = (choice.get("delta") or {}).get("content") or ""
            finish = choice.get("finish_reason")
            if delta or finish:
                yield ChatChunk(
                    delta=delta, model=model, provider=self.name, index=index,
                    finish_reason=finish, raw=data,
                )
                index += 1

    def _build_chat_payload(self, messages: Messages, model: str, *, stream: bool, **kwargs) -> dict:
        payload = self._payload_model(model)
        payload["messages"] = normalize_messages(messages)
        if stream:
            payload["stream"] = True
        for key in ("temperature", "top_p", "max_tokens", "tools", "tool_choice", "response_format", "stop"):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]
        return payload

    def _parse_chat_response(self, body: dict, model: str) -> ChatResult:
        choice = (body.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage_raw = body.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
        )
        if usage.total_tokens == 0 and text:
            usage.output_tokens = self.count_tokens(text)
        return ChatResult(
            text=text,
            model=body.get("model", model),
            provider=self.name,
            usage=usage,
            cost=self.estimate_cost(usage, model=model),
            finish_reason=choice.get("finish_reason"),
            raw=body,
        )

    @staticmethod
    def _parse_sse_line(line: str):
        """Parse an SSE ``data:`` line into a dict, ``"[DONE]"`` or ``None``."""
        import json

        if not line.startswith("data:"):
            return None
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            return "[DONE]"
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    # -- Embeddings --------------------------------------------------------

    def embed(self, texts: Union[str, list[str]], *, model: Optional[str] = None) -> EmbeddingResult:
        if Capability.EMBEDDING not in self.capabilities:
            raise ProviderCapabilityError(f"provider '{self.name}' does not support embeddings")
        self._require_config()
        model = model or self.embedding_model or self.default_model
        inputs = [texts] if isinstance(texts, str) else list(texts)
        payload = self._payload_model(model)
        payload["input"] = inputs
        response = self.http.post_json(
            self._embeddings_url(model), self._auth_headers(), payload, timeout=self.timeout
        )
        if not response.ok:
            raise ProviderRequestError(f"{self.name} embed failed [{response.status}]: {response.text[:300]}")
        body = response.json()
        vectors = [item.get("embedding", []) for item in body.get("data", [])]
        usage_raw = body.get("usage") or {}
        usage = TokenUsage(input_tokens=usage_raw.get("prompt_tokens", sum(self.count_tokens(t) for t in inputs)))
        return EmbeddingResult(
            vectors=vectors,
            model=body.get("model", model),
            provider=self.name,
            usage=usage,
            cost=self.estimate_cost(usage, model=model),
        )

    # -- Health ------------------------------------------------------------

    def health_check(self) -> HealthStatus:
        if not self.is_configured():
            return HealthStatus(
                healthy=False, configured=False,
                detail=f"missing API key ({self.api_key_env})",
            )
        start = time.monotonic()
        try:
            response = self.http.get(self._models_url(), self._auth_headers(), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - report, never raise from a health check
            return HealthStatus(healthy=False, configured=True, detail=f"unreachable: {exc}")
        latency = round((time.monotonic() - start) * 1000, 2)
        return HealthStatus(
            healthy=response.ok,
            configured=True,
            detail="ok" if response.ok else f"status {response.status}",
            latency_ms=latency,
        )
