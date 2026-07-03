"""REST endpoints for export / import / replay-from-export (v0.6, additive).

* ``GET  /api/export/formats``               — available formats (+ importable).
* ``GET  /api/export/kinds``                 — exportable/importable entity kinds.
* ``GET  /api/export/analytics?format=``     — export the analytics snapshot.
* ``GET  /api/export/<kind>/<id>?format=``   — export a conversation/workflow/replay/evaluation.
* ``POST /api/import[?format=]``             — reconstruct an uploaded bundle into the DB.
* ``POST /api/import/inspect[?format=]``     — parse + verify an upload without writing.
* ``POST /api/import/replay[?format=&model=&temperature=...]`` — import a conversation and replay it.

Downloads stream raw bytes with a ``Content-Disposition`` attachment header.
Uploads read the raw request body; the format is auto-detected when not given.
"""
import logging

from flask import Blueprint, Response, jsonify, request

from ..errors import error_response
from ..exporting import (
    BundleError,
    BundleKind,
    ExporterError,
    ImporterError,
    export_entity,
    import_data,
    inspect_data,
    list_formats,
    list_kinds,
    replay_from_export,
)
from ..exporting.bundle import ExportFormat

logger = logging.getLogger("agentscope")

exports_bp = Blueprint("exports", __name__)

_DEFAULT_FORMAT = ExportFormat.JSON


def _status_for(exc: BundleError) -> int:
    return 404 if "not found" in str(exc).lower() else 400


def _download(result) -> Response:
    response = Response(result.content, mimetype=result.content_type)
    response.headers["Content-Disposition"] = f'attachment; filename="{result.filename}"'
    response.headers["Content-Length"] = str(len(result.content))
    return response


# -- Discovery --------------------------------------------------------------


@exports_bp.get("/export/formats")
def export_formats():
    """List available export formats and their metadata."""
    return jsonify({"formats": list_formats()})


@exports_bp.get("/export/kinds")
def export_kinds():
    """List exportable and importable entity kinds."""
    return jsonify(list_kinds())


# -- Export -----------------------------------------------------------------


@exports_bp.get("/export/analytics")
def export_analytics():
    """Export the platform analytics snapshot (no entity id)."""
    fmt = request.args.get("format", _DEFAULT_FORMAT)
    try:
        return _download(export_entity(BundleKind.ANALYTICS, None, fmt))
    except ExporterError as exc:
        return error_response(str(exc), 400, {"formats": [f["format"] for f in list_formats()]})
    except BundleError as exc:
        return error_response(str(exc), _status_for(exc))


@exports_bp.get("/export/<kind>/<int:entity_id>")
def export_kind(kind: str, entity_id: int):
    """Export one entity of ``kind`` in the requested ``format``."""
    if kind not in BundleKind.ALL or kind == BundleKind.ANALYTICS:
        return error_response(
            "invalid export kind", 400, {"allowed": sorted(BundleKind.ALL - {BundleKind.ANALYTICS})}
        )
    fmt = request.args.get("format", _DEFAULT_FORMAT)
    try:
        return _download(export_entity(kind, entity_id, fmt))
    except ExporterError as exc:
        return error_response(str(exc), 400, {"formats": [f["format"] for f in list_formats()]})
    except BundleError as exc:
        return error_response(str(exc), _status_for(exc))


# -- Import -----------------------------------------------------------------


def _body_bytes() -> bytes:
    return request.get_data() or b""


@exports_bp.post("/import")
def import_bundle():
    """Reconstruct an uploaded bundle (conversation/workflow) into the database."""
    data = _body_bytes()
    if not data:
        return error_response("request body is empty", 400)
    try:
        return jsonify(import_data(data, request.args.get("format"))), 201
    except (ImporterError, BundleError) as exc:
        return error_response(str(exc), 400)


@exports_bp.post("/import/inspect")
def import_inspect():
    """Parse and verify an uploaded bundle without writing anything."""
    data = _body_bytes()
    if not data:
        return error_response("request body is empty", 400)
    try:
        return jsonify(inspect_data(data, request.args.get("format")))
    except (ImporterError, BundleError) as exc:
        return error_response(str(exc), 400)


@exports_bp.post("/import/replay")
def import_replay():
    """Import an exported conversation and replay it (optionally overriding params)."""
    data = _body_bytes()
    if not data:
        return error_response("request body is empty", 400)

    def _float(name):
        raw = request.args.get(name)
        return float(raw) if raw not in (None, "") else None

    try:
        overrides = {
            "model": request.args.get("model"),
            "temperature": _float("temperature"),
            "top_p": _float("top_p"),
            "system_prompt": request.args.get("system_prompt"),
            "conversation_name": request.args.get("conversation_name"),
        }
    except ValueError:
        return error_response("temperature and top_p must be numbers", 400)

    try:
        return jsonify(replay_from_export(data, request.args.get("format"), **overrides)), 201
    except (ImporterError, BundleError) as exc:
        return error_response(str(exc), 400)
