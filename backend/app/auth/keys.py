"""API key generation and hashing.

Keys look like ``as_<random>``. Only a keyed hash is persisted; the raw value is
shown once at creation. A short, non-secret ``prefix`` is stored to help users
identify a key in listings.

Hashing uses **HMAC-SHA256 keyed by a server-side pepper** rather than a bare
SHA-256. The raw keys are already 256 bits of ``secrets.token_urlsafe(32)`` — so
offline cracking was infeasible either way — but peppering means a stolen
``key_hash`` column is useless without also stealing the pepper (which lives in
config/secrets, not the database). For backward compatibility with keys minted
under the old bare-SHA-256 scheme, verification/lookup also accepts the legacy
digest (see :func:`candidate_hashes`); those keys keep working and simply age
out as they are rotated.
"""
import hashlib
import hmac
import secrets
from typing import Tuple

# Used only when hashing happens outside a Flask app context (e.g. a direct unit
# test of these helpers). Within the app, the configured ``API_KEY_PEPPER`` is
# used. Both the hashing and verification of a given key always run in the same
# context, so the two never mix.
_FALLBACK_PEPPER = "agentscope-api-key-pepper"


def _pepper() -> bytes:
    """The active HMAC pepper: app config when available, else a fallback."""
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            value = current_app.config.get("API_KEY_PEPPER")
            if value:
                return value.encode("utf-8")
    except Exception:  # pragma: no cover - defensive; never fail hashing on this
        pass
    return _FALLBACK_PEPPER.encode("utf-8")


def generate_key(prefix: str = "as") -> str:
    """Generate a new random API key string."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def key_prefix(raw: str) -> str:
    """A short, non-secret label for display/lookup (first 12 chars)."""
    return raw[:12]


def _legacy_hash(raw: str) -> str:
    """The pre-pepper bare SHA-256 digest (retained for backward compatibility)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_key(raw: str) -> str:
    """The peppered HMAC-SHA256 hex digest stored for newly minted keys."""
    return hmac.new(_pepper(), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def candidate_hashes(raw: str) -> Tuple[str, str]:
    """Hashes a stored key could match: the new peppered one and the legacy one.

    Used for DB lookup and verification so both current (HMAC) and pre-existing
    (bare SHA-256) keys resolve, while all *new* keys are stored peppered.
    """
    return hash_key(raw), _legacy_hash(raw)


def verify_key(raw: str, hashed: str) -> bool:
    """Constant-time comparison of a presented key against a stored hash."""
    return any(hmac.compare_digest(c, hashed) for c in candidate_hashes(raw))


def new_key(prefix: str = "as") -> Tuple[str, str, str]:
    """Return ``(raw, prefix, key_hash)`` for a freshly minted key."""
    raw = generate_key(prefix)
    return raw, key_prefix(raw), hash_key(raw)
