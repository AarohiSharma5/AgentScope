"""Minimal, dependency-free JSON Web Tokens (HS256).

Implements just enough of RFC 7519 for stateless auth (``iat``/``exp``/``type``
claims, HMAC-SHA256 signatures) without pulling in a third-party JWT library.
Signatures are compared in constant time.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional


class TokenError(Exception):
    """Base class for token decoding failures."""


class InvalidToken(TokenError):
    """The token is malformed or its signature does not verify."""


class ExpiredToken(TokenError):
    """The token's ``exp`` claim is in the past."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def encode(
    claims: dict,
    secret: str,
    expires_in: Optional[int] = None,
    token_type: Optional[str] = None,
) -> str:
    """Encode ``claims`` into a signed HS256 JWT.

    ``iat`` is always set; ``exp`` is set when ``expires_in`` (seconds) is given.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(claims)
    now = int(time.time())
    payload.setdefault("iat", now)
    if expires_in is not None:
        payload["exp"] = now + int(expires_in)
    if token_type is not None:
        payload["type"] = token_type

    header_seg = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    payload_seg = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_seg}.{payload_seg}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_seg}.{payload_seg}.{_b64encode(signature)}"


def decode(
    token: str,
    secret: str,
    expected_type: Optional[str] = None,
    verify_exp: bool = True,
) -> dict:
    """Verify a token's signature/expiry and return its claims.

    Raises :class:`InvalidToken` or :class:`ExpiredToken` on failure.
    """
    try:
        header_seg, payload_seg, signature_seg = token.split(".")
    except (ValueError, AttributeError):
        raise InvalidToken("token is malformed")

    signing_input = f"{header_seg}.{payload_seg}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    try:
        provided = _b64decode(signature_seg)
    except (ValueError, TypeError):
        raise InvalidToken("token signature is not valid base64")
    if not hmac.compare_digest(expected, provided):
        raise InvalidToken("token signature does not verify")

    try:
        claims = json.loads(_b64decode(payload_seg))
    except (ValueError, TypeError):
        raise InvalidToken("token payload is not valid JSON")

    if verify_exp and "exp" in claims and int(claims["exp"]) < int(time.time()):
        raise ExpiredToken("token has expired")
    if expected_type is not None and claims.get("type") != expected_type:
        raise InvalidToken(f"expected a {expected_type} token")
    return claims
