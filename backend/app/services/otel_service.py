"""OpenTelemetry (OTLP/HTTP JSON) ingest → AgentScope agent runs.

Lets *any* OpenTelemetry-instrumented app push its GenAI traces to AgentScope
over the standard OTLP/HTTP JSON protocol — no AgentScope SDK required. This is
the vendor-neutral counterpart to the framework callback handlers: tools built
on **OpenLLMetry**, **OpenInference** (Arize), or the OTel **GenAI semantic
conventions** all emit these attributes, so one endpoint covers them.

We translate an OTLP payload into the exact dict shape that
:func:`app.services.ingest_service.ingest_agent_run` already accepts, so all
persistence, redaction and atomicity are reused unchanged:

* one OTLP **trace** (spans sharing a ``traceId``) -> one **agent run**
* each span -> one **agent step**, classified as llm / retrieval / tool / step
* LLM spans carry model, prompt, completion, token usage and (priced) cost
* tool spans attach a ``tool_call``; retriever spans attach a ``retrieval``

Attribute names are read across the three common conventions (GenAI semconv,
OpenLLMetry ``gen_ai.*``/``llm.*``, OpenInference ``*.value``/``token_count.*``)
so the mapping is robust to whichever instrumentation produced the spans.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import pricing
from ..utils.validation import ValidationError
from . import ingest_service

# --- OTLP JSON decoding ------------------------------------------------------


def _first(obj: dict, *keys: str) -> Any:
    """Return the first present, non-None key (tolerates camel/snake variants)."""
    for key in keys:
        if isinstance(obj, dict) and obj.get(key) is not None:
            return obj[key]
    return None


def _value(v: Any) -> Any:
    """Decode an OTLP AnyValue object to a plain Python value."""
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        try:
            return int(v["intValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [_value(x) for x in (v["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in v:
        return {
            kv.get("key"): _value(kv.get("value"))
            for kv in (v["kvlistValue"] or {}).get("values", [])
            if isinstance(kv, dict)
        }
    return None


def _attrs(attr_list: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in attr_list or []:
        if isinstance(item, dict) and item.get("key"):
            out[item["key"]] = _value(item.get("value"))
    return out


def _collect_spans(payload: dict) -> List[dict]:
    """Flatten resourceSpans→scopeSpans→spans, decoding attrs and resource once."""
    spans: List[dict] = []
    resource_spans = _first(payload, "resourceSpans", "resource_spans") or []
    for rs in resource_spans:
        if not isinstance(rs, dict):
            continue
        resource = rs.get("resource") or {}
        resource_attrs = _attrs(resource.get("attributes"))
        scope_spans = _first(rs, "scopeSpans", "scope_spans", "instrumentationLibrarySpans") or []
        for ss in scope_spans:
            if not isinstance(ss, dict):
                continue
            for span in ss.get("spans") or []:
                if not isinstance(span, dict):
                    continue
                span["_attrs"] = _attrs(span.get("attributes"))
                span["_resource"] = resource_attrs
                spans.append(span)
    return spans


# --- GenAI attribute readers (span kind agnostic) ---------------------------


def _span_kind(attrs: dict) -> str:
    kind = (
        attrs.get("openinference.span.kind")
        or attrs.get("traceloop.span.kind")
        or attrs.get("gen_ai.operation.name")
        or ""
    )
    return str(kind).lower()


def _model(attrs: dict) -> Optional[str]:
    value = (
        attrs.get("gen_ai.response.model")
        or attrs.get("gen_ai.request.model")
        or attrs.get("llm.model_name")
        or attrs.get("llm.request.model")
        or attrs.get("model")
    )
    return str(value) if value is not None else None


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _input_tokens(attrs: dict) -> Optional[int]:
    return _int(
        attrs.get("gen_ai.usage.input_tokens")
        if attrs.get("gen_ai.usage.input_tokens") is not None
        else attrs.get("gen_ai.usage.prompt_tokens")
        if attrs.get("gen_ai.usage.prompt_tokens") is not None
        else attrs.get("llm.token_count.prompt")
        if attrs.get("llm.token_count.prompt") is not None
        else attrs.get("llm.usage.prompt_tokens")
    )


def _output_tokens(attrs: dict) -> Optional[int]:
    return _int(
        attrs.get("gen_ai.usage.output_tokens")
        if attrs.get("gen_ai.usage.output_tokens") is not None
        else attrs.get("gen_ai.usage.completion_tokens")
        if attrs.get("gen_ai.usage.completion_tokens") is not None
        else attrs.get("llm.token_count.completion")
        if attrs.get("llm.token_count.completion") is not None
        else attrs.get("llm.usage.completion_tokens")
    )


def _indexed_text(attrs: dict, prefix: str) -> Optional[str]:
    """Join OpenLLMetry-style indexed attrs, e.g. ``gen_ai.prompt.0.content``."""
    items = []
    suffix = ".content"
    for key, val in attrs.items():
        if key.startswith(prefix + ".") and key.endswith(suffix) and val is not None:
            middle = key[len(prefix) + 1 : -len(suffix)]
            try:
                idx = int(middle.split(".")[0])
            except (TypeError, ValueError):
                idx = 0
            items.append((idx, str(val)))
    items.sort()
    return "\n".join(text for _, text in items) if items else None


def _prompt_text(attrs: dict) -> Optional[str]:
    for key in ("input.value", "gen_ai.prompt", "llm.prompts", "prompt"):
        if attrs.get(key) is not None:
            return _stringify(attrs[key])
    return _indexed_text(attrs, "gen_ai.prompt") or _indexed_text(attrs, "llm.input_messages")


def _completion_text(attrs: dict) -> Optional[str]:
    for key in ("output.value", "gen_ai.completion", "gen_ai.response.text", "completion"):
        if attrs.get(key) is not None:
            return _stringify(attrs[key])
    return _indexed_text(attrs, "gen_ai.completion") or _indexed_text(attrs, "llm.output_messages")


def _stringify(value: Any) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    import json

    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


# --- span → step / run mapping ----------------------------------------------


def _duration_ms(span: dict) -> Optional[float]:
    start = _int(_first(span, "startTimeUnixNano", "start_time_unix_nano"))
    end = _int(_first(span, "endTimeUnixNano", "end_time_unix_nano"))
    if start is None or end is None or end < start:
        return None
    return round((end - start) / 1_000_000, 3)


def _is_error(span: dict) -> bool:
    status = span.get("status") or {}
    code = status.get("code")
    return code in (2, "STATUS_CODE_ERROR", "ERROR")


def _classify(attrs: dict) -> str:
    kind = _span_kind(attrs)
    has_llm = (
        _model(attrs) is not None
        or _input_tokens(attrs) is not None
        or _output_tokens(attrs) is not None
    )
    if kind in ("llm", "chat", "completion", "text_completion", "chat_model") or (
        has_llm and kind not in ("embedding", "retriever", "retrieval", "tool")
    ):
        return "llm"
    if kind in ("retriever", "retrieval", "embedding") or _has_retrieval_docs(attrs):
        return "retriever"
    if kind in ("tool", "function") or attrs.get("gen_ai.tool.name") or attrs.get("tool.name"):
        return "tool"
    return "step"


def _has_retrieval_docs(attrs: dict) -> bool:
    return any(k.startswith("retrieval.documents.") for k in attrs)


def _retrieval_documents(attrs: dict) -> List[dict]:
    """Decode OpenInference ``retrieval.documents.{i}.document.*`` attrs."""
    by_index: Dict[int, dict] = {}
    for key, val in attrs.items():
        if not key.startswith("retrieval.documents.") or val is None:
            continue
        rest = key[len("retrieval.documents.") :]
        parts = rest.split(".", 1)
        try:
            idx = int(parts[0])
        except (TypeError, ValueError):
            continue
        field = parts[1] if len(parts) > 1 else ""
        doc = by_index.setdefault(idx, {})
        if field in ("document.content", "content"):
            doc["chunk_text"] = str(val)
        elif field in ("document.score", "score"):
            doc["similarity_score"] = val
        elif field in ("document.id", "id"):
            doc["document_id"] = str(val)
        elif field in ("document.metadata", "metadata"):
            doc["metadata"] = val
    return [by_index[i] for i in sorted(by_index)]


def _build_step(span: dict, step_type: str) -> dict:
    attrs = span["_attrs"]
    latency = _duration_ms(span)
    status = "failed" if _is_error(span) else "success"
    metadata = {
        "otel_span_id": _first(span, "spanId", "span_id"),
        "otel_parent_span_id": _first(span, "parentSpanId", "parent_span_id"),
        "span_kind": _span_kind(attrs) or None,
    }
    system = attrs.get("gen_ai.system")
    if system:
        metadata["gen_ai_system"] = system

    step: Dict[str, Any] = {
        "step_type": {"llm": "llm", "retriever": "retrieval", "tool": "action"}.get(step_type, "reasoning"),
        "name": span.get("name"),
        "status": status,
        "latency_ms": latency,
        "metadata": metadata,
        "input": _prompt_text(attrs),
        "output": _completion_text(attrs),
    }

    if step_type == "llm":
        input_tokens = _input_tokens(attrs)
        output_tokens = _output_tokens(attrs)
        model = _model(attrs)
        if input_tokens is not None or output_tokens is not None:
            step["token_usage"] = {
                "input": input_tokens,
                "output": output_tokens,
                "total": (input_tokens or 0) + (output_tokens or 0),
            }
        step["cost"] = pricing.estimate_cost(model, input_tokens, output_tokens)
        if model:
            metadata["model"] = model
    elif step_type == "tool":
        tool_name = attrs.get("gen_ai.tool.name") or attrs.get("tool.name") or span.get("name") or "tool"
        step["tool_calls"] = [
            {
                "tool_name": str(tool_name),
                "arguments": attrs.get("gen_ai.tool.input") or attrs.get("tool.parameters") or _prompt_text(attrs),
                "result": _completion_text(attrs),
                "status": status,
                "latency_ms": latency,
            }
        ]
    elif step_type == "retriever":
        documents = _retrieval_documents(attrs)
        step["retrievals"] = [
            {
                "query": _prompt_text(attrs) or attrs.get("input.value"),
                "num_documents": len(documents) or None,
                "documents": documents,
                "retrieval_time_ms": latency,
            }
        ]
    return step


def _root_name(spans: List[dict]) -> str:
    ids = {_first(s, "spanId", "span_id") for s in spans}
    for span in spans:
        parent = _first(span, "parentSpanId", "parent_span_id")
        if not parent or parent not in ids:
            attrs = span["_attrs"]
            return (
                span.get("name")
                or attrs.get("gen_ai.agent.name")
                or span["_resource"].get("service.name")
                or "otel-trace"
            )
    return spans[0].get("name") or "otel-trace"


def _build_run(trace_id: str, spans: List[dict]) -> Optional[dict]:
    spans = sorted(spans, key=lambda s: _int(_first(s, "startTimeUnixNano", "start_time_unix_nano")) or 0)
    steps = [_build_step(span, _classify(span["_attrs"])) for span in spans]

    llm_steps = [s for s in steps if s["step_type"] == "llm"]
    input_tokens = sum((s.get("token_usage") or {}).get("input") or 0 for s in llm_steps) or None
    output_tokens = sum((s.get("token_usage") or {}).get("output") or 0 for s in llm_steps) or None
    total_tokens = (input_tokens or 0) + (output_tokens or 0) or None
    costs = [s["cost"] for s in llm_steps if s.get("cost") is not None]
    estimated_cost = round(sum(costs), 8) if costs else None

    first_llm = llm_steps[0] if llm_steps else None
    last_llm = llm_steps[-1] if llm_steps else None
    model_name = (first_llm or {}).get("metadata", {}).get("model") if first_llm else None

    starts = [_int(_first(s, "startTimeUnixNano", "start_time_unix_nano")) for s in spans]
    ends = [_int(_first(s, "endTimeUnixNano", "end_time_unix_nano")) for s in spans]
    starts = [s for s in starts if s is not None]
    ends = [e for e in ends if e is not None]
    latency_ms = round((max(ends) - min(starts)) / 1_000_000, 3) if starts and ends else None

    status = "failed" if any(_is_error(s) for s in spans) else "success"
    resource = spans[0]["_resource"]

    return {
        "agent_name": _root_name(spans),
        "agent_type": "otel",
        "model_name": model_name or "unknown",
        "user_prompt": first_llm.get("input") if first_llm else None,
        "final_response": last_llm.get("output") if last_llm else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "latency_ms": latency_ms,
        "status": status,
        "steps": steps,
        "metadata": {
            "source": "otel",
            "otel_trace_id": trace_id,
            "service_name": resource.get("service.name"),
        },
    }


def ingest_otlp(payload: dict) -> dict:
    """Ingest an OTLP/HTTP JSON trace payload; return an accept summary.

    Groups spans by ``traceId`` and persists one agent run per trace. Unknown /
    non-GenAI spans are still recorded as generic steps so nothing is silently
    dropped. Raises :class:`ValidationError` for a non-object body.
    """
    if not isinstance(payload, dict):
        raise ValidationError("request body must be an OTLP JSON object")

    spans = _collect_spans(payload)
    if not spans:
        return {"accepted_spans": 0, "runs": []}

    groups: Dict[str, List[dict]] = {}
    for span in spans:
        trace_id = _first(span, "traceId", "trace_id") or "unknown"
        groups.setdefault(str(trace_id), []).append(span)

    run_ids = []
    for trace_id, group in groups.items():
        run_dict = _build_run(trace_id, group)
        if run_dict is None:
            continue
        run = ingest_service.ingest_agent_run(run_dict)
        run_ids.append(run.id)

    return {"accepted_spans": len(spans), "accepted_traces": len(groups), "runs": run_ids}
