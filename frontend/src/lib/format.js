// Shared formatting helpers.

export const fmtNumber = (n) =>
  n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });

export const fmtLatency = (ms) =>
  ms == null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;

export const fmtCost = (c) => (c == null ? "—" : `$${Number(c).toFixed(4)}`);

export const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

// Duration between two ISO timestamps, formatted like a latency.
export const fmtDuration = (startIso, endIso) => {
  if (!startIso || !endIso) return "—";
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (Number.isNaN(ms) || ms < 0) return "—";
  return fmtLatency(ms);
};
