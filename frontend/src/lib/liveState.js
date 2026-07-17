// Pure, unit-testable reducer that folds the live event stream into the state
// the dashboard renders (running conversations/agents, session aggregates and a
// capped activity feed). Kept free of React so it can be tested directly.

const FEED_LIMIT = 60;
const RUNNING = "running";

// Finished conversations/agents are kept briefly for context, then evicted so a
// long-lived Live session can't grow its maps without bound (a memory leak on a
// page that is meant to stay open for hours). Running rows are never evicted.
const FINISHED_TTL_MS = 5 * 60 * 1000; // drop finished rows older than 5 minutes
const MAX_FINISHED_ROWS = 50; // and cap how many finished rows we retain (LRU)

export const initialLiveState = {
  conversations: {}, // id -> { id, name, status, phase, latency_ms, updatedAt }
  agents: {}, // runId -> { id, name, type, status, parentRunId, requestId, latency_ms, updatedAt }
  totals: { tokens: 0, cost: 0, steps: 0, latencySum: 0, latencyCount: 0, events: 0 },
  feed: [], // most-recent-first list of { id, type, data, timestamp }
  seededReplays: 0, // running replays, seeded from REST
  seededEvaluations: 0, // running evaluations, seeded from REST
  lastActivityAt: null,
};

function tokensFrom(usage) {
  if (!usage) return 0;
  return usage.total ?? (usage.input || 0) + (usage.output || 0);
}

function applyEvent(state, event) {
  const { type, data = {}, timestamp } = event;
  const now = timestamp || new Date().toISOString();
  const totals = { ...state.totals, events: state.totals.events + 1 };
  let { conversations, agents, seededEvaluations } = state;

  switch (type) {
    case "workflow.updated": {
      const id = data.conversation_run_id;
      if (id != null) {
        const finished =
          data.phase === "finished" ||
          ["success", "failed", "cancelled", "timeout"].includes(data.status);
        conversations = {
          ...conversations,
          [id]: {
            id,
            name: data.conversation_name ?? conversations[id]?.name ?? null,
            status: finished ? data.status || "success" : RUNNING,
            phase: data.phase ?? conversations[id]?.phase ?? null,
            latency_ms: data.latency_ms ?? conversations[id]?.latency_ms ?? null,
            updatedAt: now,
          },
        };
      }
      break;
    }
    case "agent.started":
    case "agent.finished": {
      const id = data.run_id;
      if (id != null) {
        const finished = type === "agent.finished";
        agents = {
          ...agents,
          [id]: {
            id,
            name: data.agent_name ?? agents[id]?.name ?? `agent-${id}`,
            type: data.agent_type ?? agents[id]?.type ?? null,
            parentRunId: data.parent_run_id ?? agents[id]?.parentRunId ?? null,
            requestId: data.request_id ?? agents[id]?.requestId ?? null,
            status: finished ? data.status || "success" : RUNNING,
            latency_ms: data.latency_ms ?? agents[id]?.latency_ms ?? null,
            updatedAt: now,
          },
        };
      }
      break;
    }
    case "step.started":
      totals.steps += 1;
      break;
    case "step.finished": {
      totals.tokens += tokensFrom(data.token_usage);
      totals.cost += data.cost || 0;
      if (data.latency_ms != null) {
        totals.latencySum += data.latency_ms;
        totals.latencyCount += 1;
      }
      break;
    }
    case "evaluation.finished":
      seededEvaluations = Math.max(0, state.seededEvaluations - 1);
      break;
    default:
      break;
  }

  const nowMs = Date.parse(now) || Date.now();
  const feed = [{ ...event, timestamp: now }, ...state.feed].slice(0, FEED_LIMIT);
  return {
    ...state,
    conversations: evictFinished(conversations, nowMs),
    agents: evictFinished(agents, nowMs),
    totals,
    seededEvaluations,
    feed,
    lastActivityAt: now,
  };
}

// Drop finished rows that are older than the TTL, then LRU-evict the oldest
// finished rows beyond the cap. Running rows are always retained. Returns the
// same map reference when nothing is evicted so selectors can memoize on it.
function evictFinished(map, nowMs) {
  const finished = [];
  for (const key in map) {
    if (map[key].status !== RUNNING) finished.push(key);
  }
  if (!finished.length) return map;

  const ageOf = (key) => nowMs - (Date.parse(map[key].updatedAt) || nowMs);
  const doomed = new Set(finished.filter((key) => ageOf(key) > FINISHED_TTL_MS));

  const survivors = finished.filter((key) => !doomed.has(key));
  if (survivors.length > MAX_FINISHED_ROWS) {
    survivors.sort((a, b) => ageOf(b) - ageOf(a)); // oldest (largest age) first
    for (let i = 0; i < survivors.length - MAX_FINISHED_ROWS; i += 1) {
      doomed.add(survivors[i]);
    }
  }
  if (!doomed.size) return map;

  const next = {};
  for (const key in map) {
    if (!doomed.has(key)) next[key] = map[key];
  }
  return next;
}

export function liveReducer(state, action) {
  switch (action.type) {
    case "event":
      return applyEvent(state, action.event);
    case "seed":
      return {
        ...state,
        seededReplays: action.replays ?? state.seededReplays,
        seededEvaluations: action.evaluations ?? state.seededEvaluations,
      };
    case "clear":
      // Clear the feed and any finished rows, keeping active work + seeds.
      return {
        ...state,
        feed: [],
        conversations: pickRunning(state.conversations),
        agents: pickRunning(state.agents),
        totals: { ...initialLiveState.totals },
      };
    case "reset":
      return { ...initialLiveState };
    default:
      return state;
  }
}

function pickRunning(map) {
  return Object.fromEntries(
    Object.entries(map).filter(([, v]) => v.status === RUNNING)
  );
}

// -- Selectors --------------------------------------------------------------

export function selectCounts(state) {
  const conversations = Object.values(state.conversations);
  const agents = Object.values(state.agents);
  return {
    runningConversations: conversations.filter((c) => c.status === RUNNING).length,
    runningAgents: agents.filter((a) => a.status === RUNNING).length,
    runningReplays: state.seededReplays,
    runningEvaluations: state.seededEvaluations,
  };
}

export function selectAverageLatency(state) {
  const { latencySum, latencyCount } = state.totals;
  return latencyCount ? latencySum / latencyCount : null;
}

// Rows for the live tables, most-recently-updated first.
//
// Sorting the whole map on every event/render is wasteful: with a high event
// rate these selectors run on each dispatch even when their slice of state did
// not change. Because the reducer keeps the ``conversations``/``agents``
// reference stable when a given event doesn't touch it, we memoize on that
// reference and recompute only when it actually changes.
function memoizeByMap(compute) {
  let lastMap;
  let lastResult;
  return (map) => {
    if (map !== lastMap) {
      lastMap = map;
      lastResult = compute(map);
    }
    return lastResult;
  };
}

const conversationRowsOf = memoizeByMap((map) => Object.values(map).sort(byUpdatedDesc));
const agentRowsOf = memoizeByMap((map) => Object.values(map).sort(byUpdatedDesc));

export function selectConversationRows(state) {
  return conversationRowsOf(state.conversations);
}

export function selectAgentRows(state) {
  return agentRowsOf(state.agents);
}

// Running-only rows for the "Running Agents" table (memoized on the full rows).
const runningAgentRowsOf = memoizeByMap((rows) => rows.filter((a) => a.status === RUNNING));

export function selectRunningAgentRows(state) {
  return runningAgentRowsOf(selectAgentRows(state));
}

const byUpdatedDesc = (a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || "");
