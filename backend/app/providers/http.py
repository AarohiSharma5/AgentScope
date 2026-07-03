"""A tiny, injectable HTTP client for provider adapters.

Adapters never import vendor SDKs; they speak HTTP through this interface. The
default :class:`UrllibHttpClient` uses only the standard library (no ``requests``
dependency), and tests inject a fake client so no network access is required.
"""
from __future__ import annotations

import json as _json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional

logger = logging.getLogger("agentscope")

DEFAULT_TIMEOUT = 30.0


@dataclass
class HttpResponse:
    """A normalized HTTP response."""

    status: int
    text: str = ""
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> dict:
        if not self.text:
            return {}
        return _json.loads(self.text)


class HttpClient(ABC):
    """Transport used by provider adapters (injectable for tests)."""

    @abstractmethod
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        payload: Optional[dict] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> HttpResponse:
        """Perform a request and return an :class:`HttpResponse`."""

    @abstractmethod
    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict] = None,
        payload: Optional[dict] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Iterator[str]:
        """Perform a request and yield decoded response lines (for SSE)."""

    # Convenience wrappers -------------------------------------------------

    def post_json(self, url: str, headers: dict, payload: dict, timeout: float = DEFAULT_TIMEOUT) -> HttpResponse:
        return self.request("POST", url, headers=headers, payload=payload, timeout=timeout)

    def get(self, url: str, headers: dict, timeout: float = DEFAULT_TIMEOUT) -> HttpResponse:
        return self.request("GET", url, headers=headers, timeout=timeout)


class UrllibHttpClient(HttpClient):
    """Standard-library HTTP client (no third-party dependency)."""

    def _build(self, method: str, url: str, headers: Optional[dict], payload: Optional[dict]):
        data = _json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        return request

    def request(self, method, url, *, headers=None, payload=None, timeout=DEFAULT_TIMEOUT) -> HttpResponse:
        request = self._build(method, url, headers, payload)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return HttpResponse(status=response.status, text=body, headers=dict(response.headers))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return HttpResponse(status=exc.code, text=body, headers=dict(exc.headers or {}))

    def stream(self, method, url, *, headers=None, payload=None, timeout=DEFAULT_TIMEOUT) -> Iterator[str]:
        request = self._build(method, url, headers, payload)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\n").rstrip("\r")
                if line:
                    yield line


#: Shared default client instance.
default_http_client = UrllibHttpClient()
