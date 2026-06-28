"""REST API endpoints for traces and dashboard stats."""
from flask import Blueprint, jsonify, request

from ..services import trace_service

traces_bp = Blueprint("traces", __name__)


@traces_bp.post("/traces")
def create_trace():
    """Ingest a new LLM request trace."""
    data = request.get_json(silent=True) or {}
    if not data.get("model_name"):
        return jsonify({"error": "model_name is required"}), 400

    trace = trace_service.create_trace(data)
    return jsonify(trace.to_dict()), 201


@traces_bp.get("/traces")
def list_traces():
    """List traces (most recent first) with simple pagination."""
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    traces = trace_service.list_traces(limit=limit, offset=offset)
    return jsonify([t.to_dict() for t in traces])


@traces_bp.get("/traces/<int:trace_id>")
def get_trace(trace_id: int):
    """Fetch a single trace with all captured fields."""
    trace = trace_service.get_trace(trace_id)
    if trace is None:
        return jsonify({"error": "trace not found"}), 404
    return jsonify(trace.to_dict())


@traces_bp.get("/stats")
def get_stats():
    """Return aggregate dashboard metrics."""
    return jsonify(trace_service.get_stats())
