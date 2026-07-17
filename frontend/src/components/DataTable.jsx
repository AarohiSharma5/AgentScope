import { Link } from "react-router-dom";
import { INTERACTIVE_ROW_CLASS, ROW_LINK_CLASS } from "../lib/rowInteraction.js";

// A generic, column-config-driven table for the list views. It replaces seven
// near-identical `*Table.jsx` components that all rendered the same
// overflow/border/header/row scaffolding by hand.
//
// Columns: `{ key, header, className?, primary?, render? }`. `render(row)`
// returns the cell content (defaults to `row[key]`). Exactly one column is the
// "primary" one — explicitly via `primary: true`, else the first column — and
// when `rowLink` is provided that cell's content is wrapped in a real <Link>.
// This keeps native <tr>/<td> semantics (no `role="button"` row) while making
// each row keyboard-navigable and openable in a new tab (see M8 / rowInteraction).
//
// Genuinely interactive cells (a secondary link, an action button) are just
// regular columns whose `render` returns that element — they are siblings of the
// primary link, never nested inside it.
export default function DataTable({
  columns,
  rows,
  rowKey = (row) => row.id,
  rowLink = null,
  rowLabel = null,
  minWidth = "min-w-[640px]",
  emptyMessage = null,
}) {
  const primaryKey = (columns.find((c) => c.primary) || columns[0])?.key;

  return (
    <div className="overflow-x-auto rounded-xl border border-ink-500 bg-ink-700">
      <table className={`w-full ${minWidth} text-left text-sm`}>
        <thead className="border-b border-ink-500 bg-ink-600 text-xs uppercase tracking-wider text-gray-500">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 font-medium ${col.align === "right" ? "text-right" : ""}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-600">
          {rows.map((row) => (
            <tr key={rowKey(row)} className={INTERACTIVE_ROW_CLASS}>
              {columns.map((col) => {
                const content = col.render ? col.render(row) : row[col.key];
                const isPrimary = col.key === primaryKey;
                const align = col.align === "right" ? "text-right" : "";
                return (
                  <td key={col.key} className={`px-4 py-3 ${align} ${col.className || ""}`}>
                    {isPrimary && rowLink ? (
                      <Link
                        to={rowLink(row)}
                        className={`inline-block ${ROW_LINK_CLASS}`}
                        aria-label={rowLabel ? rowLabel(row) : undefined}
                      >
                        {content}
                      </Link>
                    ) : (
                      content
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
          {rows.length === 0 && emptyMessage && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-10 text-center text-gray-500">
                {emptyMessage}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
