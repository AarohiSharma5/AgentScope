import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import TracesTable from "../components/TracesTable.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../lib/format.js";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [traces, setTraces] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getStats(), api.getTraces()])
      .then(([s, t]) => {
        setStats(s);
        setTraces(t);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <p className="text-gray-500">Loading…</p>;
  }

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-rose-300">
        Failed to load data: {error}. Is the backend running on port 5000?
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label="Total Requests" value={fmtNumber(stats.total_requests)} />
        <StatCard label="Avg Latency" value={fmtLatency(stats.avg_latency_ms)} />
        <StatCard label="Avg Tokens" value={fmtNumber(stats.avg_tokens)} />
        <StatCard label="Avg Cost" value={fmtCost(stats.avg_cost)} />
        <StatCard
          label="Success Rate"
          value={`${stats.success_rate}%`}
          sublabel={`${traces.length} traces`}
        />
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-gray-500">
          Recent Requests
        </h2>
        <TracesTable traces={traces} />
      </div>
    </div>
  );
}
