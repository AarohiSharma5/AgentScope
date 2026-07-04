"""Read-only endpoints for inspecting background jobs (v1.0 optimization)."""
from flask import Blueprint, jsonify

from ..jobs import job_manager

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.get("/jobs")
def list_jobs():
    """List background jobs and their status (most recent first)."""
    jobs = sorted(job_manager.list(), key=lambda j: j.created_at, reverse=True)
    return jsonify({"data": [j.to_dict() for j in jobs]})


@jobs_bp.get("/jobs/<job_id>")
def get_job(job_id: str):
    """Return a single background job by id."""
    job = job_manager.get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job.to_dict())
