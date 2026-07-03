"""API key generation and hashing.

Keys look like ``as_<random>``. Only the SHA-256 hash is persisted; the raw
value is shown once at creation. A short, non-secret ``prefix`` is stored to
help users identify a key in listings.
"""
import hashlib
import hmac
import secrets
from typing import Tuple


def generate_key(prefix: str = "as") -> str:
    """Generate a new random API key string."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def key_prefix(raw: str) -> str:
    """A short, non-secret label for display/lookup (first 12 chars)."""
    return raw[:12]


def hash_key(raw: str) -> str:
    """The SHA-256 hex digest stored in the database."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_key(raw: str, hashed: str) -> bool:
    """Constant-time comparison of a presented key against a stored hash."""
    return hmac.compare_digest(hash_key(raw), hashed)


def new_key(prefix: str = "as") -> Tuple[str, str, str]:
    """Return ``(raw, prefix, key_hash)`` for a freshly minted key."""
    raw = generate_key(prefix)
    return raw, key_prefix(raw), hash_key(raw)
