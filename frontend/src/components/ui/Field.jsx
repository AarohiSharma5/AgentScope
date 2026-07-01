const EMPTY = <span className="text-gray-600">—</span>;

function isEmpty(value) {
  return value === undefined || value === null || value === "";
}

export default function Field({ label, value, children, className = "" }) {
  const content = children ?? (isEmpty(value) ? EMPTY : value);
  return (
    <div className={className}>
      <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <div className="mt-1 break-words text-sm text-gray-200">{content}</div>
    </div>
  );
}
