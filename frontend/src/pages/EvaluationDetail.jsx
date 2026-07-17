import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { fmtScore, fmtTime } from "../lib/format.js";

import Card from "../components/ui/Card.jsx";
import Section from "../components/ui/Section.jsx";
import Skeleton from "../components/ui/Skeleton.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import MetricCard, { humanize } from "../components/eval/MetricCard.jsx";
import RadarChart from "../components/charts/RadarChart.jsx";
import LineChart from "../components/charts/LineChart.jsx";

function scoreTone(value) {
  if (value == null) return "text-gray-400";
  if (value >= 0.7) return "text-emerald-400";
  if (value >= 0.4) return "text-amber-400";
  return "text-rose-400";
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

export default function EvaluationDetail() {
  const { id } = useParams();
  const [evaluation, setEvaluation] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setEvaluation(null);

    api
      .getEvaluation(id)
      .then(async (run) => {
        if (!active) return;
        setEvaluation(run);
        const res = await api
          .getEvaluations({
            conversation_run_id: run.conversation_run_id,
            sort: "created_at",
            limit: 50,
          })
          .catch(() => ({ data: [] }));
        if (active) setHistory(res.data || []);
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  const metrics = evaluation?.metrics || [];
  const radarAxes = metrics.map((m) => ({
    label: humanize(m.metric_name),
    value: m.metric_value,
  }));
  const historyPoints = history.map((h) => ({
    label: fmtTime(h.created_at),
    value: h.overall_score,
  }));

  return (
    <div className="space-y-6">
      <Link to="/evaluations" className="text-sm text-accent hover:text-accent-hover">
        ← Back to evaluations
      </Link>

      {loading ? (
        <DetailSkeleton />
      ) : error ? (
        <ErrorState message={`Failed to load this evaluation: ${error}`} />
      ) : !evaluation ? (
        <EmptyState icon="?" title="Evaluation not found" message="The id may be incorrect." />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-100">
                Evaluation #{evaluation.id}
              </h1>
              {evaluation.evaluation_type && (
                <span className="rounded-md bg-ink-500 px-2 py-1 font-mono text-xs text-gray-300">
                  {evaluation.evaluation_type}
                </span>
              )}
              <StatusBadge status={evaluation.status} />
            </div>
            <Link
              to={`/conversations/${evaluation.conversation_run_id}`}
              className="font-mono text-sm text-accent hover:text-accent-hover"
            >
              conversation #{evaluation.conversation_run_id}
            </Link>
          </div>

          <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
            <Card className="flex flex-col items-center justify-center p-6">
              <p className="text-xs uppercase tracking-wider text-gray-500">Overall Score</p>
              <p className={`mt-2 text-5xl font-semibold ${scoreTone(evaluation.overall_score)}`}>
                {fmtScore(evaluation.overall_score)}
              </p>
              <p className="mt-2 text-xs text-gray-500">{fmtTime(evaluation.created_at)}</p>
            </Card>

            <Card className="p-5">
              <h3 className="mb-2 text-sm font-medium text-gray-200">Metric Radar</h3>
              <RadarChart axes={radarAxes} label="Metric radar" />
            </Card>
          </div>

          <Section title="Metrics" count={metrics.length}>
            {metrics.length === 0 ? (
              <EmptyState message="This evaluation recorded no metrics." />
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {metrics.map((m) => (
                  <MetricCard key={m.id ?? m.metric_name} metric={m} />
                ))}
              </div>
            )}
          </Section>

          <Section title="Score History" count={historyPoints.length}>
            <Card className="p-5">
              {historyPoints.length < 2 ? (
                <p className="py-6 text-center text-sm text-gray-500">
                  Not enough evaluations of this conversation to chart a trend yet.
                </p>
              ) : (
                <LineChart data={historyPoints} format={fmtScore} label="Score history over time" />
              )}
            </Card>
          </Section>
        </>
      )}
    </div>
  );
}
