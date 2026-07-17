import { useEffect, useState } from "react";
import { api } from "../api/client.js";
import StatCard from "../components/StatCard.jsx";
import TracesTable from "../components/TracesTable.jsx";
import Loading from "../components/ui/Loading.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import { fmtCost, fmtLatency, fmtNumber } from "../lib/format.js";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [traces, setTraces] = useState([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getStats(), api.getTraces()])
      .then(([s, t]) => {
        setStats(s);
        setTraces(t.data);
        setTotal(t.pagination?.total ?? t.data.length);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <Loading label="Loading dashboard…" />;
  }

  if (error) {
    return (
      <ErrorState message={`Failed to load data: ${error}. Is the backend running?`} />
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
          sublabel={`${total} traces`}
        />
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wider text-gray-500">
          Recent Requests
        </h2>
        {traces.length === 0 ? (
          <EmptyState
            icon="◇"
            title="No requests yet"
            message="Send an LLM request trace to POST /api/traces (or run the chat flow) to populate the dashboard."
          />
        ) : (
          <TracesTable traces={traces} />
        )}
      </div>
    </div>
  );
}
