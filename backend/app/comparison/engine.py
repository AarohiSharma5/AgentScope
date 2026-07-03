"""Model comparison engine (v0.5).

Executes one traced workflow against multiple models and compares them on
output, latency, tokens, cost, evaluation score, tool calls, memory usage and
retriever performance.

Each model variant is produced by replaying the base conversation under that
model (:class:`~app.orchestration.replay_engine.ReplayEngine`) — reusing the
workflow, agent sequence, prompts, memory, retrieved documents and tool calls —
and (optionally) scored by the
:class:`~app.evaluation.engine.EvaluationEngine`. Pairwise
:class:`~app.models.evaluation_trace.ModelComparison` records are stored
(baseline vs each variant), and a summary + side-by-side view are generated.

Business logic / persistence live in
:mod:`app.services.comparison_service`; this class only orchestrates. Model
names are opaque strings, so the design stays provider-agnostic. Must be used
inside a Flask application context.
"""
import logging
from typing import Any, Optional

from ..evaluation.engine import EvaluationEngine
from ..orchestration.replay_engine import ReplayEngine
from ..services import comparison_service

logger = logging.getLogger("agentscope")


class ComparisonError(Exception):
    """Raised when a comparison cannot be run (e.g. no models, missing base run)."""


class ComparisonResult:
    """The outcome of a multi-model comparison."""

    def __init__(
        self,
        original_conversation_run_id: int,
        baseline_model: str,
        profiles: list[dict],
        summary: dict,
        side_by_side: dict,
        comparison_ids: list[int],
    ) -> None:
        self.original_conversation_run_id = original_conversation_run_id
        self.baseline_model = baseline_model
        self.profiles = profiles
        self.summary = summary
        self.side_by_side = side_by_side
        self.comparison_ids = comparison_ids

    @property
    def winner(self) -> Optional[str]:
        """The overall winning model, per the summary ranking."""
        return self.summary.get("overall_winner")

    def profile(self, model: str) -> Optional[dict]:
        """Return one model's profile by name."""
        return next((p for p in self.profiles if p.get("model") == model), None)

    def __repr__(self) -> str:
        return (
            f"<ComparisonResult models={[p.get('model') for p in self.profiles]} "
            f"winner={self.winner}>"
        )


class ModelComparisonEngine:
    """Runs a workflow against multiple models and compares the results."""

    def __init__(
        self,
        replay_engine: Optional[ReplayEngine] = None,
        evaluation_engine: Optional[EvaluationEngine] = None,
    ) -> None:
        self.replay_engine = replay_engine or ReplayEngine()
        self.evaluation_engine = evaluation_engine or EvaluationEngine()

    def compare(
        self,
        conversation_run_id: int,
        models: list[str],
        baseline_model: Optional[str] = None,
        evaluate: bool = False,
        reference: Optional[str] = None,
        expected_facts: Optional[list[str]] = None,
        latency_budget_ms: Optional[float] = None,
        cost_budget: Optional[float] = None,
        model_configs: Optional[dict[str, dict]] = None,
    ) -> ComparisonResult:
        """Compare ``models`` by replaying ``conversation_run_id`` under each.

        ``model_configs`` maps a model name to replay overrides (``system_prompt``,
        ``memory``, ``tools``, ``live``, ``agent_handlers``, ``tool_handlers``) —
        e.g. to drive real, provider-specific live execution. When ``evaluate`` is
        true each variant is scored and the score participates in ranking.
        """
        if not models:
            raise ComparisonError("at least one model is required")
        baseline_model = baseline_model or models[0]
        if baseline_model not in models:
            raise ComparisonError("baseline_model must be one of models")
        configs = model_configs or {}

        profiles: list[dict] = []
        for model in models:
            profiles.append(
                self._run_variant(
                    conversation_run_id, model, configs.get(model, {}),
                    evaluate, reference, expected_facts, latency_budget_ms, cost_budget,
                )
            )

        by_model = {p["model"]: p for p in profiles}
        baseline = by_model[baseline_model]
        comparison_ids = [
            comparison_service.record_pair(baseline, variant).id
            for variant in profiles
            if variant["model"] != baseline_model
        ]

        return ComparisonResult(
            original_conversation_run_id=conversation_run_id,
            baseline_model=baseline_model,
            profiles=profiles,
            summary=comparison_service.summarize(profiles),
            side_by_side=comparison_service.side_by_side(profiles),
            comparison_ids=comparison_ids,
        )

    def _run_variant(
        self,
        conversation_run_id: int,
        model: str,
        config: dict,
        evaluate: bool,
        reference: Optional[str],
        expected_facts: Optional[list[str]],
        latency_budget_ms: Optional[float],
        cost_budget: Optional[float],
    ) -> dict:
        """Replay + (optionally) evaluate one model, returning its profile."""
        replay = self.replay_engine.replay(
            conversation_run_id,
            model=model,
            system_prompt=config.get("system_prompt"),
            memory=config.get("memory"),
            tools=config.get("tools"),
            live=config.get("live", False),
            agent_handlers=config.get("agent_handlers"),
            tool_handlers=config.get("tool_handlers"),
        )

        evaluation_score = None
        if evaluate:
            evaluation = self.evaluation_engine.evaluate(
                replay.replay_conversation_run_id,
                reference=reference,
                expected_facts=expected_facts,
                latency_budget_ms=latency_budget_ms,
                cost_budget=cost_budget,
            )
            evaluation_score = evaluation.overall_score

        profile = comparison_service.variant_profile(
            replay.replay_conversation_run_id,
            model=model,
            evaluation_score=evaluation_score,
            replay_run_id=replay.replay_run.id,
        )
        return profile
