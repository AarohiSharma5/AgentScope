"""High-level façade over collection, exporters and importers.

Routes call into here; this module ties the pieces together (collect -> render,
parse -> reconstruct) and exposes replay-from-export. All DB access happens via
the collectors/importers, which delegate to the existing services.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from . import collect, exporters, importers
from .bundle import BundleKind, verify_checksum

logger = logging.getLogger("agentscope")


@dataclass
class ExportResult:
    """A rendered export ready to be returned as a download."""

    content: bytes
    filename: str
    content_type: str


def list_formats() -> list[dict]:
    """Describe every available export format (and whether it is importable)."""
    importable_formats = set(importers._IMPORTERS)
    result = []
    for info in exporters.exporter_registry.describe():
        result.append({**info, "importable": info["format"] in importable_formats})
    return result


def list_kinds() -> dict:
    """List exportable and importable entity kinds."""
    return {
        "exportable": sorted(BundleKind.ALL),
        "importable": sorted(BundleKind.IMPORTABLE),
    }


def export_entity(kind: str, entity_id: Optional[int], fmt: str) -> ExportResult:
    """Collect ``kind``/``entity_id`` and render it in ``fmt``."""
    bundle = collect.collect(kind, entity_id)
    exporter = exporters.exporter_registry.get(fmt)
    content = exporter.export(bundle)
    suffix = entity_id if entity_id is not None else "all"
    filename = f"agentscope-{kind}-{suffix}.{exporter.extension}"
    logger.info("exported %s id=%s as %s (%d bytes)", kind, entity_id, fmt, len(content))
    return ExportResult(content=content, filename=filename, content_type=exporter.content_type)


def inspect_data(data: bytes, fmt: Optional[str] = None) -> dict:
    """Parse uploaded data and return its manifest + checksum status (no DB write)."""
    bundle = importers.parse(data, fmt)
    return {
        "manifest": bundle["manifest"],
        "checksum_valid": verify_checksum(bundle),
    }


def import_data(data: bytes, fmt: Optional[str] = None) -> dict:
    """Parse and reconstruct uploaded data into the database."""
    bundle = importers.parse(data, fmt)
    summary = importers.import_bundle_to_db(bundle)
    logger.info("imported %s -> new id=%s", summary.get("kind"), summary.get("entity_id"))
    return {"manifest": bundle["manifest"], "imported": summary}


def replay_from_export(data: bytes, fmt: Optional[str] = None, **overrides: Any) -> dict:
    """Import an exported conversation and replay it, returning both ids.

    ``overrides`` are forwarded to the replay engine (``model``,
    ``temperature``, ``top_p``, ``system_prompt``, ``conversation_name``).
    """
    from ..orchestration.replay_engine import ReplayEngine

    bundle = importers.parse(data, fmt)
    if bundle["manifest"]["kind"] != BundleKind.CONVERSATION:
        from .bundle import BundleError

        raise BundleError("replay is only supported for conversation exports")

    imported = importers.import_bundle_to_db(bundle)
    conversation_id = imported["entity_id"]

    clean = {k: v for k, v in overrides.items() if v is not None}
    result = ReplayEngine().replay(conversation_id, **clean)
    return {
        "imported_conversation_run_id": conversation_id,
        "replay_run_id": result.replay_run.id,
        "replay_conversation_run_id": result.replay_conversation_run_id,
        "status": result.status,
        "totals": result.totals,
    }
