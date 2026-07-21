import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { useEventStream } from "../lib/useEventStream.js";
import StatCard from "../components/StatCard.jsx";
import Card from "../components/ui/Card.jsx";
import Loading from "../components/ui/Loading.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import BarChart from "../components/charts/BarChart.jsx";
import LineChart from "../components/charts/LineChart.jsx";
import ScatterChart from "../components/charts/ScatterChart.jsx";
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

// Toggles real-time mode. When on, the page subscribes to the evaluation event
// stream and auto-refreshes as new evaluations complete. The dot reflects the
// live SSE connection: pulsing green when streaming, amber while connecting.
function LiveToggle({ live, status, onToggle }) {
  const connected = status === "open";
  const dot = !live
    ? "bg-gray-500"
    : connected
      ? "bg-emerald-400 animate-pulse"
      : "bg-amber-400 animate-pulse";
  const text = !live ? "Go live" : connected ? "Live" : "Connecting…";
  return (
    <button
      type="button"
      onClick={onToggle}
      title={
        live
          ? "Auto-refreshing as evaluations complete. Click to stop."
          : "Auto-refresh the dashboard as new evaluations complete."
      }
      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1 text-xs font-medium transition-colors ${
        live
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
          : "border-ink-500 bg-ink-700 text-gray-400 hover:text-gray-200"
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      {text}
    </button>
  );
}

// Scopes the whole page (time-series, headline cards, percentiles) to a single
// generating model. Empty value means "all models". Options come from the
// backend's unfiltered `available_models`, so the list stays stable regardless
// of the current selection.
function ModelPicker({ value, options, onChange, disabled }) {
  if (!options || options.length === 0) return null;
  return (
    <label className="inline-flex items-center gap-2 text-xs text-gray-400">
      <span>Model</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-ink-500 bg-ink-700 px-2 py-1 text-xs font-medium text-gray-200 disabled:opacity-50"
      >
        <option value="">All models</option>
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    </label>
  );
}

// Saved views (custom dashboards): load a named range+model preset, save the
// current one, or delete the selected preset. Keeps the whole dashboard
// configuration one click away.
function ViewsBar({ views, onApply, onSave, onDelete }) {
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [selectedId, setSelectedId] = useState("");

  const apply = (id) => {
    setSelectedId(id);
    const v = views.find((x) => String(x.id) === String(id));
    if (v) onApply(v.config || {});
  };
  const save = async () => {
    if (!name.trim()) return;
    await onSave(name.trim());
    setName("");
    setSaving(false);
  };

  const ctl =
    "rounded-lg border border-ink-500 bg-ink-700 px-2 py-1 text-xs font-medium text-gray-300";

  return (
    <div className="inline-flex items-center gap-1.5">
      {views.length > 0 && (
        <select
          value={selectedId}
          onChange={(e) => apply(e.target.value)}
          className={`${ctl} text-gray-200`}
          title="Load a saved view"
        >
          <option value="">Saved views…</option>
          {views.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      )}
      {selectedId && (
        <button
          type="button"
          onClick={() => {
            onDelete(selectedId);
            setSelectedId("");
          }}
          className={`${ctl} text-gray-500 hover:text-rose-400`}
          title="Delete this view"
        >
          ✕
        </button>
      )}
      {saving ? (
        <span className="inline-flex items-center gap-1">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && save()}
            placeholder="View name"
            className="w-32 rounded-lg border border-ink-500 bg-ink-800 px-2 py-1 text-xs text-gray-200 outline-none focus:border-accent"
          />
          <button type="button" onClick={save} className={`${ctl} text-accent`}>
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setSaving(false);
              setName("");
            }}
            className={`${ctl} text-gray-500`}
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setSaving(true)}
          className={`${ctl} hover:text-gray-100`}
          title="Save the current range + model as a view"
        >
          + Save view
        </button>
      )}
    </div>
  );
}

// Evaluation-count-weighted averages of a metric over the earlier vs. the
// recent half of the selected window. Busy days count more than quiet ones.
// Returns null when there isn't enough data on both sides to compare.
function halfAverages(daily, pick) {
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
  if (earlier == null || recent == null) return null;
  return { earlier, recent };
}

// Percent change of a metric between the earlier and recent halves.
function trendPct(daily, pick) {
  const h = halfAverages(daily, pick);
  if (!h || h.earlier === 0) return null;
  return (h.recent - h.earlier) / Math.abs(h.earlier);
}

// Date of the day with the min/max value of a metric (for "inspect worst day").
function worstDay(daily, pick, mode) {
  let best = null;
  for (const d of daily) {
    const v = pick(d);
    if (v == null) continue;
    if (!best || (mode === "max" ? v > best.v : v < best.v)) best = { date: d.date, v };
  }
  return best ? best.date : null;
}

