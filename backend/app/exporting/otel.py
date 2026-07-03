"""Convert a conversation bundle into OpenTelemetry (OTLP/JSON) trace data.

The output is an OTLP ``TracesData`` document (``resourceSpans`` -> ``scopeSpans``
-> ``spans``) that can be posted to any OpenTelemetry collector. Attributes
follow the OpenTelemetry **GenAI semantic conventions** where they apply:

* ``gen_ai.system`` / ``gen_ai.request.model`` — the provider/model.
* ``gen_ai.usage.input_tokens`` / ``gen_ai.usage.output_tokens``.
* ``gen_ai.operation.name`` — e.g. ``chat`` / ``execute_tool`` / ``embeddings``.
* ``gen_ai.tool.name`` for tool spans.

The conversation/agent/step hierarchy maps onto the span parent/child tree so a
traced run renders as a familiar waterfall in Jaeger/Tempo/etc. Timestamps are
approximate (start times are not persisted per step), so spans are laid out
sequentially from the conversation start using recorded latencies.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from .bundle import BundleError, BundleKind

_SCOPE_NAME = "agentscope"
_SCOPE_VERSION = "0.6"

# OTLP SpanKind enum values.
_SPAN_KIND_INTERNAL = 1
_SPAN_KIND_CLIENT = 3


def _hex_id(*parts: Any, length: int = 16) -> str:
    """Deterministic hex span/trace id from ``parts`` (stable across exports)."""
    seed = "/".join(str(p) for p in parts).encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[: length * 2]


def _attr(key: str, value: Any) -> Optional[dict]:
    """Render one OTLP KeyValue attribute, or None when the value is empty."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": value}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _attrs(pairs: dict) -> list[dict]:
    """Render a dict into a list of non-empty OTLP attributes."""
    return [a for a in (_attr(k, v) for k, v in pairs.items()) if a is not None]


def _ns(ms: float) -> int:
    """Milliseconds since epoch-ish origin -> unix nanoseconds."""
    return int(ms * 1_000_000)


class _Clock:
    """Lays out spans sequentially from a base time using recorded latencies."""

    def __init__(self, base_ms: float = 0.0) -> None:
        self.cursor = base_ms

    def span(self, latency_ms: Optional[float]) -> tuple[int, int]:
        start = self.cursor
        duration = latency_ms if latency_ms and latency_ms > 0 else 1.0
        self.cursor += duration
        # Offset by a large fixed origin so nanos are plausible wall-clock values.
        origin = 1_700_000_000_000  # ~2023-11 in ms
        return _ns(origin + start), _ns(origin + start + duration)


