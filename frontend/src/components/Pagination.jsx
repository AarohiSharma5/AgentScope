export default function Pagination({ page, pages, total, onChange }) {
  const safePages = Math.max(pages || 1, 1);
  const canPrev = page > 1;
  const canNext = page < safePages;

  const btn =
    "rounded-md border border-ink-500 px-3 py-1.5 text-sm text-gray-300 transition-colors enabled:hover:bg-ink-600 disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <div className="flex items-center justify-between gap-3 text-sm text-gray-500">
      <span>
        {typeof total === "number" ? `${total} run${total === 1 ? "" : "s"}` : ""}
      </span>
      <div className="flex items-center gap-2">
        <button className={btn} onClick={() => onChange(page - 1)} disabled={!canPrev}>
          Previous
        </button>
        <span className="px-1 text-gray-400">
          Page {page} of {safePages}
        </span>
        <button className={btn} onClick={() => onChange(page + 1)} disabled={!canNext}>
          Next
        </button>
      </div>
    </div>
  );
}
