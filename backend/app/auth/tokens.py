"""Minimal, dependency-free JSON Web Tokens (HS256).

Implements just enough of RFC 7519 for stateless auth (``iat``/``exp``/``iss``/
``type`` claims, HMAC-SHA256 signatures) without pulling in a third-party JWT
library. Signatures are compared in constant time.

Decoding is deliberately strict to close the classic JWT verification gaps:

* **Algorithm confusion / ``alg: none``.** The header ``alg`` is parsed and must
  be in the caller's allow-list (``HS256`` only), so a token that asks for
  ``none`` — or any asymmetric algorithm — is rejected before any signature work.
* **Missing expiry.** ``exp`` is required by default, so a token minted without
  one can't be replayed forever.
* **Issuer.** When an ``issuer`` is supplied it must be present and match, so a
  token minted for another service/tenant is rejected.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Iterable, Optional

#: The only signing algorithm this module implements. Kept as an allow-list so
#: ``decode`` can reject ``alg: none`` and algorithm-confusion attacks up front.
_SUPPORTED_ALGORITHMS = ("HS256",)


class TokenError(Exception):
    """Base class for token decoding failures."""


class InvalidToken(TokenError):
    """The token is malformed, unauthorized, or its signature does not verify."""


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
    *,
    verify_exp: bool = True,
    require_exp: bool = True,
    issuer: Optional[str] = None,
    algorithms: Iterable[str] = _SUPPORTED_ALGORITHMS,
) -> dict:
    """Verify a token and return its claims, or raise on any failure.

    The header ``alg`` is pinned to ``algorithms`` (default ``HS256``), so
    ``alg: none`` and algorithm-confusion attacks are rejected before the
    signature is checked. ``exp`` is required unless ``require_exp`` is False, and
    when ``issuer`` is given the ``iss`` claim must be present and match.

    Raises :class:`InvalidToken` or :class:`ExpiredToken` on failure.
    """
    allowed = set(algorithms)
    try:
        header_seg, payload_seg, signature_seg = token.split(".")
    except (ValueError, AttributeError):
        raise InvalidToken("token is malformed")

    # Parse and pin the algorithm *before* trusting the token. This is what
    # rejects ``{"alg": "none"}`` and any algorithm we do not implement.
    try:
        header = json.loads(_b64decode(header_seg))
    except (ValueError, TypeError):
        raise InvalidToken("token header is not valid JSON")
    alg = header.get("alg")
    if alg not in allowed:
        raise InvalidToken(f"unsupported token algorithm: {alg!r}")

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

    if "exp" not in claims:
        if require_exp:
            raise InvalidToken("token is missing a required exp claim")
    elif verify_exp and int(claims["exp"]) < int(time.time()):
        raise ExpiredToken("token has expired")

    if issuer is not None and claims.get("iss") != issuer:
        raise InvalidToken("token issuer is not recognized")

    if expected_type is not None and claims.get("type") != expected_type:
        raise InvalidToken(f"expected a {expected_type} token")
    return claims
