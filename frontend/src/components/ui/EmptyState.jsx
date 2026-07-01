export default function EmptyState({ message = "Nothing here yet." }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-500 bg-ink-800/50 px-4 py-10 text-center text-sm text-gray-500">
      {message}
    </div>
  );
}
