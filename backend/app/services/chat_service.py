"""The chatbot flow, instrumented end-to-end with the TraceRecorder SDK.

This is the single integration point that turns a raw chat request into a fully
traced agent execution while keeping the v0.1 request Trace (prompt, response,
tokens, latency, cost) intact.

Execution flow::

    Request Received
      -> Start AgentRun
      -> Planner Step
      -> Memory Lookup   (optional)
      -> Retriever       (optional)
      -> Tool Call       (optional)
      -> LLM Generation
      -> Verifier
      -> Finish AgentRun
      -> Store Final Response
      -> Return Response

All tracing is automatic: the caller only builds a ``TraceRecorder(request_id)``
and every phase is a one-line helper. The model, memory, retriever, tools and
verifier are pluggable callables so this works with any provider; sensible
in-process simulators are used by default so the flow is runnable with no keys.
"""
import logging
from time import perf_counter
from typing import Callable, Optional

from ..models.agent_trace import AgentStatus
from ..utils.trace_recorder import TraceRecorder
from . import trace_service

logger = logging.getLogger("agentscope")


def _default_model(payload: dict, context: Optional[dict] = None) -> dict:
    """Deterministic in-process 'LLM' so the flow runs without external calls."""
    prompt = (payload.get("user_prompt") or "").strip()
    model_name = payload.get("model_name", "gpt-4o")
    grounding = ""
    if context and context.get("documents"):
        titles = [d.get("title", "doc") if isinstance(d, dict) else str(d) for d in context["documents"]]
        grounding = f" (grounded in: {', '.join(titles)})"
    response = f"Here is a response to: {prompt}{grounding}"

    input_tokens = max(len(prompt.split()), 1)
    output_tokens = max(len(response.split()), 1)
    return {
        "response": response,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": trace_service.estimate_cost(model_name, input_tokens, output_tokens),
    }


def _default_memory(prompt: str) -> dict:
    return {
        "retrieved_text": f"Recalled prior context relevant to: {prompt}",
        "similarity_score": 0.86,
        "used": True,
    }


def _default_retriever(prompt: str) -> dict:
    return {
        "documents": [
            {"title": "Reference A", "source": "chroma"},
            {"title": "Reference B", "source": "pinecone"},
        ],
        "embedding_time_ms": 11.5,
        "retrieval_time_ms": 38.2,
    }


def run_chat(
    payload: dict,
    *,
    model: Callable[[dict, Optional[dict]], dict] = _default_model,
    memory: Optional[Callable[[str], dict]] = _default_memory,
    retriever: Optional[Callable[[str], dict]] = _default_retriever,
    tools: Optional[list[dict]] = None,
    verifier: Optional[Callable[[str], str]] = None,
    agent_name: str = "Chatbot",
) -> dict:
    """Handle one chat request, tracing the full agent flow automatically.

    ``payload`` should contain ``user_prompt`` and optionally ``system_prompt``
    and ``model_name``. Pass ``None`` for ``memory``/``retriever`` to skip those
    optional phases; ``tools`` is a list of ``{"name", "arguments", "run"?}``.
    """
    started = perf_counter()
    user_prompt = payload.get("user_prompt")
    system_prompt = payload.get("system_prompt")
    model_name = payload.get("model_name", "gpt-4o")

    # Request Received -> create the v0.1 request Trace (prompt/model now,
    # response/tokens/cost stored once the flow completes).
    trace = trace_service.create_trace(
        {
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
            "model_name": model_name,
        }
    )

    # A developer only needs this one line; helpers handle the rest.
    recorder = TraceRecorder(trace.id)
    run = recorder.begin(agent_name=agent_name, agent_type="chatbot", metadata={"model": model_name})

    try:
        # Planner
        recorder.planner(
            input=user_prompt,
            output=f"Break down and answer the user's question: {user_prompt}",
        )

        # Memory Lookup (optional)
        if memory is not None:
            recorder.memory_lookup(query=user_prompt, work=lambda: memory(user_prompt))

        # Retriever (optional)
        context = None
        if retriever is not None:
            context = recorder.retriever(query=user_prompt, work=lambda: retriever(user_prompt))

        # Tool Call (optional)
        for tool in tools or []:
            recorder.tool_call(
                tool_name=tool["name"],
                arguments=tool.get("arguments"),
                work=tool.get("run"),
                result=tool.get("result"),
            )

        # LLM Generation
        llm_result = recorder.llm_generation(
            input=user_prompt,
            work=lambda: model(payload, context if isinstance(context, dict) else None),
        )
        response_text = (
            llm_result.get("response") if isinstance(llm_result, dict) else str(llm_result)
        )
        token_usage = None
        cost = None
        if isinstance(llm_result, dict):
            it, ot = llm_result.get("input_tokens"), llm_result.get("output_tokens")
            token_usage = {"input": it, "output": ot, "total": (it or 0) + (ot or 0)}
            cost = llm_result.get("cost")

        # Verifier
        recorder.verifier(
            input=response_text,
            work=(lambda: verifier(response_text)) if verifier else None,
            output=None if verifier else "Response verified: coherent and grounded.",
        )
    except Exception as exc:  # noqa: BLE001 - finalize the trace, then re-raise
        latency_ms = round((perf_counter() - started) * 1000, 2)
        recorder.complete(
            status=AgentStatus.FAILED,
            latency_ms=latency_ms,
            metadata={"error": f"{type(exc).__name__}: {exc}"},
        )
        raise

    # Finish AgentRun + Store Final Response on the request Trace.
    latency_ms = round((perf_counter() - started) * 1000, 2)
    recorder.complete(
        status=AgentStatus.SUCCESS,
        final_response=response_text,
        token_usage=token_usage,
        cost=cost,
        latency_ms=latency_ms,
    )

    logger.info(
        "Chat handled: request_id=%s run_id=%s latency_ms=%s", trace.id, run.id, latency_ms
    )

    # Return Response
    return {
        "request_id": trace.id,
        "agent_run_id": run.id,
        "response": response_text,
        "model_name": model_name,
        "usage": token_usage,
        "cost": cost,
        "latency_ms": latency_ms,
        "status": "success",
    }
