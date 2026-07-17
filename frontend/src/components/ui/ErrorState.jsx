// Inline error banner. Uses role="alert" so assistive tech announces it the
// moment it appears, and offers an optional retry affordance.
export default function ErrorState({
  message = "Something went wrong.",
  onRetry = null,
  retryLabel = "Retry",
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200"
    >
      <span>{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-rose-400/40 px-3 py-1 text-xs font-medium text-rose-100 transition-colors hover:bg-rose-500/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}
