"""Hand-maintained OpenAPI 3.0 description of the AgentScope HTTP API.

The route serializers are hand-rolled dicts rather than schema objects, so this
document is the single, reviewable source of truth for the API contract: the
shared envelopes (``{error, details}`` and ``{data, pagination}``), the auth
flow, and the primary read/ingest endpoints. It is served at
``/api/openapi.json`` (and ``/api/v1/openapi.json``) and rendered by the Swagger
UI at ``/api/docs``.

Keep this in sync when routes or their response shapes change; it is small and
intentionally close to the code it documents.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .version import API_VERSION, __version__

_ref = lambda name: {"$ref": f"#/components/schemas/{name}"}  # noqa: E731


def _paginated(item_schema_name: str) -> dict[str, Any]:
    """An envelope schema wrapping a page of ``item_schema_name`` items."""
    return {
        "type": "object",
        "required": ["data", "pagination"],
        "properties": {
            "data": {"type": "array", "items": _ref(item_schema_name)},
            "pagination": _ref("Pagination"),
        },
    }


def _list_op(tag: str, summary: str, item_schema_name: str, *, searchable: bool = True) -> dict[str, Any]:
    params = [
        {"$ref": "#/components/parameters/Page"},
        {"$ref": "#/components/parameters/Limit"},
        {"$ref": "#/components/parameters/Sort"},
    ]
    if searchable:
        params.append({"$ref": "#/components/parameters/Query"})
    return {
        "tags": [tag],
        "summary": summary,
        "parameters": params,
        "responses": {
            "200": {
                "description": "A page of results.",
                "content": {"application/json": {"schema": _paginated(item_schema_name)}},
            },
            "400": {"$ref": "#/components/responses/BadRequest"},
        },
    }


def _get_op(tag: str, summary: str, item_schema_name: str) -> dict[str, Any]:
    return {
        "tags": [tag],
        "summary": summary,
        "parameters": [{"$ref": "#/components/parameters/IdPath"}],
        "responses": {
            "200": {
                "description": "The requested resource.",
                "content": {"application/json": {"schema": _ref(item_schema_name)}},
            },
            "404": {"$ref": "#/components/responses/NotFound"},
        },
    }


def _spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "AgentScope API",
            "version": __version__,
            "description": (
                "Observability API for LLM requests, agent runs, RAG retrievals, "
                "multi-agent workflows, replays and evaluations.\n\n"
                "All list endpoints share the `{data, pagination}` envelope and all "
                "errors share the `{error, details}` envelope. Requests may use the "
                "versioned prefix `/api/v1` or the unversioned alias `/api`, which "
                f"currently maps to `{API_VERSION}`."
            ),
        },
        "servers": [
            {"url": "/api/v1", "description": "Current API version (recommended)."},
            {"url": "/api", "description": "Unversioned alias for the current version."},
        ],
        "tags": [
            {"name": "Meta", "description": "Health, version and API metadata."},
            {"name": "Auth", "description": "Registration, login and token lifecycle."},
            {"name": "Traces", "description": "v0.1 LLM request traces."},
            {"name": "Agent Runs", "description": "v0.2 agent execution traces."},
            {"name": "RAG", "description": "v0.3 retrievals and prompt assembly."},
            {"name": "Workflows", "description": "v0.4 multi-agent workflows and conversations."},
            {"name": "Evaluations", "description": "v0.5 replays, evaluations and comparisons."},
        ],
        "security": [{"bearerAuth": []}, {"apiKey": []}, {}],
        "paths": _paths(),
        "components": _components(),
    }


def _paths() -> dict[str, Any]:
    return {
        "/health": {
            "get": {
                "tags": ["Meta"],
                "summary": "Liveness probe.",
                "security": [{}],
                "responses": {
                    "200": {
                        "description": "Service is up.",
                        "content": {"application/json": {"schema": _ref("Health")}},
                    }
                },
            }
        },
        "/version": {
            "get": {
                "tags": ["Meta"],
                "summary": "Service and API version metadata.",
                "security": [{}],
                "responses": {
                    "200": {
                        "description": "Version metadata.",
                        "content": {"application/json": {"schema": _ref("Version")}},
                    }
                },
            }
        },
        "/auth/register": {
            "post": {
                "tags": ["Auth"],
                "summary": "Create the first user / register an account.",
                "security": [{}],
                "requestBody": {"$ref": "#/components/requestBodies/Credentials"},
                "responses": {
                    "201": {
                        "description": "Account created; returns the session tokens.",
                        "content": {"application/json": {"schema": _ref("Session")}},
                    },
                    "400": {"$ref": "#/components/responses/BadRequest"},
                },
            }
        },
        "/auth/login": {
            "post": {
                "tags": ["Auth"],
                "summary": "Exchange credentials for access and refresh tokens.",
                "security": [{}],
                "requestBody": {"$ref": "#/components/requestBodies/Credentials"},
                "responses": {
                    "200": {
                        "description": "Authenticated; returns the session tokens.",
                        "content": {"application/json": {"schema": _ref("Session")}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            }
        },
        "/auth/refresh": {
            "post": {
                "tags": ["Auth"],
                "summary": "Rotate a refresh token for a fresh access token.",
                "security": [{}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["refresh_token"],
                                "properties": {"refresh_token": {"type": "string"}},
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "New token bundle (the old refresh token is revoked).",
                        "content": {"application/json": {"schema": _ref("Session")}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            }
        },
        "/auth/me": {
            "get": {
                "tags": ["Auth"],
                "summary": "Return the authenticated user.",
                "responses": {
                    "200": {
                        "description": "The current user.",
                        "content": {"application/json": {"schema": _ref("User")}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            }
        },
        "/stats": {
            "get": {
                "tags": ["Traces"],
                "summary": "Aggregate request/token/cost metrics.",
                "responses": {
                    "200": {
                        "description": "Dashboard summary metrics.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/traces": {
            "get": _list_op("Traces", "List LLM request traces.", "Trace"),
            "post": {
                "tags": ["Traces"],
                "summary": "Ingest an LLM request trace.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": _ref("TraceInput")}},
                },
                "responses": {
                    "201": {
                        "description": "Trace stored.",
                        "content": {"application/json": {"schema": _ref("Trace")}},
                    },
                    "400": {"$ref": "#/components/responses/BadRequest"},
                },
            },
        },
        "/traces/{id}": {"get": _get_op("Traces", "Fetch a single trace.", "Trace")},
        "/agent-runs": {"get": _list_op("Agent Runs", "List agent execution runs.", "AgentRun")},
        "/agent-runs/{id}": {"get": _get_op("Agent Runs", "Fetch a single agent run.", "AgentRun")},
        "/retrievals": {"get": _list_op("RAG", "List RAG retrievals.", "Retrieval")},
        "/retrievals/{id}": {"get": _get_op("RAG", "Fetch a single retrieval.", "Retrieval")},
        "/otel/v1/traces": {
            "post": {
                "tags": ["Agent Runs"],
                "summary": "Ingest OpenTelemetry (OTLP/HTTP JSON) traces.",
                "description": (
                    "Accepts OTLP/HTTP JSON trace payloads from any OpenTelemetry-"
                    "instrumented app (OTel GenAI semconv, OpenLLMetry, OpenInference). "
                    "Each trace becomes an agent run; GenAI spans become steps."
                ),
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "responses": {
                    "200": {
                        "description": "Accepted; OTLP-style partialSuccess plus an accept summary.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "400": {"$ref": "#/components/responses/BadRequest"},
                },
            }
        },
        "/workflows": {"get": _list_op("Workflows", "List multi-agent workflows.", "Workflow")},
        "/workflows/{id}": {"get": _get_op("Workflows", "Fetch a single workflow.", "Workflow")},
        "/conversations": {"get": _list_op("Workflows", "List conversations.", "Conversation")},
        "/conversations/{id}": {
            "get": _get_op("Workflows", "Fetch a single conversation.", "Conversation")
        },
        "/evaluations": {"get": _list_op("Evaluations", "List evaluations.", "Evaluation")},
        "/evaluations/{id}": {
            "get": _get_op("Evaluations", "Fetch a single evaluation.", "Evaluation")
        },
        "/replays": {"get": _list_op("Evaluations", "List replays.", "Replay")},
        "/replays/{id}": {"get": _get_op("Evaluations", "Fetch a single replay.", "Replay")},
    }


def _components() -> dict[str, Any]:
    obj = {"type": "object", "additionalProperties": True}
    return {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        },
        "parameters": {
            "Page": {
                "name": "page",
                "in": "query",
                "description": "1-based page number.",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
            },
            "Limit": {
                "name": "limit",
                "in": "query",
                "description": "Page size (bounded server-side).",
                "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "Sort": {
                "name": "sort",
                "in": "query",
                "description": "Sort field, prefixed with '-' for descending (e.g. '-created_at').",
                "schema": {"type": "string"},
            },
            "Query": {
                "name": "q",
                "in": "query",
                "description": "Free-text search filter.",
                "schema": {"type": "string"},
            },
            "IdPath": {
                "name": "id",
                "in": "path",
                "required": True,
                "schema": {"type": "integer"},
            },
        },
        "requestBodies": {
            "Credentials": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["email", "password"],
                            "properties": {
                                "email": {"type": "string", "format": "email"},
                                "password": {"type": "string", "format": "password"},
                            },
                        }
                    }
                },
            }
        },
        "responses": {
            "BadRequest": {
                "description": "Malformed request.",
                "content": {"application/json": {"schema": _ref("Error")}},
            },
            "Unauthorized": {
                "description": "Missing or invalid credentials.",
                "content": {"application/json": {"schema": _ref("Error")}},
            },
            "NotFound": {
                "description": "Resource not found.",
                "content": {"application/json": {"schema": _ref("Error")}},
            },
        },
        "schemas": {
            "Error": {
                "type": "object",
                "required": ["error"],
                "properties": {
                    "error": {"type": "string", "description": "Human-readable message."},
                    "details": {
                        "type": "object",
                        "nullable": True,
                        "additionalProperties": True,
                        "description": "Optional field-level or contextual detail.",
                    },
                },
            },
            "Pagination": {
                "type": "object",
                "required": ["page", "limit", "total", "pages"],
                "properties": {
                    "page": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "total": {"type": "integer"},
                    "pages": {"type": "integer"},
                },
            },
            "Health": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "ok"},
                    "service": {"type": "string", "example": "agentscope"},
                },
            },
            "Version": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "example": "agentscope"},
                    "version": {"type": "string", "example": __version__},
                    "api_version": {"type": "string", "example": API_VERSION},
                    "supported_api_versions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "Session": {
                "type": "object",
                "properties": {
                    "user": _ref("User"),
                    "tokens": _ref("TokenBundle"),
                },
            },
            "TokenBundle": {
                "type": "object",
                "properties": {
                    "access_token": {"type": "string"},
                    "refresh_token": {"type": "string"},
                    "token_type": {"type": "string", "example": "bearer"},
                    "expires_in": {"type": "integer"},
                },
            },
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "email": {"type": "string", "format": "email"},
                    "role": {"type": "string"},
                },
            },
            # The read models are hand-rolled dicts today, so they are documented
            # as open objects with the stable id/timestamp keys every serializer
            # includes. Tighten these as serializers are formalized.
            "TraceInput": {
                "type": "object",
                "required": ["model", "prompt"],
                "properties": {
                    "model": {"type": "string"},
                    "prompt": {"type": "string"},
                    "response": {"type": "string"},
                    "status": {"type": "string"},
                },
                "additionalProperties": True,
            },
            "Trace": obj,
            "AgentRun": obj,
            "Retrieval": obj,
            "Workflow": obj,
            "Conversation": obj,
            "Evaluation": obj,
            "Replay": obj,
        },
    }


_CACHED_SPEC: dict[str, Any] | None = None


def get_spec() -> dict[str, Any]:
    """Return the OpenAPI document (built once and cached, returned as a copy)."""
    global _CACHED_SPEC
    if _CACHED_SPEC is None:
        _CACHED_SPEC = _spec()
    return deepcopy(_CACHED_SPEC)


# Minimal, dependency-free Swagger UI shell loaded from a CDN. Kept as a template
# so the spec URL can be injected for either the versioned or unversioned mount.
_SWAGGER_UI_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AgentScope API — Reference</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js" crossorigin></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: "__SPEC_URL__",
        dom_id: "#swagger-ui",
        deepLinking: true,
      });
    </script>
  </body>
</html>"""


def swagger_ui_html(spec_url: str) -> str:
    """Return a Swagger UI page pointed at ``spec_url``."""
    return _SWAGGER_UI_TEMPLATE.replace("__SPEC_URL__", spec_url)
