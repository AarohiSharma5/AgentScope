"""Service metadata endpoints: health, version and the OpenAPI reference.

Mounted at both ``/api`` (unversioned alias) and ``/api/v1`` so the docs and
health probe are reachable regardless of which prefix a client uses.
"""
from flask import Blueprint, Response, jsonify, request

from ..openapi import get_spec, swagger_ui_html
from ..version import API_VERSION, SUPPORTED_API_VERSIONS, __version__

meta_bp = Blueprint("meta", __name__)


@meta_bp.get("/health")
def health():
    """Liveness probe (unauthenticated)."""
    return jsonify({"status": "ok", "service": "agentscope"})


@meta_bp.get("/version")
def version():
    """Return service and API version metadata (unauthenticated)."""
    return jsonify(
        {
            "service": "agentscope",
            "version": __version__,
            "api_version": API_VERSION,
            "supported_api_versions": list(SUPPORTED_API_VERSIONS),
        }
    )


@meta_bp.get("/openapi.json")
def openapi():
    """Serve the OpenAPI 3.0 document describing this API."""
    return jsonify(get_spec())


@meta_bp.get("/docs")
def docs():
    """Render Swagger UI pointed at the sibling ``openapi.json`` on this mount."""
    # Derive the spec URL from the current path so it works under both the
    # ``/api`` and ``/api/v1`` mounts without knowing which one served us.
    spec_url = request.path.rsplit("/", 1)[0] + "/openapi.json"
    return Response(swagger_ui_html(spec_url), mimetype="text/html")
