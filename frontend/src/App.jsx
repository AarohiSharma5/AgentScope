import { Link, NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import TraceDetail from "./pages/TraceDetail.jsx";
import AgentRuns from "./pages/AgentRuns.jsx";
import AgentRunDetail from "./pages/AgentRunDetail.jsx";

function NavItem({ to, label, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `rounded-md px-3 py-1.5 text-sm transition-colors ${
          isActive
            ? "bg-ink-600 text-gray-100"
            : "text-gray-400 hover:text-gray-200"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-ink-500 bg-ink-800/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-2">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm font-bold text-white">
                A
              </span>
              <span className="text-base font-semibold text-gray-100">
                AgentScope
              </span>
            </Link>
            <nav className="flex items-center gap-1">
              <NavItem to="/" label="Requests" end />
              <NavItem to="/agent-runs" label="Agent Runs" />
            </nav>
          </div>
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
          <Route path="/agent-runs" element={<AgentRuns />} />
          <Route path="/agent-runs/:id" element={<AgentRunDetail />} />
        </Routes>
      </main>
    </div>
  );
}
