"""REST endpoints for RAG / retrieval / prompt-assembly tracing (v0.3).

Routes stay thin: parse and validate input, delegate all querying/aggregation to
the service layer, and shape responses via reusable serializers. No business
logic or SQLAlchemy session access lives here.

Response conventions (shared with the rest of the API):

* Collections -> ``{"data": [...], "pagination": {page, limit, total, pages}}``
* Single resource -> the serialized object directly
* Errors -> ``{"error": message, "details": {...optional}}`` (see ``errors``)
"""
from flask import Blueprint, jsonify, request

from ..errors import error_response
from ..serializers.rag import (
    serialize_prompt_assembly,
    serialize_retrieval_detail,
    serialize_retrieval_summary,
)
from ..services import ingest_service, trace_service
from ..utils.pagination import PaginationError, paginated, parse_page_limit

rag_bp = Blueprint("rag", __name__)


@rag_bp.post("/retrievals")
def create_retrieval():
    """Ingest a single retrieval so it appears in the RAG Observatory.

    Accepts an optional ``request_id`` to link to an existing request trace; when
    omitted, a minimal parent trace is created. The retrieval is wrapped in a thin
    run+step (the RAG Observatory lists retrievals that hang off agent steps).
    Returns the created retrieval with documents, embedding and timeline.
    """
    data = request.get_json(silent=True) or {}
    retrieval = ingest_service.ingest_retrieval(data)
    return jsonify(serialize_retrieval_detail(retrieval)), 201


@rag_bp.get("/retrievals")
def list_retrievals():
    """List retrievals with pagination, search, sorting and filtering."""
    try:
        page, limit = parse_page_limit(request.args)
    except PaginationError as exc:
        return error_response(str(exc), 400)

    q = request.args.get("q")
    if q is not None:
        q = q.strip() or None

    embedding_model = request.args.get("embedding_model")
    if embedding_model is not None:
        embedding_model = embedding_model.strip() or None

    min_documents = request.args.get("min_documents")
    if min_documents is not None:
        try:
            min_documents = int(min_documents)
        except (TypeError, ValueError):
            return error_response("min_documents must be an integer", 400)
        if min_documents < 0:
            return error_response("min_documents must be >= 0", 400)

    sort = request.args.get("sort", "-id")
    if not trace_service.is_valid_retrieval_sort(sort):
        return error_response(
            "invalid sort field",
            400,
            {
                "allowed": sorted(trace_service.RETRIEVAL_SORTABLE),
                "hint": "prefix with '-' for descending, e.g. -num_documents",
            },
        )

    items, total = trace_service.list_retrievals(
        page=page,
        limit=limit,
        q=q,
        sort=sort,
        embedding_model=embedding_model,
        min_documents=min_documents,
    )
    return jsonify(
        paginated([serialize_retrieval_summary(r) for r in items], page, limit, total)
    )


@rag_bp.get("/retrievals/<int:retrieval_id>")
def get_retrieval(retrieval_id: int):
    """Return a retrieval with embedding, documents, scores, selection, prompt, timeline."""
    retrieval = trace_service.get_retrieval(retrieval_id)
    if retrieval is None:
        return error_response("retrieval not found", 404)
    return jsonify(serialize_retrieval_detail(retrieval))


@rag_bp.get("/prompts/<int:prompt_id>")
def get_prompt(prompt_id: int):
    """Return a fully reconstructed prompt (all sections + final prompt)."""
    assembly = trace_service.get_prompt_assembly(prompt_id)
    if assembly is None:
        return error_response("prompt assembly not found", 404)
    return jsonify(serialize_prompt_assembly(assembly))


@rag_bp.get("/dashboard/rag-metrics")
def rag_metrics():
    """Return aggregate RAG metrics for the dashboard."""
    return jsonify(trace_service.get_rag_metrics())
