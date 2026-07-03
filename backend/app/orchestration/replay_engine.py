"""Replay engine (v0.5).

Re-runs any previously traced conversation, faithfully reusing its workflow,
agent sequence, prompts, memory, retrieved documents and tool calls — while
letting the caller override the model, temperature, top_p, system prompt,
memory or tools. Every replay:

* produces a brand-new traced :class:`~app.models.workflow_trace.ConversationRun`
  (via the Multi-Agent SDK), so the replay is itself fully observable;
* is recorded as a :class:`~app.models.evaluation_trace.ReplayRun` linked back to
  the original conversation; and
* can be compared against the original with
  :meth:`ReplayEngine.compare`, producing a
  :class:`~app.models.evaluation_trace.ModelComparison`.

Replays run in one of two modes:

* **mock** (default) — deterministic: original outputs and tool results are
  replayed as-is. Overrides that change *inputs* (system prompt, memory, tools)
  are applied; cost is re-estimated for the new model.
* **live** — the caller supplies ``agent_handlers`` (role/name → callable) and/or
  ``tool_handlers`` (tool name → callable) that are actually invoked to produce
  fresh outputs / tool results.

Business logic and persistence live in :mod:`app.services.replay_service`; this
class only orchestrates. Must be used inside a Flask application context.
"""
import json
import logging
from typing import Any, Callable, Optional

from ..models.agent_trace import AgentStatus
from ..services import replay_service, trace_service
from .orchestrator import AgentOrchestrator

logger = logging.getLogger("agentscope")

# A live agent handler receives the reconstructed node snapshot + shared context
# and returns the node's output. A tool handler receives the recorded arguments.
AgentHandler = Callable[..., Any]
ToolHandler = Callable[..., Any]


class ReplayError(Exception):
    """Raised when a conversation cannot be replayed (e.g. it does not exist)."""


class ReplayResult:
    """The outcome of a replay."""

    def __init__(
        self,
        replay_run,
        conversation,
        original_conversation_run_id: int,
        status: str,
        totals: dict,
    ) -> None:
        self.replay_run = replay_run
        self.conversation = conversation
        self.original_conversation_run_id = original_conversation_run_id
        self.status = status
        self.totals = totals

    @property
    def ok(self) -> bool:
        """True when the replay completed successfully."""
        return self.status == AgentStatus.SUCCESS

    @property
    def replay_conversation_run_id(self) -> int:
        """The id of the new conversation produced by the replay."""
        return self.conversation.id

    def __repr__(self) -> str:
        return (
            f"<ReplayResult replay_run_id={self.replay_run.id} "
            f"conversation_id={self.conversation.id} status={self.status}>"
        )


