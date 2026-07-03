"""Persistent CLI settings (endpoint, API key, defaults).

Settings live in a JSON file, by default ``~/.agentscope/config.json`` (override
the directory with ``AGENTSCOPE_HOME`` or the exact file with
``AGENTSCOPE_CONFIG``). Environment variables (``AGENTSCOPE_*``) take precedence
over the file, and explicit CLI flags take precedence over everything.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# Persisted keys and their types. ``api_key`` is stored but masked on display.
KNOWN_KEYS = {
    "endpoint": str,
    "api_key": str,
    "service_name": str,
    "default_model": str,
    "timeout": float,
    "color": bool,
}

_ENV_MAP = {
    "endpoint": "AGENTSCOPE_ENDPOINT",
    "api_key": "AGENTSCOPE_API_KEY",
    "service_name": "AGENTSCOPE_SERVICE_NAME",
    "default_model": "AGENTSCOPE_DEFAULT_MODEL",
    "timeout": "AGENTSCOPE_TIMEOUT",
}


def config_path() -> Path:
    """Resolve the settings file path (respecting env overrides)."""
    explicit = os.environ.get("AGENTSCOPE_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    home = os.environ.get("AGENTSCOPE_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".agentscope"
    return base / "config.json"


def _coerce(key: str, value: Any) -> Any:
    typ = KNOWN_KEYS.get(key, str)
    if value is None or isinstance(value, typ):
        return value
    if typ is bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if typ is float:
        return float(value)
    return str(value)


class Settings:
    """Loaded CLI settings with helpers to read, mutate and persist."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, path: Optional[Path] = None):
        self._data: Dict[str, Any] = dict(data or {})
        self.path = path or config_path()

    # -- persistence --------------------------------------------------------

    @classmethod
    def load(cls) -> "Settings":
        path = config_path()
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
        # Layer environment variables on top of the file.
        for key, env in _ENV_MAP.items():
            if os.environ.get(env):
                data[key] = _coerce(key, os.environ[env])
        return cls(data, path)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in self._data.items() if v is not None}
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:  # tighten permissions where supported (holds an API key)
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - non-POSIX
            pass
        return self.path

    # -- accessors ----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = _coerce(key, value)

    def unset(self, key: str) -> bool:
        return self._data.pop(key, _MISSING) is not _MISSING

    def as_dict(self, mask_secrets: bool = True) -> Dict[str, Any]:
        out = dict(self._data)
        if mask_secrets and out.get("api_key"):
            out["api_key"] = _mask(out["api_key"])
        return out

    @property
    def endpoint(self) -> Optional[str]:
        return self._data.get("endpoint")

    @property
    def api_key(self) -> Optional[str]:
        return self._data.get("api_key")

    @property
    def timeout(self) -> float:
        return float(self._data.get("timeout") or 10.0)


_MISSING = object()


def _mask(secret: str) -> str:
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}…{secret[-4:]}"
