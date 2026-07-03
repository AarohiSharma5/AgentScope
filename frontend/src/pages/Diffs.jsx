import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client.js";
import PromptDiff from "../components/eval/PromptDiff.jsx";
import TraceDiff from "../components/eval/TraceDiff.jsx";
import Card from "../components/ui/Card.jsx";
import Section from "../components/ui/Section.jsx";
import Loading from "../components/ui/Loading.jsx";
import EmptyState from "../components/ui/EmptyState.jsx";
import ErrorState from "../components/ui/ErrorState.jsx";
import { fmtTime } from "../lib/format.js";

const INPUT =
  "rounded-lg border border-ink-500 bg-ink-800 px-3 py-2 text-sm text-gray-200 placeholder-gray-600 outline-none focus:border-accent";

function CompareForm({ labelA, labelB, a, b, onA, onB, onCompare, busy }) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onCompare();
      }}
      className="flex flex-col gap-3 md:flex-row md:items-end"
    >
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wider text-gray-500">{labelA}</span>
        <input type="number" value={a} onChange={(e) => onA(e.target.value)}
          placeholder="id" className={`${INPUT} w-full md:w-40`} />
      </label>
      <span className="hidden pb-2 text-gray-600 md:block">vs</span>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-wider text-gray-500">{labelB}</span>
        <input type="number" value={b} onChange={(e) => onB(e.target.value)}
          placeholder="id" className={`${INPUT} w-full md:w-40`} />
      </label>
      <button type="submit" disabled={busy}
        className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50">
        {busy ? "Comparing…" : "Compare"}
      </button>
    </form>
  );
}

// Optional helper: list an agent run's captured prompt versions and let the
// user pick A / B by clicking.
function VersionBrowser({ onPick }) {
  const [runId, setRunId] = useState("");
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function load(e) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.getPromptVersions({ agent_run_id: runId, limit: 50 });
      setVersions(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="p-5">
      <form onSubmit={load} className="flex items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wider text-gray-500">Agent run ID</span>
          <input type="number" value={runId} onChange={(e) => setRunId(e.target.value)}
            placeholder="e.g. 1" className={`${INPUT} w-40`} />
        </label>
        <button type="submit"
          className="rounded-lg border border-ink-500 px-4 py-2 text-sm text-gray-200 transition-colors hover:bg-ink-600">
          Load versions
        </button>
      </form>
      {loading && <div className="mt-3"><Loading label="Loading versions…" /></div>}
      {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
      {!loading && versions.length > 0 && (
        <ul className="mt-4 divide-y divide-ink-600 text-sm">
          {versions.map((v) => (
            <li key={v.id} className="flex items-center gap-3 py-2">
              <span className="font-mono text-gray-500">#{v.id}</span>
              <span className="font-medium text-gray-200">{v.version}</span>
              <span className="text-xs text-gray-500">{fmtTime(v.created_at)}</span>
              <span className="ml-auto flex gap-1">
                <button onClick={() => onPick("a", v.id)}
                  className="rounded-md bg-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-500">
                  Set A
                </button>
                <button onClick={() => onPick("b", v.id)}
                  className="rounded-md bg-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-500">
                  Set B
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function DiffPanel({ tab, a, b }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const idA = Number(a);
    const idB = Number(b);
    if (!Number.isInteger(idA) || !Number.isInteger(idB) || idA <= 0 || idB <= 0) {
      setResult(null);
      setError(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    const fetcher = tab === "prompt" ? api.getPromptDiff : api.getTraceDiff;
    fetcher(idA, idB)
      .then((res) => active && setResult(res))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [tab, a, b]);

  if (loading) return <Loading label="Computing diff…" />;
  if (error) return <ErrorState message={`Failed to load diff: ${error}`} />;
  if (!result)
    return (
      <EmptyState
        icon="⇄"
        title="Nothing to compare yet"
        message={
          tab === "prompt"
            ? "Enter two prompt version IDs above to see a word-level diff."
            : "Enter two conversation IDs above to compare their traces."
        }
      />
    );
  return tab === "prompt" ? <PromptDiff diff={result} /> : <TraceDiff diff={result} />;
}

export default function Diffs() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "trace" ? "trace" : "prompt";
  const a = params.get("a") || "";
  const b = params.get("b") || "";

  // Local input state (committed to the URL on "Compare").
  const [inputA, setInputA] = useState(a);
  const [inputB, setInputB] = useState(b);

  useEffect(() => {
    setInputA(a);
    setInputB(b);
  }, [a, b]);

  const setTab = (next) => {
    const p = new URLSearchParams(params);
    p.set("tab", next);
    p.delete("a");
    p.delete("b");
    setParams(p);
    setInputA("");
    setInputB("");
  };

  const compare = () => {
    const p = new URLSearchParams(params);
    p.set("tab", tab);
    p.set("a", inputA);
    p.set("b", inputB);
    setParams(p);
  };

  const pick = (which, id) => {
    if (which === "a") setInputA(String(id));
    else setInputB(String(id));
  };

  const tabButton = (value, label) => (
    <button
      type="button"
      onClick={() => setTab(value)}
      className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
        tab === value ? "bg-ink-500 text-gray-100" : "text-gray-400 hover:text-gray-200"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-100">Diffs</h1>
        <p className="mt-1 text-sm text-gray-500">
          Compare prompt versions or entire traces side by side, with changes highlighted.
        </p>
      </div>

      <div className="flex items-center gap-1 rounded-lg border border-ink-500 bg-ink-800 p-1">
        {tabButton("prompt", "Prompt Diff")}
        {tabButton("trace", "Trace Diff")}
      </div>

      <Section title={tab === "prompt" ? "Compare prompt versions" : "Compare traces"}>
        <Card className="p-5">
          <CompareForm
            labelA={tab === "prompt" ? "Version A" : "Conversation A"}
            labelB={tab === "prompt" ? "Version B" : "Conversation B"}
            a={inputA}
            b={inputB}
            onA={setInputA}
            onB={setInputB}
            onCompare={compare}
          />
        </Card>
      </Section>

      {tab === "prompt" && (
        <Section title="Browse prompt versions">
          <VersionBrowser onPick={pick} />
        </Section>
      )}

      <DiffPanel tab={tab} a={a} b={b} />
    </div>
  );
}
