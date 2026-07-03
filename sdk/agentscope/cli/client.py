"""A tiny HTTP client for the AgentScope server REST API (stdlib only)."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Tuple


class ApiError(Exception):
    """An API call failed (transport error or non-2xx response)."""

    def __init__(self, message: str, status: Optional[int] = None, details: Any = None):
        super().__init__(message)
        self.status = status
        self.details = details


class ApiClient:
    """Talks to a running AgentScope server; returns parsed JSON."""

    def __init__(self, endpoint: str, api_key: Optional[str] = None, timeout: float = 10.0):
        self.base = endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- verbs --------------------------------------------------------------

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("GET", path, params=params)[1]

    def post(self, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, params=params, body=body)[1]

    def delete(self, path: str, params: Optional[dict] = None) -> Any:
        return self._request("DELETE", path, params=params)[1]

    def post_raw(self, path: str, data: bytes, params: Optional[dict] = None) -> Any:
        return self._request("POST", path, params=params, raw=data)[1]

    def download(self, path: str, params: Optional[dict] = None) -> Tuple[bytes, str]:
        """GET raw bytes; returns ``(content, filename)`` from the response."""
        status, content, headers = self._raw_request("GET", path, params=params)
        if status >= 400:
            raise ApiError(f"request failed ({status})", status)
        disposition = headers.get("Content-Disposition", "")
        filename = "export.bin"
        if "filename=" in disposition:
            filename = disposition.split("filename=")[-1].strip().strip('"')
        return content, filename

    def ping(self) -> bool:
        """Return True when the server responds to a lightweight request."""
        try:
            self._raw_request("GET", "/api/stats")
            return True
        except (ApiError, urllib.error.URLError, OSError):
            return False

    # -- transport ----------------------------------------------------------

    def _url(self, path: str, params: Optional[dict]) -> str:
        url = f"{self.base}{path}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean, doseq=True)
        return url

    def _headers(self, content_type: Optional[str] = None) -> dict:
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _raw_request(self, method, path, params=None, body=None, raw=None):
        if raw is not None:
            data, ctype = raw, "application/octet-stream"
        elif body is not None:
            data, ctype = json.dumps(body).encode("utf-8"), "application/json"
        else:
            data, ctype = None, None
        req = urllib.request.Request(
            self._url(path, params), data=data, headers=self._headers(ctype), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec - user endpoint
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:  # includes 4xx/5xx
            return exc.code, exc.read(), dict(exc.headers)
        except urllib.error.URLError as exc:
            raise ApiError(f"cannot reach server at {self.base}: {exc.reason}") from exc

    def _request(self, method, path, params=None, body=None, raw=None):
        status, payload, _ = self._raw_request(method, path, params=params, body=body, raw=raw)
        data: Any = None
        if payload:
            try:
                data = json.loads(payload.decode("utf-8"))
            except ValueError:
                data = payload.decode("utf-8", errors="replace")
        if status >= 400:
            message = data.get("error") if isinstance(data, dict) else f"request failed ({status})"
            details = data.get("details") if isinstance(data, dict) else None
            raise ApiError(message or f"request failed ({status})", status, details)
        return status, data
