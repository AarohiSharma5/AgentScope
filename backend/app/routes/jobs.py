"""Read-only endpoints for inspecting background jobs (v1.0 optimization).

Jobs are a process-global, cross-tenant view (they are not org-scoped), so both
endpoints require an administrative principal when auth is enforced.
"""
from flask import Blueprint, jsonify

from ..auth import require_admin
from ..jobs import job_manager

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.get("/jobs")
@require_admin
def list_jobs():
    """List background jobs and their status (most recent first)."""
    jobs = sorted(job_manager.list(), key=lambda j: j.created_at, reverse=True)
    return jsonify({"data": [j.to_dict() for j in jobs]})


@jobs_bp.get("/jobs/<job_id>")
@require_admin
def get_job(job_id: str):
    """Return a single background job by id."""
    job = job_manager.get(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job.to_dict())
