export default function StatCard({ label, value, sublabel }) {
  return (
    <div className="rounded-xl border border-ink-500 bg-ink-700 p-5 transition-colors hover:border-accent/50">
      <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold text-gray-100">{value}</p>
      {sublabel && <p className="mt-1 text-xs text-gray-500">{sublabel}</p>}
    </div>
  );
}
