export default function Card({ children, className = "" }) {
  return (
    <div className={`rounded-xl border border-ink-500 bg-ink-700 ${className}`}>
      {children}
    </div>
  );
}