class ReplayEngine:
    """Replays traced conversations under optionally-overridden parameters."""

    def replay(
        self,
        original_conversation_run_id: int,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        system_prompt: Optional[str] = None,
        memory: Optional[Any] = None,
        tools: Optional[dict[str, Any]] = None,
        live: bool = False,
        agent_handlers: Optional[dict[str, AgentHandler]] = None,
        tool_handlers: Optional[dict[str, ToolHandler]] = None,
        conversation_name: Optional[str] = None,
    ) -> ReplayResult:
        """Replay a conversation, returning a :class:`ReplayResult`.

        ``model`` / ``temperature`` / ``top_p`` override the generation
        parameters (and drive cost re-estimation). ``system_prompt`` / ``memory``
        replace the reused system prompt / memory context. ``tools`` maps a tool
        name to a replacement result (mock) or, with ``live=True`` and
        ``tool_handlers`` / ``agent_handlers``, fresh callables are invoked.
        """
        snapshot = replay_service.build_snapshot(original_conversation_run_id)
        if snapshot is None:
            raise ReplayError(
                f"conversation {original_conversation_run_id} not found or has no trace"
            )

        replayed_model = model or snapshot.get("request_model")
        replay_run = replay_service.create_replay_run(
            original_conversation_run_id=original_conversation_run_id,
            replayed_model=replayed_model,
            temperature=temperature,
            top_p=top_p,
            system_prompt_override=system_prompt,
            metadata={"live": live},
        )

        cfg = _ReplayConfig(
            model=replayed_model,
            temperature=temperature,
            top_p=top_p,
            system_prompt=system_prompt,
            memory=memory,
            tools=tools or {},
            live=live,
            agent_handlers=agent_handlers or {},
            tool_handlers=tool_handlers or {},
        )

        orchestrator = AgentOrchestrator(
            conversation_name=conversation_name
            or f"replay of {snapshot.get('conversation_name') or original_conversation_run_id}",
            workflow_definition_id=snapshot.get("workflow_definition_id"),
            metadata={
                "replay_of": original_conversation_run_id,
                "replay_run_id": replay_run.id,
            },
        )

        status = AgentStatus.SUCCESS
        try:
            self._run_nodes(orchestrator, snapshot["nodes"], cfg)
        except Exception:  # noqa: BLE001 - finish trace + replay record, then re-raise
            status = AgentStatus.FAILED
            logger.exception("replay failed for conversation %s", original_conversation_run_id)

        orchestrator.finish(status=status)
        totals = replay_service.conversation_totals(orchestrator.conversation.id)
        replay_service.finish_replay_run(
            replay_run,
            status=status,
            latency_ms=orchestrator.conversation.latency_ms,
            cost=totals["cost"],
            metadata={"replay_conversation_run_id": orchestrator.conversation.id},
        )

        result = ReplayResult(
            replay_run=replay_run,
            conversation=orchestrator.conversation,
            original_conversation_run_id=original_conversation_run_id,
            status=status,
            totals=totals,
        )
        if status == AgentStatus.FAILED:
            raise ReplayError(f"replay {replay_run.id} failed") from None
        return result

    # -- Node replay --------------------------------------------------------

    def _run_nodes(self, orchestrator, nodes: list[dict], cfg: "_ReplayConfig") -> None:
        """Recreate each agent (preserving hierarchy) and replay its work."""
        agents_by_node: dict[int, Any] = {}
        for plan in nodes:
            parent = agents_by_node.get(plan.get("parent_node_id"))
            agent = orchestrator.create_agent(
                name=plan.get("name") or plan.get("role") or f"agent-{plan['node_id']}",
                role=plan.get("role"),
                parent=parent,
                parallel_group=plan.get("parallel_group"),
                metadata={"replay_of_node": plan["node_id"]},
            )
            agents_by_node[plan["node_id"]] = agent
            agent.execute(work=lambda a=agent, p=plan: self._replay_node(a, p, cfg))

    def _replay_node(self, agent, plan: dict, cfg: "_ReplayConfig") -> Any:
        """Replay a single node's prompt, steps, tools, memory and retrievers."""
        recorder = agent.orchestrator.recorder
        run = agent.run

        self._replay_prompt(recorder, run, plan, cfg)

        output = plan.get("output")
        for step_plan in plan.get("steps", []):
            output = self._replay_step(recorder, run, step_plan, cfg) or output

        # A live agent handler may override the node's final output entirely.
        handler = cfg.agent_handlers.get(agent.role) or cfg.agent_handlers.get(agent.name)
        if cfg.live and handler is not None:
            output = handler(plan, agent.context)
        return output

    def _replay_prompt(self, recorder, run, plan: dict, cfg: "_ReplayConfig") -> None:
        """Re-record the node's prompt assembly, applying prompt/memory overrides."""
        prompt = plan.get("prompt")
        if prompt is None and cfg.system_prompt is None and cfg.memory is None:
            return
        prompt = prompt or {}
        memory_context = cfg.memory_context() if cfg.memory is not None else prompt.get("memory_context")
        recorder.record_prompt_assembly(
            run,
            system_prompt=cfg.system_prompt if cfg.system_prompt is not None else prompt.get("system_prompt"),
            conversation_context=prompt.get("conversation_context"),
            retrieved_context=prompt.get("retrieved_context"),
            memory_context=memory_context,
            user_prompt=prompt.get("user_prompt"),
            assembled_prompt=prompt.get("assembled_prompt"),
        )

    def _replay_step(self, recorder, run, step_plan: dict, cfg: "_ReplayConfig") -> Any:
        """Replay one step and its sub-records; returns the (possibly new) output."""
        step = recorder.add_step(
            run,
            step_type=step_plan.get("step_type"),
            name=step_plan.get("name"),
            input=step_plan.get("input"),
            metadata=cfg.generation_metadata(),
        )

        for tool in step_plan.get("tools", []):
            self._replay_tool(recorder, step, tool, cfg)
        for mem in step_plan.get("memory", []):
            recorder.record_memory(
                step,
                memory_type=mem.get("memory_type"),
                query=mem.get("query"),
                retrieved_text=mem.get("retrieved_text"),
                similarity_score=mem.get("similarity_score"),
                used=mem.get("used"),
                latency_ms=mem.get("latency_ms"),
            )
        for retr in step_plan.get("retrievers", []):
            rt = recorder.record_retriever(
                step,
                query=retr.get("query"),
                retrieved_documents=retr.get("retrieved_documents"),
                embedding_time_ms=retr.get("embedding_time_ms"),
                retrieval_time_ms=retr.get("retrieval_time_ms"),
                num_documents=retr.get("num_documents"),
            )
            for doc in retr.get("documents", []):
                recorder.record_retrieved_document(
                    rt,
                    document_id=doc.get("document_id"),
                    document_name=doc.get("document_name"),
                    document_source=doc.get("document_source"),
                    chunk_index=doc.get("chunk_index"),
                    chunk_text=doc.get("chunk_text"),
                    similarity_score=doc.get("similarity_score"),
                    selected=bool(doc.get("selected")),
                )

        output = step_plan.get("output")
        token_usage = step_plan.get("token_usage")
        cost = cfg.recost(token_usage, fallback=step_plan.get("cost"))
        recorder.finish_step(
            step,
            output=output,
            token_usage=token_usage,
            cost=cost,
            metadata=cfg.generation_metadata(),
        )
        return output

    def _replay_tool(self, recorder, step, tool: dict, cfg: "_ReplayConfig") -> None:
        """Replay a tool call, honouring mock overrides and live handlers."""
        name = tool.get("tool_name")
        arguments = tool.get("arguments")
        result = tool.get("result")
        status = tool.get("status", AgentStatus.SUCCESS)

        handler = cfg.tool_handlers.get(name)
        if cfg.live and handler is not None:
            result = _stringify(handler(arguments))
            status = AgentStatus.SUCCESS
        elif name in cfg.tools:
            result = _stringify(cfg.tools[name])

        recorder.record_tool(
            step,
            tool_name=name,
            arguments=arguments,
            result=result,
            status=status,
            latency_ms=tool.get("latency_ms"),
        )

    # -- Comparison ---------------------------------------------------------

    def compare(
        self,
        original_conversation_run_id: int,
        replay: Any,
        model_a: Optional[str] = None,
        model_b: Optional[str] = None,
        winner: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        """Compare an original conversation against a replay of it.

        ``replay`` may be a :class:`ReplayResult`, a ``ReplayRun`` or a replay
        conversation id. Records a
        :class:`~app.models.evaluation_trace.ModelComparison` anchored to the
        original conversation, with cost / latency / token deltas
        (original minus replay). When ``winner`` is not given, the cheaper (then
        faster) side wins.
        """
        replay_conversation_id = self._replay_conversation_id(replay)

        original = replay_service.conversation_totals(original_conversation_run_id)
        replayed = replay_service.conversation_totals(replay_conversation_id)

        cost_diff = _sub(original["cost"], replayed["cost"])
        latency_diff = _sub(original["latency_ms"], replayed["latency_ms"])
        token_diff = _sub(original["total_tokens"], replayed["total_tokens"])
        token_diff = int(token_diff) if token_diff is not None else None

        if winner is None:
            winner, reason = _decide_winner(
                model_a, model_b, original, replayed, cost_diff, latency_diff, reason
            )

        return replay_service.create_model_comparison(
            conversation_run_id=original_conversation_run_id,
            model_a=model_a,
            model_b=model_b,
            winner=winner,
            reason=reason,
            cost_difference=cost_diff,
            latency_difference=latency_diff,
            token_difference=token_diff,
            metadata={
                "replay_conversation_run_id": replay_conversation_id,
                "original_totals": original,
                "replay_totals": replayed,
            },
        )

    @staticmethod
    def _replay_conversation_id(replay: Any) -> int:
        """Resolve a ReplayResult / ReplayRun / id into a replay conversation id."""
        if isinstance(replay, ReplayResult):
            return replay.replay_conversation_run_id
        if isinstance(replay, int):
            return replay
        # A ReplayRun stores the produced conversation id in its metadata.
        meta = getattr(replay, "replay_metadata", None) or {}
        conv_id = meta.get("replay_conversation_run_id")
        if conv_id is None:
            raise ReplayError("cannot resolve replay conversation id from replay run")
        return conv_id


class _ReplayConfig:
    """Resolved replay overrides + small helpers, kept out of the engine body."""

    def __init__(
        self,
        model: Optional[str],
        temperature: Optional[float],
        top_p: Optional[float],
        system_prompt: Optional[str],
        memory: Optional[Any],
        tools: dict,
        live: bool,
        agent_handlers: dict,
        tool_handlers: dict,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.system_prompt = system_prompt
        self.memory = memory
        self.tools = tools
        self.live = live
        self.agent_handlers = agent_handlers
        self.tool_handlers = tool_handlers

    def generation_metadata(self) -> dict:
        """Non-null generation parameters, recorded on each replayed step."""
        meta = {"replayed_model": self.model}
        if self.temperature is not None:
            meta["temperature"] = self.temperature
        if self.top_p is not None:
            meta["top_p"] = self.top_p
        return meta

    def memory_context(self) -> Optional[str]:
        """Render the memory override as a context string."""
        if self.memory is None:
            return None
        if isinstance(self.memory, str):
            return self.memory
        if isinstance(self.memory, (list, tuple)):
            return "\n".join(str(m) for m in self.memory)
        return str(self.memory)

    def recost(self, token_usage: Optional[dict], fallback: Optional[float]) -> Optional[float]:
        """Re-estimate step cost for the replay model, falling back to the original."""
        if isinstance(token_usage, dict) and self.model:
            estimated = trace_service.estimate_cost(
                self.model,
                token_usage.get("input") or 0,
                token_usage.get("output") or 0,
            )
            if estimated is not None:
                return estimated
        return fallback


def _stringify(value: Any) -> Optional[str]:
    """Coerce a tool result to a string for the text column (JSON for structures)."""
    if value is None or isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Subtract two optional numbers, returning None if both are missing."""
    if a is None and b is None:
        return None
    return round((a or 0) - (b or 0), 6)


def _decide_winner(model_a, model_b, original, replayed, cost_diff, latency_diff, reason):
    """Pick a winner by lower cost, breaking ties by lower latency."""
    label_a = model_a or "original"
    label_b = model_b or "replay"
    if cost_diff is not None and cost_diff != 0:
        winner = label_b if cost_diff > 0 else label_a
        return winner, reason or f"lower cost ({winner})"
    if latency_diff is not None and latency_diff != 0:
        winner = label_b if latency_diff > 0 else label_a
        return winner, reason or f"lower latency ({winner})"
    return None, reason or "tie on cost and latency"
