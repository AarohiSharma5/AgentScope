import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import Card from "../components/ui/Card.jsx";
import Loading from "../components/ui/Loading.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import BarChart from "../components/charts/BarChart.jsx";
import LineChart from "../components/charts/LineChart.jsx";
import { fmtCost, fmtLatency, fmtNumber, fmtScore } from "../lib/format.js";

// Short "Jul 3" label from an ISO date (YYYY-MM-DD).
function dayLabel(iso) {
  if (!iso || iso === "unknown") return "?";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ChartCard({ title, subtitle, children }) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-gray-200">{title}</h3>
        {subtitle && <span className="font-mono text-xs text-gray-500">{subtitle}</span>}
      </div>
      {children}
    </Card>
  );
}

// Selectable time windows. `days: 0` tells the backend to return all history.
const RANGES = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 0 },
];

function RangePicker({ value, onChange, disabled }) {
  return (
    <div className="inline-flex rounded-lg border border-ink-500 bg-ink-700 p-0.5">
      {RANGES.map((r) => (
        <button
          key={r.label}
          type="button"
          disabled={disabled}
          onClick={() => onChange(r.days)}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
            value === r.days
              ? "bg-ink-600 text-gray-100"
              : "text-gray-400 hover:text-gray-200"
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

// Percent change of a metric between the earlier and the recent half of the
// selected window. `pick` reads the metric off a daily bucket; buckets are
// weighted by their evaluation count so busy days count more than quiet ones.
// Returns null when there isn't enough data on both sides to compare.
function trendPct(daily, pick) {
  if (!daily || daily.length < 2) return null;
  const mid = Math.floor(daily.length / 2);
  const wavg = (rows) => {
    let num = 0;
    let den = 0;
    for (const r of rows) {
      const v = pick(r);
      if (v == null) continue;
      const w = r.evaluations || 0;
      num += v * w;
      den += w;
    }
    return den ? num / den : null;
  };
  const earlier = wavg(daily.slice(0, mid));
  const recent = wavg(daily.slice(mid));
  if (earlier == null || recent == null || earlier === 0) return null;
  return (recent - earlier) / Math.abs(earlier);
}

// Colored ▲/▼ indicator. `goodDirection` says which way is an improvement so we
// can color cost/latency/failures (down = good) opposite to score (up = good).
function Delta({ pct, goodDirection = "up" }) {
  if (pct == null) return <span className="text-gray-600">no trend yet</span>;
  const asPct = pct * 100;
  const flat = Math.abs(asPct) < 0.5;
  const up = asPct > 0;
  const good = up ? goodDirection === "up" : goodDirection === "down";
  const color = flat ? "text-gray-500" : good ? "text-emerald-400" : "text-rose-400";
  const arrow = flat ? "→" : up ? "▲" : "▼";
  return (
    <span className={color} title="Recent half of the selected period vs. the earlier half">
      {arrow} {Math.abs(asPct).toFixed(1)}% vs earlier
    </span>
  );
}

export default function Analytics() {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(90);

  useEffect(() => {
    let active = true;
    setRefreshing(true);
    api
      .getEvaluationAnalytics({ days })
      .then((data) => active && setAnalytics(data))
      .catch((e) => active && setError(e.message))
      .finally(() => {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => {
      active = false;
    };
  }, [days]);

  if (loading) return <Loading label="Loading analytics…" />;
  if (error) {
    return <ErrorState message={`Failed to load analytics: ${error}. Is the backend running?`} />;
  }

  const totals = analytics?.totals || {};
  const daily = analytics?.daily || [];
  const label = (d) => dayLabel(d.date);
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

  // Within-window trends for the four time-series metrics. Tool Success and
  // Memory Usage aren't in the daily series, so they carry no delta.
  const scoreTrend = trendPct(daily, (d) => d.evaluation_score);
  const costTrend = trendPct(daily, (d) => (d.evaluations ? d.cost / d.evaluations : null));
  const latencyTrend = trendPct(daily, (d) => d.latency_ms);
  const failureTrend = trendPct(daily, (d) => d.failure_rate);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Analytics</h1>
          <p className="mt-1 text-sm text-gray-500">
            Cost, latency, quality and reliability trends across your evaluations.
          </p>
        </div>
        <RangePicker value={days} onChange={setDays} disabled={refreshing} />
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
        <StatCard
          label="Avg Score"
          value={fmtScore(totals.average_evaluation_score)}
          sublabel={<Delta pct={scoreTrend} goodDirection="up" />}
        />
        <StatCard
          label="Avg Cost"
          value={fmtCost(totals.average_cost)}
          sublabel={<Delta pct={costTrend} goodDirection="down" />}
        />
        <StatCard
          label="Avg Latency"
          value={fmtLatency(totals.average_latency)}
          sublabel={<Delta pct={latencyTrend} goodDirection="down" />}
        />
        <StatCard
          label="Failure Rate"
          value={pct(totals.failure_rate)}
          sublabel={<Delta pct={failureTrend} goodDirection="down" />}
        />
        <StatCard label="Tool Success" value={fmtScore(totals.average_tool_accuracy)} />
        <StatCard label="Memory Usage" value={fmtScore(totals.average_memory_usage)} />
      </div>

      {daily.length === 0 ? (
        <EmptyState
          icon="◔"
          title="No analytics yet"
          message="Run some evaluations to populate cost, latency and quality trends."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <ChartCard title="Daily Cost">
            <BarChart
              data={daily.map((d) => ({ label: label(d), value: d.cost }))}
              format={fmtCost}
              label="Daily cost"
            />
          </ChartCard>
          <ChartCard title="Daily Latency">
            <BarChart
              data={daily.map((d) => ({ label: label(d), value: d.latency_ms }))}
              format={fmtLatency}
              color="bg-sky-500/70"
              label="Daily latency"
            />
          </ChartCard>
          <ChartCard title="Average Evaluation Score">
            <LineChart
              data={daily.map((d) => ({ label: label(d), value: d.evaluation_score }))}
              format={fmtScore}
              label="Average evaluation score over time"
            />
          </ChartCard>
          <ChartCard title="Token Usage">
            <BarChart
              data={daily.map((d) => ({ label: label(d), value: d.tokens }))}
              format={fmtNumber}
              color="bg-violet-500/70"
              label="Daily token usage"
            />
          </ChartCard>
          <ChartCard title="Failure Rate">
            <BarChart
              data={daily.map((d) => ({ label: label(d), value: d.failure_rate }))}
              format={pct}
              color="bg-rose-500/70"
              label="Daily failure rate"
            />
          </ChartCard>
          <ChartCard title="Reliability" subtitle="tool success · memory usage">
            <BarChart
              data={[
                { label: "Tool Success", value: totals.average_tool_accuracy },
                { label: "Memory Usage", value: totals.average_memory_usage },
                { label: "Correctness", value: totals.average_correctness },
                { label: "Faithfulness", value: totals.average_faithfulness },
                { label: "Groundedness", value: totals.average_groundedness },
              ]}
              format={fmtScore}
              color="bg-emerald-500/70"
              label="Reliability metrics"
            />
          </ChartCard>
        </div>
      )}
    </div>
  );
}
