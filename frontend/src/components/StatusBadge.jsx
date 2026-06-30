export default function StatusBadge({ status }) {
  const isSuccess = status === "success";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
        isSuccess
          ? "bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/20"
          : "bg-rose-500/10 text-rose-400 ring-1 ring-rose-500/20"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          isSuccess ? "bg-emerald-400" : "bg-rose-400"
        }`}
      />
      {isSuccess ? "Success" : "Failed"}
    </span>
  );
}
