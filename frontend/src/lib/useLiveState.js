import { useCallback, useEffect, useReducer } from "react";
import { api } from "../api/client.js";
import { useEventStream } from "./useEventStream.js";
import { initialLiveState, liveReducer } from "./liveState.js";

// Ties the SSE stream to the live reducer and seeds the running replay /
// evaluation counts from REST (those have no dedicated start event), refreshing
// them on an interval while the stream is live.
export function useLiveState({ topics = [], paused = false, refreshMs = 8000 } = {}) {
  const [state, dispatch] = useReducer(liveReducer, undefined, () => ({ ...initialLiveState }));

  const onEvent = useCallback((event) => dispatch({ type: "event", event }), []);
  const { status, lastEventId } = useEventStream({ topics, paused, onEvent });

  useEffect(() => {
    if (paused) return undefined;
    let active = true;
    const load = () => {
      Promise.all([
        api.getReplays({ status: "running", limit: 1 }).catch(() => null),
        api.getEvaluations({ status: "running", limit: 1 }).catch(() => null),
      ]).then(([replays, evaluations]) => {
        if (!active) return;
        dispatch({
          type: "seed",
          replays: replays?.pagination?.total ?? 0,
          evaluations: evaluations?.pagination?.total ?? 0,
        });
      });
    };
    load();
    const timer = setInterval(load, refreshMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [paused, refreshMs]);

  const controls = {
    clear: useCallback(() => dispatch({ type: "clear" }), []),
    reset: useCallback(() => dispatch({ type: "reset" }), []),
  };

  return { status, lastEventId, state, controls };
}