// Derive regression alerts from the daily series. Quality uses a relative drop,
// failure rate an absolute jump in percentage points, cost/latency a relative
// rise. Each alert carries the worst day so the UI can drill into it.
function buildAlerts(daily) {
  const alerts = [];
  if (!daily || daily.length < 2) return alerts;

  const s = halfAverages(daily, (d) => d.evaluation_score);
  if (s && s.earlier > 0) {
    const drop = (s.earlier - s.recent) / s.earlier;
    if (drop >= 0.05) {
      alerts.push({
        id: "score",
        severity: drop >= 0.15 ? "crit" : "warn",
        title: "Quality regression.",
        msg: `Average score fell ${Math.round(drop * 100)}% vs. earlier in this period.`,
        date: worstDay(daily, (d) => d.evaluation_score, "min"),
      });
    }
  }

  const f = halfAverages(daily, (d) => d.failure_rate);
  if (f) {
    const inc = f.recent - f.earlier;
    if (inc >= 0.05) {
      alerts.push({
        id: "failure",
        severity: inc >= 0.15 ? "crit" : "warn",
        title: "Failure-rate spike.",
        msg: `Failure rate rose ${Math.round(inc * 100)} points vs. earlier.`,
        date: worstDay(daily, (d) => d.failure_rate, "max"),
      });
    }
  }

  const c = halfAverages(daily, (d) => (d.evaluations ? d.cost / d.evaluations : null));
  if (c && c.earlier > 0) {
    const inc = (c.recent - c.earlier) / c.earlier;
    if (inc >= 0.2) {
      alerts.push({
        id: "cost",
        severity: inc >= 0.5 ? "crit" : "warn",
        title: "Cost spike.",
        msg: `Average cost per evaluation rose ${Math.round(inc * 100)}% vs. earlier.`,
        date: worstDay(daily, (d) => (d.evaluations ? d.cost / d.evaluations : null), "max"),
      });
    }
  }

  const l = halfAverages(daily, (d) => d.latency_ms);
  if (l && l.earlier > 0) {
    const inc = (l.recent - l.earlier) / l.earlier;
    if (inc >= 0.2) {
      alerts.push({
        id: "latency",
        severity: inc >= 0.5 ? "crit" : "warn",
        title: "Latency spike.",
        msg: `Average latency rose ${Math.round(inc * 100)}% vs. earlier.`,
        date: worstDay(daily, (d) => d.latency_ms, "max"),
      });
    }
  }

  // Most severe first.
  alerts.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "crit" ? -1 : 1));
  return alerts;
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

// Best-effort provider inference from a model name. Keeps the cross-provider
// comparison explicit on screen (the thing no single vendor dashboard shows).
function providerOf(model) {
  const m = (model || "").toLowerCase();
  if (/(gpt|^o[0-9]|davinci|chatgpt|text-embedding|whisper|dall-e)/.test(m)) return "OpenAI";
  if (m.includes("claude")) return "Anthropic";
  if (/(gemini|palm|bison|gecko)/.test(m)) return "Google";
  if (/(llama|meta-)/.test(m)) return "Meta";
  if (/(mistral|mixtral|codestral)/.test(m)) return "Mistral";
  if (m.includes("command") || m.includes("cohere")) return "Cohere";
  if (m.includes("grok")) return "xAI";
  return "Other";
}

// Distinct color per provider so the cross-provider comparison reads visually
// in the quadrant. Full literal class strings so Tailwind's JIT keeps them.
const PROVIDER_COLORS = {
  OpenAI: "bg-teal-500/80 border-teal-300",
  Anthropic: "bg-amber-500/80 border-amber-300",
  Google: "bg-sky-500/80 border-sky-300",
  Meta: "bg-blue-500/80 border-blue-300",
  Mistral: "bg-orange-500/80 border-orange-300",
  Cohere: "bg-pink-500/80 border-pink-300",
  xAI: "bg-slate-400/80 border-slate-200",
  Other: "bg-gray-500/80 border-gray-300",
};

function providerColor(provider) {
  return PROVIDER_COLORS[provider] || PROVIDER_COLORS.Other;
}

// Quality per dollar: how much evaluation score each dollar buys. The headline
// "value" metric that ties cost to outcome (higher is better).
function qualityPerDollar(row) {
  if (row.average_evaluation_score == null || !row.average_cost) return null;
  return row.average_evaluation_score / row.average_cost;
}

