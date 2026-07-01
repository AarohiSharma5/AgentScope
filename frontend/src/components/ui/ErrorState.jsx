export default function ErrorState({ message = "Something went wrong." }) {
  return (
    <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
      {message}
    </div>
  );
}
