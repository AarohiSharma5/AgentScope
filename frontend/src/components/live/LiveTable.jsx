import { memo, useEffect, useRef, useState } from "react";
import EmptyState from "../ui/EmptyState.jsx";

// A single row that briefly flashes whenever its `updatedAt` changes, so live
// updates are visible without a full re-render of the table.
//
// Wrapped in React.memo so that, during a high-frequency event stream, only the
// rows whose object identity actually changed re-render. The live reducer
// produces immutable updates (unchanged rows keep the same reference), and the
// column config is a stable module-level constant, so this is safe and removes
// most of the per-event render cost on a busy dashboard.
const LiveRow = memo(function LiveRow({ row, columns }) {
  const prev = useRef(row.updatedAt);
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (prev.current !== undefined && prev.current !== row.updatedAt) {
      setFlash(true);
      const timer = setTimeout(() => setFlash(false), 1100);
      return () => clearTimeout(timer);
    }
    prev.current = row.updatedAt;
    return undefined;
  }, [row.updatedAt]);

  useEffect(() => {
    prev.current = row.updatedAt;
  });

  return (
    <tr className={flash ? "live-flash" : ""}>
      {columns.map((col) => (
        <td key={col.key} className={`px-4 py-2.5 ${col.className || ""}`}>
          {col.render ? col.render(row) : row[col.key]}
        </td>
      ))}
    </tr>
  );
});

// Generic real-time table driven by a column config. Reused for every live
// listing (conversations, agents, …) so no table markup is duplicated.
export default function LiveTable({ columns, rows, rowKey = (r) => r.id, empty }) {
  if (!rows.length) {
    return <EmptyState icon="◌" message={empty || "Nothing running right now."} />;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            {columns.map((col) => (
              <th key={col.key} className="px-4 py-2.5 font-medium">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {rows.map((row) => (
            <LiveRow key={rowKey(row)} row={row} columns={columns} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
