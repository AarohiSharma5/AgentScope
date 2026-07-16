"""REST API for the provider abstraction (v0.6) — additive, read-only discovery.

* ``GET /api/providers``                  — list providers (``?kind=``/``?capability=``).
* ``GET /api/providers/capabilities``     — capability -> providers map.
* ``GET /api/providers/<name>``           — one provider's static description.
* ``GET /api/providers/<name>/health``    — live health check (may be unconfigured).
"""
import logging

from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..providers import ProviderNotFoundError, provider_registry

logger = logging.getLogger("agentscope")

providers_bp = Blueprint("providers", __name__)


@providers_bp.get("/providers")
def list_providers():
    """List registered providers, optionally filtered by kind/capability."""
    return jsonify(
        {
            "providers": provider_registry.describe(
                kind=request.args.get("kind"),
                capability=request.args.get("capability"),
            )
        }
    )


@providers_bp.get("/providers/capabilities")
def provider_capabilities():
    """Return a map of capability -> providers that support it."""
    return jsonify({"capabilities": provider_registry.capabilities()})


@providers_bp.get("/providers/<name>")
def get_provider(name: str):
    """Return one provider's static description, or 404."""
    try:
        return jsonify(provider_registry.info(name).to_dict())
    except ProviderNotFoundError:
        return error_response(f"provider '{name}' not found", 404)


@providers_bp.get("/providers/<name>/health")
def provider_health(name: str):
    """Instantiate the provider and return a live health check."""
    try:
        provider = provider_registry.create(name)
    except ProviderNotFoundError:
        return error_response(f"provider '{name}' not found", 404)
    status = provider.health_check()
    body = {"provider": name, **status.to_dict()}
    return jsonify(body), 200 if status.configured else 503
