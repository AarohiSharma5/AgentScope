"""The canonical, portable export format — the *Trace Bundle*.

Everything AgentScope exports or imports is first expressed as a **bundle**: a
plain, ORM-free envelope of a manifest plus a kind-specific payload. Exporters
render a bundle into a concrete format (JSON, CSV, OTel, SQLite, ...) and
importers parse a format back into a bundle, so the DB-collection logic and the
DB-reconstruction logic each only ever deal with this one neutral shape.

Envelope::

    {
      "manifest": {
        "generator": "agentscope",
        "schema_version": "1.0",
        "kind": "conversation",
        "entity_id": 42,
        "exported_at": "2026-...Z",
        "checksum": "sha256:...",   # over the canonical payload
        "counts": {...}             # optional, informational
      },
      "payload": { ...kind-specific... }
    }
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from ..utils.timeutils import utcnow

SCHEMA_VERSION = "1.0"
GENERATOR = "agentscope"


class BundleKind:
    """The entity kinds that can be exported/imported."""

    CONVERSATION = "conversation"
    WORKFLOW = "workflow"
    REPLAY = "replay"
    EVALUATION = "evaluation"
    ANALYTICS = "analytics"

    ALL = frozenset({CONVERSATION, WORKFLOW, REPLAY, EVALUATION, ANALYTICS})
    #: Kinds that can be reconstructed into the database on import.
    IMPORTABLE = frozenset({CONVERSATION, WORKFLOW})


class ExportFormat:
    """The serialization formats an entity can be exported to."""

    JSON = "json"
    CSV = "csv"
    OTEL = "otel"
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    ZIP = "zip"
    BUNDLE = "bundle"  # the self-contained Trace Bundle (zip of all views)

    ALL = frozenset({JSON, CSV, OTEL, SQLITE, POSTGRES, ZIP, BUNDLE})


class BundleError(Exception):
    """Raised when a bundle is malformed or fails validation."""


def canonical_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, compact) used for checksums."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def checksum(payload: Any) -> str:
    """Return ``sha256:<hex>`` over the canonical form of ``payload``."""
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def make_bundle(
    kind: str,
    payload: dict,
    entity_id: Optional[int] = None,
    counts: Optional[dict] = None,
) -> dict:
    """Wrap a kind-specific ``payload`` in the standard bundle envelope."""
    if kind not in BundleKind.ALL:
        raise BundleError(f"unknown bundle kind: {kind!r}")
    manifest = {
        "generator": GENERATOR,
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "entity_id": entity_id,
        "exported_at": utcnow().isoformat(),
        "checksum": checksum(payload),
    }
    if counts:
        manifest["counts"] = counts
    return {"manifest": manifest, "payload": payload}


def validate_bundle(bundle: Any) -> dict:
    """Validate the envelope shape and return it, raising :class:`BundleError`."""
    if not isinstance(bundle, dict) or "manifest" not in bundle or "payload" not in bundle:
        raise BundleError("bundle must have 'manifest' and 'payload' keys")
    manifest = bundle["manifest"]
    if not isinstance(manifest, dict):
        raise BundleError("manifest must be an object")
    kind = manifest.get("kind")
    if kind not in BundleKind.ALL:
        raise BundleError(f"unknown or missing bundle kind: {kind!r}")
    return bundle


def verify_checksum(bundle: dict) -> bool:
    """Return True if the stored checksum matches the payload (True if absent)."""
    stored = bundle.get("manifest", {}).get("checksum")
    if not stored:
        return True
    return stored == checksum(bundle["payload"])
