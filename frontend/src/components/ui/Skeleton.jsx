// Base shimmer block used to build content-shaped loading placeholders.
export default function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded bg-ink-500/60 ${className}`} />;
}
