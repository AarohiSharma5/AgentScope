"""OpenTelemetry (OTLP/HTTP JSON) trace ingest.

Exposes ``POST /api/otel/v1/traces`` so any OpenTelemetry-instrumented app —
OpenLLMetry, OpenInference (Arize), or OTel GenAI-semconv exporters — can push
GenAI traces to AgentScope over the standard OTLP/HTTP JSON protocol, with no
AgentScope SDK. The heavy lifting (span→agent-run mapping) lives in
:mod:`app.services.otel_service`; persistence reuses the agent-run ingest path.

Point an OTLP/HTTP exporter's traces endpoint here, e.g.::

    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8000/api/otel/v1/traces
    OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json
"""
from flask import Blueprint, jsonify

from ..auth import rate_limited
from ..errors import get_json_body
from ..services import otel_service

otel_bp = Blueprint("otel", __name__)


@otel_bp.post("/otel/v1/traces")
@rate_limited(config_key="RATE_LIMIT_INGEST")
def ingest_traces():
    """Ingest an OTLP/HTTP JSON trace payload into agent runs.

    Returns HTTP 200 with an OTLP-style ``partialSuccess`` object (so standard
    OTLP clients are satisfied) plus a small accept summary for humans/debugging.
    """
    payload = get_json_body()
    result = otel_service.ingest_otlp(payload)
    return jsonify({"partialSuccess": {}, **result}), 200
