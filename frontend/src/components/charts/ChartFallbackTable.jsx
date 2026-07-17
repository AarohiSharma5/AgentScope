// A visually-hidden data table that exposes a chart's underlying values to
// assistive technology (and anyone who can't rely on color/hover cues). Pair it
// with an aria-hidden visual chart so the two never read out twice.
//
// rows: [{ key?, label, value }] where `value` is already formatted for display.
export default function ChartFallbackTable({
  caption,
  columns = ["Label", "Value"],
  rows = [],
}) {
  if (rows.length === 0) return null;
  return (
    <table className="sr-only">
      {caption && <caption>{caption}</caption>}
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c} scope="col">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r.key ?? i}>
            <th scope="row">{r.label}</th>
            <td>{r.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
