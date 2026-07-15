"""REST API for the plugin system (v0.6) — additive, no existing route changed.

Exposes installed plugins, their lifecycle and the contributions they provide so
tools/dashboards (and the frontend) can discover extensions at runtime:

* ``GET    /api/plugins``                     — list installed plugins.
* ``GET    /api/plugins/<name>``              — one plugin's record.
* ``GET    /api/plugins/extensions``          — contributions (``?capability=``).
* ``POST   /api/plugins/<name>/enable``       — enable a plugin.
* ``POST   /api/plugins/<name>/disable``      — disable a plugin.
* ``POST   /api/plugins/<name>/reload``       — reload a plugin.
* ``DELETE /api/plugins/<name>``              — uninstall a plugin.
"""
import logging

from flask import Blueprint, jsonify, request

from ..auth import require_admin
from ..plugins import (
    ALL_CAPABILITIES,
    Capability,
    PluginDependencyError,
    PluginError,
    PluginNotFoundError,
    plugin_manager,
    plugin_registry,
)
from ..plugins.base import Contribution

logger = logging.getLogger("agentscope")

plugins_bp = Blueprint("plugins", __name__)


def _serialize_contribution(contribution: Contribution) -> dict:
    """Serialize a contribution safely (objects may not be JSON-serializable)."""
    data = {
        "capability": contribution.capability,
        "name": contribution.name,
        "plugin": contribution.plugin,
        "metadata": contribution.metadata,
    }
    # UI-extension objects are plain JSON descriptors; include them directly.
    if contribution.capability == Capability.UI_EXTENSION:
        data["descriptor"] = contribution.obj
    else:
        data["provides"] = type(contribution.obj).__name__
    return data


@plugins_bp.get("/plugins")
def list_plugins():
    """List installed plugins with their metadata and lifecycle state."""
    return jsonify({"plugins": [record.to_dict() for record in plugin_manager.list_plugins()]})


@plugins_bp.get("/plugins/extensions")
def list_extensions():
    """List registered contributions, optionally filtered by ``?capability=``."""
    capability = request.args.get("capability")
    if capability is not None and capability not in ALL_CAPABILITIES:
        return (
            jsonify({"error": f"unknown capability '{capability}'",
                     "capabilities": sorted(ALL_CAPABILITIES)}),
            400,
        )
    contributions = plugin_registry.all_contributions()
    if capability:
        contributions = [c for c in contributions if c.capability == capability]
    return jsonify({"extensions": [_serialize_contribution(c) for c in contributions]})


@plugins_bp.get("/plugins/<name>")
def get_plugin(name: str):
    """Return a single plugin's record, or 404."""
    try:
        return jsonify(plugin_manager.get(name).to_dict())
    except PluginNotFoundError:
        return jsonify({"error": f"plugin '{name}' not found"}), 404


@plugins_bp.post("/plugins/<name>/enable")
@require_admin
def enable_plugin(name: str):
    try:
        record = plugin_manager.enable(name)
        return jsonify(record.to_dict())
    except PluginNotFoundError:
        return jsonify({"error": f"plugin '{name}' not found"}), 404
    except PluginDependencyError as exc:
        return jsonify({"error": str(exc)}), 409
    except PluginError as exc:
        return jsonify({"error": str(exc)}), 400


@plugins_bp.post("/plugins/<name>/disable")
@require_admin
def disable_plugin(name: str):
    # Cascade to dependents by default; ?cascade=false disables only this plugin.
    cascade = request.args.get("cascade", "true").lower() != "false"
    try:
        record = plugin_manager.disable(name, cascade=cascade)
        return jsonify(record.to_dict())
    except PluginNotFoundError:
        return jsonify({"error": f"plugin '{name}' not found"}), 404


@plugins_bp.post("/plugins/<name>/reload")
@require_admin
def reload_plugin(name: str):
    try:
        record = plugin_manager.reload(name)
        return jsonify(record.to_dict())
    except PluginNotFoundError:
        return jsonify({"error": f"plugin '{name}' not found"}), 404
    except PluginError as exc:
        return jsonify({"error": str(exc)}), 400


@plugins_bp.delete("/plugins/<name>")
@require_admin
def uninstall_plugin(name: str):
    try:
        plugin_manager.uninstall(name)
        return jsonify({"status": "uninstalled", "name": name})
    except PluginNotFoundError:
        return jsonify({"error": f"plugin '{name}' not found"}), 404
