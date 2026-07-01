export default function Loading({ label = "Loading…" }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-sm text-gray-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-500 border-t-accent" />
      {label}
    </div>
  );
}
