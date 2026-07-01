export default function Section({ title, count, action, children }) {
  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wider text-gray-500">
          {title}
          {typeof count === "number" && (
            <span className="rounded-md bg-ink-500 px-1.5 py-0.5 text-xs font-normal text-gray-400">
              {count}
            </span>
          )}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}
