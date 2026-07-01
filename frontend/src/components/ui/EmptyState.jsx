// Empty state with an optional title, hint and action.
// Backward compatible: <EmptyState message="…" /> still renders a simple hint.
export default function EmptyState({
  title,
  message = "Nothing here yet.",
  icon = "○",
  action = null,
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-ink-500 bg-ink-800/50 px-6 py-12 text-center">
      <div
        aria-hidden
        className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-ink-500 bg-ink-700 text-lg text-gray-500"
      >
        {icon}
      </div>
      {title && <p className="text-sm font-medium text-gray-300">{title}</p>}
      <p className="mt-1 max-w-sm text-sm text-gray-500">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
