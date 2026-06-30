import { Link, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import TraceDetail from "./pages/TraceDetail.jsx";

export default function App() {
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-ink-500 bg-ink-800/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link to="/" className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm font-bold text-white">
              A
            </span>
            <span className="text-base font-semibold text-gray-100">
              AgentScope
            </span>
            <span className="ml-1 rounded-md bg-ink-500 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-gray-400">
              Tracer
            </span>
          </Link>
          <a
            href="https://github.com"
            className="text-sm text-gray-400 transition-colors hover:text-gray-200"
          >
            Docs
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/traces/:id" element={<TraceDetail />} />
        </Routes>
      </main>
    </div>
  );
}
