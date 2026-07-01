import Skeleton from "./Skeleton.jsx";

// Table-shaped loading placeholder. Mirrors the real table's column count so
// the layout doesn't jump when data arrives.
export default function TableSkeleton({ columns = 8, rows = 6 }) {
  return (
    <div className="overflow-hidden rounded-xl border border-ink-500 bg-ink-700">
      <div className="flex gap-4 border-b border-ink-500 bg-ink-600 px-4 py-3">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={i} className="h-3 flex-1" />
        ))}
      </div>
      <div className="divide-y divide-ink-600">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-4 px-4 py-4">
            {Array.from({ length: columns }).map((_, c) => (
              <Skeleton key={c} className="h-4 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
