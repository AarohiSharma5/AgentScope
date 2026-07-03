"""Anthropic (Claude) provider adapter — Messages API.

Anthropic's wire format differs from OpenAI's (a top-level ``system`` field,
``max_tokens`` required, and a distinct streaming event protocol), so this is a
bespoke adapter rather than an OpenAI-compatible subclass. Anthropic has no
embeddings API, so EMBEDDING is not advertised.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterator, Optional

from ..base import (
    Capability,
    ChatChunk,
    ChatResult,
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

logger = logging.getLogger("agentscope")

ANTHROPIC_VERSION = "2023-06-01"


@register_provider
class AnthropicProvider(LLMProvider):
    name = "anthropic"
    api_key_env = "ANTHROPIC_API_KEY"
    base_url = "https://api.anthropic.com/v1"
    default_model = "claude-3-5-sonnet-latest"
    capabilities = {Capability.CHAT, Capability.STREAMING, Capability.TOOLS, Capability.VISION}
    models = [
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
    ]
    pricing = {
        "claude-3-5-sonnet-latest": (0.003, 0.015),
        "claude-3-5-haiku-latest": (0.0008, 0.004),
        "claude-3-opus-latest": (0.015, 0.075),
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        http_client: Optional[HttpClient] = None,
        timeout: float = 30.0,
        max_tokens: int = 1024,
    ) -> None:
        self.api_key = api_key or os.getenv(self.api_key_env)
        self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL") or self.base_url).rstrip("/")
        if default_model:
            self.default_model = default_model
        self.http = http_client or default_http_client
        self.timeout = timeout
        self.max_tokens = max_tokens

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key or "", "anthropic-version": ANTHROPIC_VERSION}

    @staticmethod
    def _split_system(messages: Messages):
        """Separate a leading system prompt from the conversation turns."""
        normalized = normalize_messages(messages)
        system = None
        turns = []
        for message in normalized:
            if message["role"] == Role.SYSTEM:
                system = message["content"] if system is None else f"{system}\n{message['content']}"
            else:
                turns.append(message)
        return system, turns

    def _payload(self, messages: Messages, model: str, *, stream: bool, **kwargs) -> dict:
        system, turns = self._split_system(messages)
        payload = {
            "model": model,
            "messages": turns,
            "max_tokens": kwargs.get("max_tokens") or self.max_tokens,
        }
        if system:
            payload["system"] = system
        for key in ("temperature", "top_p", "tools", "stop_sequences"):
            if kwargs.get(key) is not None:
                payload[key] = kwargs[key]
        if stream:
            payload["stream"] = True
        return payload

    def chat(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> ChatResult:
        if not self.api_key:
            raise ProviderConfigError(f"provider 'anthropic' requires {self.api_key_env}")
        model = model or self.default_model
        response = self.http.post_json(
            f"{self.base_url}/messages", self._headers(), self._payload(messages, model, stream=False, **kwargs),
            timeout=self.timeout,
        )
        if not response.ok:
            raise ProviderRequestError(f"anthropic chat failed [{response.status}]: {response.text[:300]}")
        body = response.json()
        text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
        usage_raw = body.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
        )
        return ChatResult(
            text=text, model=body.get("model", model), provider=self.name, usage=usage,
            cost=self.estimate_cost(usage, model=model), finish_reason=body.get("stop_reason"), raw=body,
        )

    def stream(self, messages: Messages, *, model: Optional[str] = None, **kwargs) -> Iterator[ChatChunk]:
        if not self.api_key:
            raise ProviderConfigError(f"provider 'anthropic' requires {self.api_key_env}")
        model = model or self.default_model
        index = 0
        for line in self.http.stream(
            "POST", f"{self.base_url}/messages", headers=self._headers(),
            payload=self._payload(messages, model, stream=True, **kwargs), timeout=self.timeout,
        ):
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[len("data:"):].strip())
            except json.JSONDecodeError:
                continue
            if event.get("type") == "content_block_delta":
                delta = (event.get("delta") or {}).get("text") or ""
                if delta:
                    yield ChatChunk(delta=delta, model=model, provider=self.name, index=index, raw=event)
                    index += 1
            elif event.get("type") == "message_stop":
                break

    def health_check(self) -> HealthStatus:
        if not self.is_configured():
            return HealthStatus(healthy=False, configured=False, detail=f"missing API key ({self.api_key_env})")
        start = time.monotonic()
        try:
            # A tiny 1-token message is the cheapest reachability probe.
            response = self.http.post_json(
                f"{self.base_url}/messages", self._headers(),
                {"model": self.default_model, "max_tokens": 1, "messages": [{"role": Role.USER, "content": "ping"}]},
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(healthy=False, configured=True, detail=f"unreachable: {exc}")
        latency = round((time.monotonic() - start) * 1000, 2)
        return HealthStatus(
            healthy=response.ok, configured=True,
            detail="ok" if response.ok else f"status {response.status}", latency_ms=latency,
        )