// Per-model comparison table. Highlights the highest-scoring, cheapest and
// best-value models so the cost/quality trade-off is obvious at a glance.
function ModelBreakdown({ rows, highlightModel }) {
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  const scored = rows.filter((r) => r.average_evaluation_score != null);
  const bestScore = scored.length
    ? Math.max(...scored.map((r) => r.average_evaluation_score))
    : null;
  const costed = rows.filter((r) => r.average_cost != null);
  const bestCost = costed.length ? Math.min(...costed.map((r) => r.average_cost)) : null;
  const values = rows.map(qualityPerDollar).filter((v) => v != null);
  const bestValue = values.length ? Math.max(...values) : null;

  return (
    <Card className="p-5">
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-200">By Model</h3>
        <p className="mt-1 text-xs text-gray-500">
          Cost, quality and reliability per generating model over the selected period.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink-500 text-left text-xs uppercase tracking-wider text-gray-500">
              <th className="py-2 pr-4 font-medium">Model</th>
              <th className="py-2 pr-4 font-medium">Provider</th>
              <th className="py-2 pr-4 text-right font-medium">Evals</th>
              <th className="py-2 pr-4 text-right font-medium">Avg Score</th>
              <th className="py-2 pr-4 text-right font-medium">Avg Cost</th>
              <th className="py-2 pr-4 text-right font-medium">Quality / $</th>
              <th className="py-2 pr-4 text-right font-medium">Avg Latency</th>
              <th className="py-2 text-right font-medium">Failure Rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isBestScore =
                bestScore != null && r.average_evaluation_score === bestScore;
              const isBestCost = bestCost != null && r.average_cost === bestCost;
              const value = qualityPerDollar(r);
              const isBestValue = bestValue != null && value === bestValue;
              const isSelected = highlightModel && r.model === highlightModel;
              return (
                <tr
                  key={r.model}
                  className={`border-b border-ink-600/50 last:border-0 ${
                    isSelected ? "bg-accent/10" : ""
                  }`}
                >
                  <td className="py-2 pr-4 font-mono text-gray-200">{r.model}</td>
                  <td className="py-2 pr-4 text-gray-400">{providerOf(r.model)}</td>
                  <td className="py-2 pr-4 text-right text-gray-300">
                    {fmtNumber(r.evaluations)}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right ${
                      isBestScore ? "text-emerald-400" : "text-gray-300"
                    }`}
                  >
                    {fmtScore(r.average_evaluation_score)}
                    {isBestScore && <span className="ml-1 text-[10px] uppercase">best</span>}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right ${
                      isBestCost ? "text-emerald-400" : "text-gray-300"
                    }`}
                  >
                    {fmtCost(r.average_cost)}
                    {isBestCost && (
                      <span className="ml-1 text-[10px] uppercase">cheapest</span>
                    )}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right ${
                      isBestValue ? "text-emerald-400" : "text-gray-300"
                    }`}
                  >
                    {value == null ? "—" : fmtNumber(Math.round(value))}
                    {isBestValue && (
                      <span className="ml-1 text-[10px] uppercase">best value</span>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-right text-gray-300">
                    {fmtLatency(r.average_latency)}
                  </td>
                  <td className="py-2 text-right text-gray-300">{pct(r.failure_rate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// p50/p95/p99 of latency and per-conversation cost. The tail (p95/p99) surfaces
// the worst-case pain that a single average hides.
function PercentilesCard({ percentiles }) {
  const lat = percentiles.latency_ms || {};
  const cost = percentiles.cost || {};
  const hasData = [lat.p50, lat.p95, lat.p99, cost.p50, cost.p95, cost.p99].some(
    (v) => v != null
  );
  if (!hasData) return null;
  const cell = "py-2 pr-4 text-right text-gray-300";
  return (
    <Card className="p-5">
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-200">Latency &amp; Cost Distribution</h3>
        <p className="mt-1 text-xs text-gray-500">
          Percentiles across evaluated conversations — the tail (p95/p99) reveals worst-case
          pain that averages hide.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink-500 text-left text-xs uppercase tracking-wider text-gray-500">
              <th className="py-2 pr-4 font-medium">Metric</th>
              <th
                className="py-2 pr-4 text-right font-medium"
                title="Median — half of conversations were faster/cheaper than this. The typical experience."
              >
                <span className="cursor-help underline decoration-dotted underline-offset-2">
                  p50 (median)
                </span>
              </th>
              <th
                className="py-2 pr-4 text-right font-medium"
                title="95% of conversations were faster/cheaper than this — your worst 5% (the tail engineers watch)."
              >
                <span className="cursor-help underline decoration-dotted underline-offset-2">
                  p95
                </span>
              </th>
              <th
                className="py-2 text-right font-medium"
                title="99% of conversations were faster/cheaper than this — the absolute worst 1%."
              >
                <span className="cursor-help underline decoration-dotted underline-offset-2">
                  p99
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-ink-600/50">
              <td className="py-2 pr-4 text-gray-200">Latency</td>
              <td className={cell}>{fmtLatency(lat.p50)}</td>
              <td className={cell}>{fmtLatency(lat.p95)}</td>
              <td className="py-2 text-right text-gray-300">{fmtLatency(lat.p99)}</td>
            </tr>
            <tr>
              <td className="py-2 pr-4 text-gray-200">Cost / conversation</td>
              <td className={cell}>{fmtCost(cost.p50)}</td>
              <td className={cell}>{fmtCost(cost.p95)}</td>
              <td className="py-2 text-right text-gray-300">{fmtCost(cost.p99)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// Regression alerts (or an all-clear). Each alert is clickable to jump to the
// worst day behind it, reusing the day-drill-down selection.
function AlertsPanel({ alerts, onSelectDate }) {
  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-300">
        <span aria-hidden="true">✓</span>
        No regressions detected in this period.
      </div>
    );
  }
  return (
    <div className="space-y-2" role="list" aria-label="Regression alerts">
      {alerts.map((a) => {
        const crit = a.severity === "crit";
        const tone = crit
          ? "border-rose-500/30 bg-rose-500/10 text-rose-200"
          : "border-amber-500/30 bg-amber-500/10 text-amber-200";
        const dot = crit ? "bg-rose-400" : "bg-amber-400";
        return (
          <button
            key={a.id}
            type="button"
            role="listitem"
            onClick={a.date ? () => onSelectDate(a.date) : undefined}
            className={`flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left text-sm ${tone} ${
              a.date ? "transition-opacity hover:opacity-90" : "cursor-default"
            }`}
          >
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
            <span>
              <span className="font-medium">{a.title}</span>{" "}
              <span className="opacity-80">{a.msg}</span>
              {a.date && (
                <span className="ml-1 text-xs opacity-60">· click to inspect worst day</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// Deploy / change annotations: create, list and delete markers that appear on
// the score trend so metric movements can be tied to what changed.
function AnnotationsCard({ annotations, onAdd, onDelete }) {
  const [label, setLabel] = useState("");
  const [date, setDate] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const fmtDate = (iso) =>
    iso
      ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        })
      : "";

  const submit = async (e) => {
    e.preventDefault();
    if (!label.trim() || !date) {
      setError("Label and date are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onAdd({
        label: label.trim(),
        annotated_at: date,
        description: description.trim() || undefined,
      });
      setLabel("");
      setDate("");
      setDescription("");
    } catch (err) {
      setError(err.message || "Failed to add annotation.");
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    "rounded-lg border border-ink-500 bg-ink-800 px-3 py-1.5 text-sm text-gray-200 outline-none focus:border-accent";

  return (
    <Card className="p-5">
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-200">Deploys &amp; Annotations</h3>
        <p className="mt-1 text-xs text-gray-500">
          Mark a change (new prompt, model switch) to tie it to metric movements. Markers
          show on the score trend.
        </p>
      </div>
      <form onSubmit={submit} className="mb-4 flex flex-wrap items-end gap-2">
        <div className="flex flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">Label</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="v2 prompt shipped"
            className={`w-44 ${inputCls}`}
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">Date</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={inputCls} />
        </div>
        <div className="flex flex-1 flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">
            Note (optional)
          </label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What changed?"
            className={`w-full ${inputCls}`}
          />
        </div>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-accent/90 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent disabled:opacity-50"
        >
          {busy ? "Adding…" : "Add"}
        </button>
      </form>
      {error && <p className="mb-3 text-xs text-rose-400">{error}</p>}
      {annotations.length === 0 ? (
        <p className="text-sm text-gray-500">No annotations yet.</p>
      ) : (
        <ul className="space-y-2">
          {annotations.map((a) => (
            <li
              key={a.id}
              className="flex items-start justify-between gap-3 rounded-lg border border-ink-600/50 px-3 py-2"
            >
              <div>
                <span className="text-sm text-amber-300">⚑ {a.label}</span>
                <span className="ml-2 text-xs text-gray-500">{fmtDate(a.date)}</span>
                {a.description && <p className="mt-0.5 text-xs text-gray-500">{a.description}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <Link
                  to={`/comparisons?label=${encodeURIComponent(a.label)}&since=${a.date}`}
                  className="text-xs text-accent transition-colors hover:underline"
                  title="Isolate this change by re-running a conversation across models"
                >
                  Investigate →
                </Link>
                <button
                  type="button"
                  onClick={() => onDelete(a.id)}
                  className="text-xs text-gray-500 transition-colors hover:text-rose-400"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const FINDING_DOT = {
  crit: "bg-rose-400",
  warn: "bg-amber-400",
  info: "bg-sky-400",
};

// Executive summary of the current window: a plain-English narrative plus a list
// of detected findings (regressions, anomalies, cost drivers, budget breaches).
// The summary is heuristic by default; "Summarize with AI" swaps in an
// LLM-written narrative when a provider is configured.
// Which metric a finding is about, so Investigate can pre-select the day's
// *worst* conversation for that metric (not just the most recent one).
function metricForFinding(id) {
  if (!id) return null;
  if (id.startsWith("quality") || id.startsWith("score")) return "quality";
  if (id.startsWith("cost")) return "cost";
  if (id.startsWith("latency")) return "latency";
  if (id.startsWith("failure")) return "failure";
  return null;
}

function InsightsCard({
  insights,
  aiStatus,
  onGenerateAI,
  aiBusy,
  onDownload,
  downloadBusy,
}) {
  if (!insights) return null;
  const { summary, summary_source: source, findings = [] } = insights;
  const isAI = source === "ai";
  const aiReady = aiStatus?.available === true;
  const aiModelLabel = aiStatus
    ? [aiStatus.provider, aiStatus.model].filter(Boolean).join(" · ")
    : "";
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-gray-200">Insights</h3>
          {isAI && (
            <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] uppercase text-accent">
              ✨ AI
            </span>
          )}
          {aiStatus && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] ${
                aiReady
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-ink-700 text-gray-500"
              }`}
              title={aiReady ? `LLM: ${aiModelLabel}` : aiStatus.hint || aiStatus.reason}
            >
              {aiReady ? `AI ready · ${aiModelLabel}` : "AI off"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onDownload}
            disabled={downloadBusy}
            className="rounded-lg border border-ink-500 bg-ink-700 px-2.5 py-1 text-xs font-medium text-gray-300 transition-colors hover:text-gray-100 disabled:opacity-50"
            title="Download this window as a Markdown digest"
          >
            {downloadBusy ? "Preparing…" : "↓ Download digest"}
          </button>
          <button
            type="button"
            onClick={onGenerateAI}
            disabled={aiBusy || aiStatus?.available === false}
            title={
              aiStatus?.available === false
                ? aiStatus.hint || aiStatus.reason
                : "Generate an executive summary with the configured LLM"
            }
            className="rounded-lg border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {aiBusy ? "Summarizing…" : "✨ Summarize with AI"}
          </button>
        </div>
      </div>

      <p className="text-sm leading-relaxed text-gray-300">{summary}</p>

      {(source === "ai_unavailable" || aiStatus?.available === false) && (
        <p className="mt-2 text-xs text-amber-300/80">
          {source === "ai_unavailable"
            ? "No LLM configured — showing the heuristic summary. "
            : "AI summaries are off — showing the heuristic summary. "}
          {aiStatus?.hint || (
            <>
              Set an API key (e.g. <span className="font-mono">OPENAI_API_KEY</span>) or{" "}
              <span className="font-mono">INSIGHTS_PROVIDER</span> to enable AI summaries.
            </>
          )}
        </p>
      )}

      {findings.length > 0 && (
        <ul className="mt-4 space-y-2">
          {findings.map((f) => (
            <li key={f.id} className="flex items-start gap-2 text-sm">
              <span
                className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                  FINDING_DOT[f.severity] || "bg-gray-500"
                }`}
                aria-hidden="true"
              />
              <span className="text-gray-400">
                <span className="text-gray-200">{f.title}.</span> {f.detail}
                {f.suspects?.length > 0 && (
                  <span className="mt-1 block text-xs text-gray-500">
                    Suspected change{f.suspects.length > 1 ? "s" : ""}:{" "}
                    {f.suspects.map((s, i) => (
                      <span key={`${s.date}-${s.label}-${i}`}>
                        <Link
                          to={`/comparisons?label=${encodeURIComponent(s.label)}&since=${s.date}${
                            metricForFinding(f.id) ? `&metric=${metricForFinding(f.id)}` : ""
                          }`}
                          className="text-accent hover:underline"
                          title="Isolate this change by re-running conversations across models"
                        >
                          {s.label}
                        </Link>
                        {i < f.suspects.length - 1 ? ", " : ""}
                      </span>
                    ))}
                    {f.suspects.length > 1
                      ? " — can't be auto-attributed; isolate by replaying with one reverted at a time."
                      : " — Investigate to confirm the cause."}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// Metric metadata for budgets: display label, value formatter, natural
// guardrail direction and a placeholder hint for the threshold input.
const pctFmt = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const BUDGET_METRIC_META = {
  cost: { label: "Total cost", fmt: fmtCost, dir: "lte", hint: "e.g. 50" },
  avg_score: { label: "Avg score", fmt: fmtScore, dir: "gte", hint: "0–1, e.g. 0.85" },
  failure_rate: { label: "Failure rate", fmt: pctFmt, dir: "lte", hint: "0–1, e.g. 0.05" },
  avg_latency: { label: "Avg latency", fmt: fmtLatency, dir: "lte", hint: "ms, e.g. 2000" },
};

const BUDGET_STATUS = {
  ok: { badge: "bg-emerald-500/15 text-emerald-300", bar: "bg-emerald-500/70", label: "On track" },
  warn: { badge: "bg-amber-500/15 text-amber-300", bar: "bg-amber-500/80", label: "At risk" },
  breach: { badge: "bg-rose-500/15 text-rose-300", bar: "bg-rose-500/80", label: "Breached" },
  unknown: { badge: "bg-ink-600 text-gray-400", bar: "bg-ink-500", label: "No data" },
};

// Budgets / SLOs: create, list and monitor cost caps and quality/latency/
// failure thresholds. Each row shows a progress bar toward the threshold plus an
// on-track / at-risk / breached badge, evaluated over the budget's own window.
function BudgetsCard({ budgets, availableModels, onAdd, onDelete }) {
  const [name, setName] = useState("");
  const [metric, setMetric] = useState("cost");
  const [threshold, setThreshold] = useState("");
  const [windowDays, setWindowDays] = useState(30);
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const meta = BUDGET_METRIC_META[metric] || {};

  const submit = async (e) => {
    e.preventDefault();
    const value = Number(threshold);
    if (!name.trim() || !threshold || Number.isNaN(value) || value <= 0) {
      setError("Name and a threshold greater than 0 are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onAdd({
        name: name.trim(),
        metric,
        threshold_value: value,
        window_days: Number(windowDays) || 0,
        model: model || undefined,
      });
      setName("");
      setThreshold("");
      setModel("");
    } catch (err) {
      setError(err.message || "Failed to add budget.");
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    "rounded-lg border border-ink-500 bg-ink-800 px-3 py-1.5 text-sm text-gray-200 outline-none focus:border-accent";

  return (
    <Card className="p-5">
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-200">Budgets &amp; SLOs</h3>
        <p className="mt-1 text-xs text-gray-500">
          Set a cost cap or a quality / latency / failure target. Each is checked over its own
          window and flags itself when at risk or breached.
        </p>
      </div>

      <form onSubmit={submit} className="mb-4 flex flex-wrap items-end gap-2">
        <div className="flex flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Monthly cost cap"
            className={`w-40 ${inputCls}`}
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">Metric</label>
          <select value={metric} onChange={(e) => setMetric(e.target.value)} className={inputCls}>
            {Object.entries(BUDGET_METRIC_META).map(([value, m]) => (
              <option key={value} value={value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">
            {meta.dir === "gte" ? "Min (≥)" : "Max (≤)"}
          </label>
          <input
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            placeholder={meta.hint}
            inputMode="decimal"
            className={`w-28 ${inputCls}`}
          />
        </div>
        <div className="flex flex-col">
          <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">Window</label>
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className={inputCls}
          >
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={0}>All time</option>
          </select>
        </div>
        {availableModels && availableModels.length > 0 && (
          <div className="flex flex-col">
            <label className="mb-1 text-[10px] uppercase tracking-wider text-gray-500">Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)} className={inputCls}>
              <option value="">All models</option>
              {availableModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-accent/90 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent disabled:opacity-50"
        >
          {busy ? "Adding…" : "Add"}
        </button>
      </form>
      {error && <p className="mb-3 text-xs text-rose-400">{error}</p>}

      {budgets.length === 0 ? (
        <p className="text-sm text-gray-500">No budgets yet.</p>
      ) : (
        <ul className="space-y-3">
          {budgets.map((b) => {
            const m = BUDGET_METRIC_META[b.metric] || {};
            const fmt = m.fmt || ((v) => v);
            const st = BUDGET_STATUS[b.status] || BUDGET_STATUS.unknown;
            const arrow = b.comparison === "gte" ? "≥" : "≤";
            const fillPct = Math.min(Math.max(b.ratio || 0, 0), 1) * 100;
            const windowLabel = b.window_days ? `${b.window_days}d` : "all time";
            return (
              <li key={b.id} className="rounded-lg border border-ink-600/50 px-3 py-2.5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <span className="text-sm text-gray-200">{b.name}</span>
                    <span className="ml-2 text-xs text-gray-500">
                      {m.label} {arrow} {fmt(b.threshold_value)} · {windowLabel}
                      {b.model ? ` · ${b.model}` : ""}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${st.badge}`}>
                      {st.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => onDelete(b.id)}
                      className="text-xs text-gray-500 transition-colors hover:text-rose-400"
                    >
                      Delete
                    </button>
                  </div>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
                    <div
                      className={`h-full rounded-full ${st.bar}`}
                      style={{ width: `${fillPct}%` }}
                    />
                  </div>
                  <span className="w-28 shrink-0 text-right font-mono text-xs text-gray-400">
                    {b.actual == null ? "—" : `${fmt(b.actual)} now`}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

// Breakdown of a single day, shown when a chart point is clicked.
function DayDetail({ day, onClear }) {
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  const full = day.date
    ? new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "Selected day";
  const items = [
    ["Evaluations", fmtNumber(day.evaluations)],
    ["Failures", fmtNumber(day.failures)],
    ["Failure Rate", pct(day.failure_rate)],
    ["Avg Score", fmtScore(day.evaluation_score)],
    ["Cost", fmtCost(day.cost)],
    ["Latency", fmtLatency(day.latency_ms)],
    ["Tokens", fmtNumber(day.tokens)],
  ];
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-gray-200">
          {full} <span className="ml-1 text-xs text-gray-500">· day breakdown</span>
        </h3>
        <button
          type="button"
          onClick={onClear}
          className="rounded-md border border-ink-500 px-2 py-1 text-xs text-gray-400 transition-colors hover:text-gray-200"
        >
          Clear
        </button>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
        {items.map(([k, v]) => (
          <div key={k}>
            <p className="text-xs uppercase tracking-wider text-gray-500">{k}</p>
            <p className="mt-1 text-lg font-semibold text-gray-100">{v}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Analytics() {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(90);
  const [model, setModel] = useState("");
  const [selectedDate, setSelectedDate] = useState(null);
  const [annotations, setAnnotations] = useState([]);
  const [annoVersion, setAnnoVersion] = useState(0);
  const [budgets, setBudgets] = useState([]);
  const [budgetVersion, setBudgetVersion] = useState(0);
  const [live, setLive] = useState(false);
  const [liveTick, setLiveTick] = useState(0);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [insights, setInsights] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [insightsAiBusy, setInsightsAiBusy] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [savedViews, setSavedViews] = useState([]);
  const [savedViewVersion, setSavedViewVersion] = useState(0);

  // Real-time mode: subscribe to the evaluation stream and, when new evaluations
  // land, bump `liveTick` (debounced) to re-pull every data source. Debouncing
  // collapses a burst of completions into a single refresh. The hook is paused
  // (no connection) unless live mode is on.
  const liveTimer = useRef(null);
  const { status: liveStatus } = useEventStream({
    topics: ["evaluation"],
    paused: !live,
    onEvent: () => {
      if (liveTimer.current) clearTimeout(liveTimer.current);
      liveTimer.current = setTimeout(() => setLiveTick((t) => t + 1), 1200);
    },
  });

  useEffect(() => {
    let active = true;
    setRefreshing(true);
    api
      .getEvaluationAnalytics({ days, model })
      .then((data) => {
        if (active) {
          setAnalytics(data);
          setLastUpdated(Date.now());
        }
      })
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
  }, [days, model, liveTick]);

  useEffect(() => {
    let active = true;
    api
      .getAnnotations({ days })
      .then((r) => active && setAnnotations(r?.data || []))
      .catch(() => active && setAnnotations([]));
    return () => {
      active = false;
    };
  }, [days, annoVersion, liveTick]);

  const addAnnotation = async (payload) => {
    await api.createAnnotation(payload);
    setAnnoVersion((v) => v + 1);
  };
  const removeAnnotation = async (id) => {
    await api.deleteAnnotation(id);
    setAnnoVersion((v) => v + 1);
  };

  // Budgets are independent of the page's range/model pickers — each carries its
  // own window and optional model — so they only refetch when one is added or
  // removed. `budgetVersion` also re-syncs their live status after new evals.
  useEffect(() => {
    let active = true;
    api
      .getBudgets()
      .then((r) => active && setBudgets(r?.data || []))
      .catch(() => active && setBudgets([]));
    return () => {
      active = false;
    };
  }, [budgetVersion, liveTick]);

  const addBudget = async (payload) => {
    await api.createBudget(payload);
    setBudgetVersion((v) => v + 1);
  };
  const removeBudget = async (id) => {
    await api.deleteBudget(id);
    setBudgetVersion((v) => v + 1);
  };

  // Heuristic insights refresh with the page filters and live stream. They never
  // trigger an LLM call — that's on-demand via "Summarize with AI" below.
  useEffect(() => {
    let active = true;
    api
      .getEvaluationInsights({ days, model })
      .then((r) => active && setInsights(r))
      .catch(() => active && setInsights(null));
    return () => {
      active = false;
    };
  }, [days, model, liveTick]);

  // Whether an LLM is configured for AI summaries (provider/model + hint). Fetched
  // once so the Insights card can show an "AI ready / off" state before clicking.
  useEffect(() => {
    let active = true;
    api
      .getInsightsStatus()
      .then((s) => active && setAiStatus(s))
      .catch(() => active && setAiStatus(null));
    return () => {
      active = false;
    };
  }, []);

  const generateAiInsights = async () => {
    setInsightsAiBusy(true);
    try {
      const r = await api.getEvaluationInsights({ days, model, ai: 1 });
      setInsights(r);
    } catch {
      // Keep the existing heuristic summary on failure.
    } finally {
      setInsightsAiBusy(false);
    }
  };

  // Download the current window as a Markdown digest. The report matches what's
  // on screen: if an AI summary is showing, the digest requests one too.
  const downloadReport = async () => {
    setReportBusy(true);
    try {
      const ai = insights?.summary_source === "ai" ? 1 : undefined;
      const r = await api.getEvaluationReport({ days, model, ai });
      const blob = new Blob([r.markdown || ""], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "agentscope-analytics-digest.md";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      // Non-fatal: nothing downloaded.
    } finally {
      setReportBusy(false);
    }
  };

  // Saved views (custom dashboards): load / save / delete range+model presets.
  useEffect(() => {
    let active = true;
    api
      .getSavedViews()
      .then((r) => active && setSavedViews(r?.data || []))
      .catch(() => active && setSavedViews([]));
    return () => {
      active = false;
    };
  }, [savedViewVersion]);

  const applyView = (config) => {
    setSelectedDate(null);
    setDays(config.days ?? 90);
    setModel(config.model || "");
  };
  const saveView = async (name) => {
    await api.createSavedView({ name, config: { days, model } });
    setSavedViewVersion((v) => v + 1);
  };
  const deleteView = async (id) => {
    await api.deleteSavedView(id);
    setSavedViewVersion((v) => v + 1);
  };

  if (loading) return <Loading label="Loading analytics…" />;
  if (error) {
    return <ErrorState message={`Failed to load analytics: ${error}. Is the backend running?`} />;
  }

  const totals = analytics?.totals || {};
  const daily = analytics?.daily || [];
  const byModel = analytics?.by_model || [];
  const percentiles = analytics?.percentiles || {};
  // Dropdown options: the backend's unfiltered model list, plus the current
  // selection if it happens to have no data in the window (so the <select>
  // never shows a value that isn't in its options).
  const availableModels = [
    ...new Set([...(analytics?.available_models || []), ...(model ? [model] : [])]),
  ].sort();
  // Models plottable on the cost/quality quadrant (need both dimensions),
  // colored by provider so the cross-provider comparison is visual.
  const costQuality = byModel
    .filter((m) => m.average_cost != null && m.average_evaluation_score != null)
    .map((m) => ({
      x: m.average_cost,
      y: m.average_evaluation_score,
      label: m.model,
      size: m.evaluations,
      color: providerColor(providerOf(m.model)),
    }));
  // Legend of the providers actually present on the quadrant.
  const providerLegend = [...new Set(costQuality.map((p) => providerOf(p.label)))].map(
    (name) => ({ label: name, color: providerColor(name) })
  );
  const label = (d) => dayLabel(d.date);
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);

  // Within-window trends for the four time-series metrics. Tool Success and
  // Memory Usage aren't in the daily series, so they carry no delta.
  const scoreTrend = trendPct(daily, (d) => d.evaluation_score);
  const costTrend = trendPct(daily, (d) => (d.evaluations ? d.cost / d.evaluations : null));
  const latencyTrend = trendPct(daily, (d) => d.latency_ms);
  const failureTrend = trendPct(daily, (d) => d.failure_rate);
  const successTrend = trendPct(daily, (d) => (d.evaluations == null ? null : 1 - d.failure_rate));
  const alerts = buildAlerts(daily);
  // Annotation markers keyed by day, drawn on the score trend chart.
  const annotationMarkers = annotations.map((a) => ({ key: a.date, label: a.label }));

  // Evaluations actually recorded inside the selected window (the daily series
  // is window-bounded, unlike the all-time `totals.total_evaluations`).
  const windowEvals = daily.reduce((sum, d) => sum + (d.evaluations || 0), 0);

  // When a bounded range is selected, the headline cards are derived from the
  // windowed daily series (weighted by each day's evaluation count) so they
  // track the picker just like the charts. On "All" we keep the exact backend
  // totals. Tool Success / Memory Usage aren't in the daily series, so they
  // stay all-time regardless (and are labelled as such when a window is active).
  const bounded = days > 0;
  const wsum = (fn) => daily.reduce((s, d) => s + (fn(d) || 0), 0);
  const wavg = (fn) => {
    let num = 0;
    let den = 0;
    for (const d of daily) {
      const v = fn(d);
      if (v == null) continue;
      const w = d.evaluations || 0;
      num += v * w;
      den += w;
    }
    return den ? num / den : null;
  };
  const winFailureRate = windowEvals ? wsum((d) => d.failures) / windowEvals : null;
  const scoreValue = bounded ? wavg((d) => d.evaluation_score) : totals.average_evaluation_score;
  const costValue = bounded ? (windowEvals ? wsum((d) => d.cost) / windowEvals : null) : totals.average_cost;
  const latencyValue = bounded ? wavg((d) => d.latency_ms) : totals.average_latency;
  const failureValue = bounded ? winFailureRate : totals.failure_rate;
  const successValue = bounded
    ? winFailureRate == null
      ? null
      : 1 - winFailureRate
    : totals.success_rate;
  const allTimeNote = bounded ? "all-time" : undefined;

  // Build a chart series that carries each point's date as its key, so a click
  // in any chart resolves back to the full daily bucket regardless of ordering.
  const series = (fn) => daily.map((d) => ({ label: label(d), value: fn(d), key: d.date }));
  const toggleDay = (d) => setSelectedDate((cur) => (cur === d.key ? null : d.key));
  const selectedDay = selectedDate ? daily.find((d) => d.date === selectedDate) : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Analytics</h1>
          <p className="mt-1 text-sm text-gray-500">
            {model
              ? `Trends scoped to ${model}. The comparison tables below still span all models.`
              : "Cost, latency, quality and reliability trends across your evaluations."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-500">
              Updated{" "}
              {new Date(lastUpdated).toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
          )}
          <ViewsBar
            views={savedViews}
            onApply={applyView}
            onSave={saveView}
            onDelete={deleteView}
          />
          <LiveToggle live={live} status={liveStatus} onToggle={() => setLive((v) => !v)} />
          <ModelPicker
            value={model}
            options={availableModels}
            onChange={(m) => {
              setSelectedDate(null);
              setModel(m);
            }}
            disabled={refreshing}
          />
          <RangePicker
            value={days}
            onChange={(d) => {
              setSelectedDate(null);
              setDays(d);
            }}
            disabled={refreshing}
          />
        </div>
      </div>

      <InsightsCard
        insights={insights}
        aiStatus={aiStatus}
        onGenerateAI={generateAiInsights}
        aiBusy={insightsAiBusy}
        onDownload={downloadReport}
        downloadBusy={reportBusy}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          label="Evaluations"
          value={fmtNumber(windowEvals)}
          sublabel={`${daily.length} active ${daily.length === 1 ? "day" : "days"}`}
        />
        <StatCard
          label="Avg Score"
          value={fmtScore(scoreValue)}
          sublabel={<Delta pct={scoreTrend} goodDirection="up" />}
        />
        <StatCard
          label="Success Rate"
          value={pct(successValue)}
          sublabel={<Delta pct={successTrend} goodDirection="up" />}
        />
        <StatCard
          label="Failure Rate"
          value={pct(failureValue)}
          sublabel={<Delta pct={failureTrend} goodDirection="down" />}
        />
        <StatCard
          label="Avg Cost"
          value={fmtCost(costValue)}
          sublabel={<Delta pct={costTrend} goodDirection="down" />}
        />
        <StatCard
          label="Avg Latency"
          value={fmtLatency(latencyValue)}
          sublabel={<Delta pct={latencyTrend} goodDirection="down" />}
        />
        <StatCard
          label="Tool Success"
          value={fmtScore(totals.average_tool_accuracy)}
          sublabel={allTimeNote}
        />
        <StatCard
          label="Memory Usage"
          value={fmtScore(totals.average_memory_usage)}
          sublabel={allTimeNote}
        />
      </div>

      {daily.length >= 2 && <AlertsPanel alerts={alerts} onSelectDate={setSelectedDate} />}

      <BudgetsCard
        budgets={budgets}
        availableModels={availableModels}
        onAdd={addBudget}
        onDelete={removeBudget}
      />

      <PercentilesCard percentiles={percentiles} />

      {byModel.length > 0 && <ModelBreakdown rows={byModel} highlightModel={model} />}

      {costQuality.length > 0 && (
        <ChartCard
          title="Cost vs Quality"
          subtitle="bubble size = evaluations"
        >
          <ScatterChart
            data={costQuality}
            xFormat={fmtCost}
            yFormat={fmtScore}
            xLabel="Cost"
            yLabel="Score"
            label="Cost versus quality by model"
            legend={providerLegend}
          />
        </ChartCard>
      )}

      {daily.length === 0 ? (
        <EmptyState
          icon="◔"
          title={model ? "No data for this model" : "No analytics yet"}
          message={
            model
              ? `No evaluations for ${model} in the selected period. Try a wider range or "All models".`
              : "Run some evaluations to populate cost, latency and quality trends."
          }
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          {selectedDay && (
            <div className="lg:col-span-2">
              <DayDetail day={selectedDay} onClear={() => setSelectedDate(null)} />
            </div>
          )}
          <ChartCard title="Daily Cost">
            <BarChart
              data={series((d) => d.cost)}
              format={fmtCost}
              label="Daily cost"
              onSelect={toggleDay}
              selectedKey={selectedDate}
            />
          </ChartCard>
          <ChartCard title="Daily Latency">
            <BarChart
              data={series((d) => d.latency_ms)}
              format={fmtLatency}
              color="bg-sky-500/70"
              label="Daily latency"
              onSelect={toggleDay}
              selectedKey={selectedDate}
            />
          </ChartCard>
          <ChartCard title="Average Evaluation Score">
            <LineChart
              data={series((d) => d.evaluation_score)}
              format={fmtScore}
              label="Average evaluation score over time"
              onSelect={toggleDay}
              selectedKey={selectedDate}
              markers={annotationMarkers}
            />
          </ChartCard>
          <ChartCard title="Token Usage">
            <BarChart
              data={series((d) => d.tokens)}
              format={fmtNumber}
              color="bg-violet-500/70"
              label="Daily token usage"
              onSelect={toggleDay}
              selectedKey={selectedDate}
            />
          </ChartCard>
          <ChartCard title="Failure Rate">
            <BarChart
              data={series((d) => d.failure_rate)}
              format={pct}
              color="bg-rose-500/70"
              label="Daily failure rate"
              onSelect={toggleDay}
              selectedKey={selectedDate}
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

      <AnnotationsCard
        annotations={annotations}
        onAdd={addAnnotation}
        onDelete={removeAnnotation}
      />
    </div>
  );
}
