import { useEffect, useRef } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard.jsx";
import TraceDetail from "./pages/TraceDetail.jsx";
import AgentRuns from "./pages/AgentRuns.jsx";
import AgentRunDetail from "./pages/AgentRunDetail.jsx";
import RetrievalList from "./pages/RetrievalList.jsx";
import RetrievalDetail from "./pages/RetrievalDetail.jsx";
import PromptViewer from "./pages/PromptViewer.jsx";
import Workflows from "./pages/Workflows.jsx";
import WorkflowDetail from "./pages/WorkflowDetail.jsx";
import Conversations from "./pages/Conversations.jsx";
import ConversationDetail from "./pages/ConversationDetail.jsx";
import Replays from "./pages/Replays.jsx";
import ReplayDetail from "./pages/ReplayDetail.jsx";
import Evaluations from "./pages/Evaluations.jsx";
import EvaluationDetail from "./pages/EvaluationDetail.jsx";
import Comparisons from "./pages/Comparisons.jsx";
import Analytics from "./pages/Analytics.jsx";
import Diffs from "./pages/Diffs.jsx";
import Live from "./pages/Live.jsx";
import Login from "./pages/Login.jsx";
import EmptyState from "./components/ui/EmptyState.jsx";
import { useAuth } from "./lib/AuthContext.jsx";
import { IS_DEMO } from "./lib/demo.js";

function NotFound() {
  return (
    <EmptyState
      icon="?"
      title="Page not found"
      message="The page you’re looking for doesn’t exist."
      action={
        <Link
          to="/"
          className="rounded-lg border border-ink-500 bg-ink-700 px-4 py-2 text-sm text-gray-200 transition-colors hover:bg-ink-600"
        >
          Back to dashboard
        </Link>
      }
    />
  );
}

function DemoBanner() {
  if (!IS_DEMO) return null;
  return (
    <div className="bg-amber-500/15 text-amber-200 border-b border-amber-500/30">
      <div className="mx-auto max-w-6xl px-6 py-2 text-center text-xs sm:text-sm">
        <span className="font-medium">Live demo</span> — read-only, seeded with
        sample data that resets periodically. Explore freely; changes are disabled.
      </div>
    </div>
  );
}

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

function SessionControls() {
  const { status, user, authRequired, logout, requestLogin } = useAuth();
  if (status === "authenticated") {
    return (
      <div className="flex items-center gap-3">
        {user?.email && (
          <span className="hidden text-sm text-gray-400 sm:inline">{user.email}</span>
        )}
        <button
          onClick={logout}
          className="rounded-md border border-ink-500 bg-ink-700 px-3 py-1.5 text-sm text-gray-300 transition-colors hover:bg-ink-600"
        >
          Sign out
        </button>
      </div>
    );
  }
  // In open mode we don't nag; only offer sign-in once it's relevant.
  if (authRequired) return null; // the gate is already shown
  return (
    <button
      onClick={requestLogin}
      className="text-sm text-gray-400 transition-colors hover:text-gray-200"
    >
      Sign in
    </button>
  );
}

export default function App() {
  const { status, authRequired } = useAuth();
  // Show the login gate when the backend requires auth and we have no session.
  const showLoginGate = authRequired && status !== "authenticated";

  // On each client-side navigation, move focus to the main region so keyboard
  // and screen-reader users land on the new page's content instead of being
  // stranded at the top of the (unchanged) header.
  const location = useLocation();
  const mainRef = useRef(null);
  useEffect(() => {
    mainRef.current?.focus();
  }, [location.pathname]);

  return (
    <div className="min-h-full">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20 focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        Skip to content
      </a>
      <DemoBanner />
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
            <nav className="flex flex-wrap items-center gap-1">
              <NavItem to="/" label="Requests" end />
              <NavItem to="/agent-runs" label="Agent Runs" />
              <NavItem to="/retrievals" label="RAG Observatory" />
              <NavItem to="/workflows" label="Workflows" />
              <NavItem to="/conversations" label="Conversations" />
              <NavItem to="/replays" label="Replays" />
              <NavItem to="/evaluations" label="Evaluations" />
              <NavItem to="/comparisons" label="Comparisons" />
              <NavItem to="/diffs" label="Diffs" />
              <NavItem to="/analytics" label="Analytics" />
              <NavItem
                to="/live"
                label={
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    Live
                  </span>
                }
              />
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <a
              href="https://github.com/AarohiSharma5/AgentScope/tree/main/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-gray-400 transition-colors hover:text-gray-200"
            >
              Docs
            </a>
            <SessionControls />
          </div>
        </div>
      </header>

      <main
        id="main-content"
        ref={mainRef}
        tabIndex={-1}
        className="mx-auto max-w-6xl px-6 py-8 focus:outline-none"
      >
        {showLoginGate ? (
          <Login />
        ) : (
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/traces/:id" element={<TraceDetail />} />
          <Route path="/agent-runs" element={<AgentRuns />} />
          <Route path="/agent-runs/:id" element={<AgentRunDetail />} />
          <Route path="/retrievals" element={<RetrievalList />} />
          <Route path="/retrievals/:id" element={<RetrievalDetail />} />
          <Route path="/prompts/:id" element={<PromptViewer />} />
          <Route path="/workflows" element={<Workflows />} />
          <Route path="/workflows/:id" element={<WorkflowDetail />} />
          <Route path="/conversations" element={<Conversations />} />
          <Route path="/conversations/:id" element={<ConversationDetail />} />
          <Route path="/replays" element={<Replays />} />
          <Route path="/replays/:id" element={<ReplayDetail />} />
          <Route path="/evaluations" element={<Evaluations />} />
          <Route path="/evaluations/:id" element={<EvaluationDetail />} />
          <Route path="/comparisons" element={<Comparisons />} />
          <Route path="/diffs" element={<Diffs />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/live" element={<Live />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        )}
      </main>
    </div>
  );
}
