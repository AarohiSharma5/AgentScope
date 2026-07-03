"""Prompt and trace diffing (v0.5).

Two read-only comparison helpers:

* :func:`prompt_diff` performs a word-level diff of two
  :class:`~app.models.evaluation_trace.PromptVersion` snapshots, returning
  segments tagged ``equal`` / ``added`` / ``removed`` / ``modified`` for a
  side-by-side, highlighted UI.
* :func:`trace_diff` compares two traced conversations on their step / tool /
  memory / retriever counts and their latency / cost / token totals, plus a
  node-by-node alignment (with per-node output diffs), reusing the replay
  snapshot so there is no duplicated trace-reconstruction logic.
"""
import re
from difflib import SequenceMatcher
from typing import Optional

from ..services import prompt_service, replay_service

# Split into words and whitespace runs so re-joined segments preserve spacing.
_TOKEN_RE = re.compile(r"\s+|\S+")


def _tokenize(text: Optional[str]) -> list[str]:
    return _TOKEN_RE.findall(text or "")


def diff_segments(a_text: Optional[str], b_text: Optional[str]) -> list[dict]:
    """Word-level diff of two strings as tagged segments.

    Each segment is ``{"op", "a", "b"}`` where ``op`` is ``equal``, ``added``
    (only in B), ``removed`` (only in A) or ``modified`` (replaced).
    """
    a_tokens = _tokenize(a_text)
    b_tokens = _tokenize(b_text)
    matcher = SequenceMatcher(None, a_tokens, b_tokens, autojunk=False)

    segments: list[dict] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        a_part = "".join(a_tokens[i1:i2])
        b_part = "".join(b_tokens[j1:j2])
        if op == "equal":
            segments.append({"op": "equal", "a": a_part, "b": b_part})
        elif op == "insert":
            segments.append({"op": "added", "a": "", "b": b_part})
        elif op == "delete":
            segments.append({"op": "removed", "a": a_part, "b": ""})
        else:  # replace
            segments.append({"op": "modified", "a": a_part, "b": b_part})
    return segments


def _diff_stats(segments: list[dict]) -> dict:
    """Count segments by change type for a quick summary."""
    stats = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}
    for seg in segments:
        if seg["op"] == "equal":
            stats["unchanged"] += 1
        else:
            stats[seg["op"]] += 1
    return stats


def _version_side(version) -> dict:
    """The comparable side of a prompt version for the diff response."""
    return {
        "id": version.id,
        "agent_run_id": version.agent_run_id,
        "version": version.version,
        "hash": version.hash,
        "prompt_text": version.prompt_text,
    }


def prompt_diff(version_a_id: int, version_b_id: int) -> Optional[dict]:
    """Diff two prompt versions, or None if either does not exist."""
    a = prompt_service.get_prompt_version(version_a_id)
    b = prompt_service.get_prompt_version(version_b_id)
    if a is None or b is None:
        return None
    segments = diff_segments(a.prompt_text, b.prompt_text)
    return {
        "a": _version_side(a),
        "b": _version_side(b),
        "identical": a.hash == b.hash,
        "segments": segments,
        "stats": _diff_stats(segments),
    }


# -- Trace diff -------------------------------------------------------------


def _snapshot_counts(snapshot: dict) -> dict:
    """Count steps, tools, memory accesses, retrievers and documents."""
    steps = tools = memory = retrievers = documents = 0
    for node in snapshot["nodes"]:
        for step in node.get("steps", []):
            steps += 1
            tools += len(step.get("tools", []))
            memory += len(step.get("memory", []))
            for retr in step.get("retrievers", []):
                retrievers += 1
                documents += len(retr.get("documents", []))
    return {
        "nodes": len(snapshot["nodes"]),
        "steps": steps,
        "tools": tools,
        "memory": memory,
        "retrievers": retrievers,
        "documents": documents,
    }


def _node_side(node: dict) -> dict:
    """Aggregate a single node for the trace diff (cost/tokens/output)."""
    cost = 0.0
    tokens = 0
    output = node.get("output")
    for step in node.get("steps", []):
        cost += step.get("cost") or 0.0
        usage = step.get("token_usage") or {}
        tokens += usage.get("total") or ((usage.get("input") or 0) + (usage.get("output") or 0))
    return {
        "node_id": node.get("node_id"),
        "role": node.get("role"),
        "name": node.get("name"),
        "steps": len(node.get("steps", [])),
        "cost": round(cost, 6) if cost else None,
        "tokens": tokens or None,
        "output": output,
    }


def _delta(a, b):
    """Difference ``a`` − ``b`` for optional numbers (None if both missing)."""
    if a is None and b is None:
        return None
    return round((a or 0) - (b or 0), 6)


def _metric_row(label, a, b):
    return {"metric": label, "a": a, "b": b, "delta": _delta(a, b)}


def _align_nodes(a_nodes: list[dict], b_nodes: list[dict]) -> list[dict]:
    """Pair nodes positionally, diffing outputs where both sides exist."""
    aligned = []
    for i in range(max(len(a_nodes), len(b_nodes))):
        a = a_nodes[i] if i < len(a_nodes) else None
        b = b_nodes[i] if i < len(b_nodes) else None
        a_side = _node_side(a) if a else None
        b_side = _node_side(b) if b else None
        output_diff = None
        changed = True
        if a_side and b_side:
            same_output = (a_side["output"] or "") == (b_side["output"] or "")
            changed = not (
                same_output
                and a_side["cost"] == b_side["cost"]
                and a_side["tokens"] == b_side["tokens"]
                and a_side["steps"] == b_side["steps"]
            )
            if not same_output:
                output_diff = diff_segments(a_side["output"], b_side["output"])
        aligned.append(
            {"index": i, "a": a_side, "b": b_side, "changed": changed, "output_diff": output_diff}
        )
    return aligned


def trace_diff(conversation_a_id: int, conversation_b_id: int) -> Optional[dict]:
    """Diff two traced conversations, or None if either has no trace."""
    a = replay_service.build_snapshot(conversation_a_id)
    b = replay_service.build_snapshot(conversation_b_id)
    if a is None or b is None:
        return None

    totals_a = replay_service.conversation_totals(conversation_a_id)
    totals_b = replay_service.conversation_totals(conversation_b_id)
    counts_a = _snapshot_counts(a)
    counts_b = _snapshot_counts(b)

    count_rows = [
        _metric_row(label, counts_a[label], counts_b[label])
        for label in ("nodes", "steps", "tools", "memory", "retrievers", "documents")
    ]
    metric_rows = [
        _metric_row("latency_ms", totals_a.get("latency_ms"), totals_b.get("latency_ms")),
        _metric_row("cost", totals_a.get("cost"), totals_b.get("cost")),
        _metric_row("total_tokens", totals_a.get("total_tokens"), totals_b.get("total_tokens")),
    ]

    return {
        "a": {"conversation_run_id": conversation_a_id, "name": a.get("conversation_name"),
              "model": a.get("request_model"), "counts": counts_a, "totals": totals_a},
        "b": {"conversation_run_id": conversation_b_id, "name": b.get("conversation_name"),
              "model": b.get("request_model"), "counts": counts_b, "totals": totals_b},
        "counts": count_rows,
        "metrics": metric_rows,
        "nodes": _align_nodes(a["nodes"], b["nodes"]),
    }