def conversation_to_otel(bundle: dict) -> dict:
    """Convert a conversation bundle into an OTLP ``TracesData`` document."""
    if bundle["manifest"]["kind"] != BundleKind.CONVERSATION:
        raise BundleError("OpenTelemetry export is only supported for conversations")

    payload = bundle["payload"]
    snapshot = payload.get("snapshot") or {}
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id") or bundle["manifest"].get("entity_id") or "conv"
    trace_id = _hex_id("conversation", conversation_id, length=16)
    request_model = snapshot.get("request_model")

    clock = _Clock()
    spans: list[dict] = []

    conversation_span_id = _hex_id("conv-span", conversation_id, length=8)
    conv_start, conv_end = clock.span(conversation.get("latency_ms"))
    spans.append(
        _span(
            trace_id, conversation_span_id, None,
            name=f"conversation {conversation.get('conversation_name') or conversation_id}",
            kind=_SPAN_KIND_INTERNAL, start=conv_start, end=conv_end,
            attributes=_attrs({
                "gen_ai.operation.name": "chain",
                "gen_ai.system": "agentscope",
                "gen_ai.request.model": request_model,
                "agentscope.conversation.id": conversation_id,
                "agentscope.conversation.status": conversation.get("status"),
            }),
            status_ok=conversation.get("status") != "failed",
        )
    )

    span_ids_by_node: dict[Any, str] = {}
    for node in snapshot.get("nodes", []):
        _emit_node_spans(
            spans, trace_id, conversation_span_id, node, request_model, clock, span_ids_by_node
        )

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _attrs(
                        {"service.name": "agentscope", "service.version": _SCOPE_VERSION}
                    )
                },
                "scopeSpans": [
                    {
                        "scope": {"name": _SCOPE_NAME, "version": _SCOPE_VERSION},
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def _emit_node_spans(spans, trace_id, root_span_id, node, request_model, clock, span_ids_by_node):
    """Emit an agent span and its step/tool/retriever child spans."""
    node_id = node.get("node_id")
    parent_span_id = span_ids_by_node.get(node.get("parent_node_id"), root_span_id)
    node_span_id = _hex_id("node-span", trace_id, node_id, length=8)
    span_ids_by_node[node_id] = node_span_id

    node_start = clock.cursor
    node_span_index = len(spans)
    spans.append(
        _span(
            trace_id, node_span_id, parent_span_id,
            name=f"agent {node.get('name') or node.get('role') or node_id}",
            kind=_SPAN_KIND_INTERNAL, start=0, end=0,  # patched after children
            attributes=_attrs({
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": node.get("name"),
                "gen_ai.agent.role": node.get("role"),
                "gen_ai.request.model": request_model,
            }),
        )
    )

    for index, step in enumerate(node.get("steps", [])):
        _emit_step_spans(spans, trace_id, node_span_id, node_id, index, step, request_model, clock)

    # The agent span brackets its children.
    origin_start, origin_end = _bracket(clock, node_start)
    spans[node_span_index]["startTimeUnixNano"] = origin_start
    spans[node_span_index]["endTimeUnixNano"] = origin_end


def _emit_step_spans(spans, trace_id, node_span_id, node_id, index, step, request_model, clock):
    """Emit a step span plus tool/retriever child spans following GenAI conventions."""
    usage = step.get("token_usage") or {}
    step_span_id = _hex_id("step-span", trace_id, node_id, index, length=8)
    start, end = clock.span(_infer_step_latency(step))
    spans.append(
        _span(
            trace_id, step_span_id, node_span_id,
            name=f"{step.get('step_type') or 'step'} {step.get('name') or index}",
            kind=_SPAN_KIND_CLIENT, start=start, end=end,
            attributes=_attrs({
                "gen_ai.operation.name": "chat",
                "gen_ai.system": "agentscope",
                "gen_ai.request.model": request_model,
                "gen_ai.usage.input_tokens": usage.get("input"),
                "gen_ai.usage.output_tokens": usage.get("output"),
                "agentscope.step.type": step.get("step_type"),
                "agentscope.step.cost": step.get("cost"),
            }),
        )
    )

    for tool_index, tool in enumerate(step.get("tools", [])):
        t_start, t_end = clock.span(tool.get("latency_ms"))
        spans.append(
            _span(
                trace_id, _hex_id("tool-span", trace_id, node_id, index, tool_index, length=8),
                step_span_id,
                name=f"execute_tool {tool.get('tool_name')}",
                kind=_SPAN_KIND_INTERNAL, start=t_start, end=t_end,
                attributes=_attrs({
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": tool.get("tool_name"),
                    "agentscope.tool.status": tool.get("status"),
                }),
                status_ok=tool.get("status") != "failed",
            )
        )

    for retr_index, retr in enumerate(step.get("retrievers", [])):
        r_start, r_end = clock.span(retr.get("retrieval_time_ms"))
        spans.append(
            _span(
                trace_id, _hex_id("retr-span", trace_id, node_id, index, retr_index, length=8),
                step_span_id,
                name="retrieve",
                kind=_SPAN_KIND_CLIENT, start=r_start, end=r_end,
                attributes=_attrs({
                    "gen_ai.operation.name": "retrieve",
                    "agentscope.retrieval.documents": retr.get("num_documents"),
                    "agentscope.retrieval.embedding_time_ms": retr.get("embedding_time_ms"),
                }),
            )
        )


def _infer_step_latency(step: dict) -> float:
    """A step's own latency, defaulting to a small nominal span."""
    meta = step.get("token_usage") or {}
    return meta.get("latency_ms") or 1.0


def _bracket(clock: "_Clock", start_ms: float) -> tuple[int, int]:
    """Return (start, end) nanos bracketing everything emitted since ``start_ms``."""
    origin = 1_700_000_000_000
    return _ns(origin + start_ms), _ns(origin + max(clock.cursor, start_ms + 1))


def _span(trace_id, span_id, parent_span_id, *, name, kind, start, end, attributes, status_ok=True):
    """Build one OTLP span dict."""
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": attributes,
        "status": {"code": 1 if status_ok else 2},  # 1=OK, 2=ERROR
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return span
