import { useEffect, useRef, useState } from "react";
import { EVENT_TYPES } from "./liveEvents.js";
import { getAccessToken } from "../api/authStore.js";

// Generic Server-Sent Events subscription to the backend /api/stream endpoint.
//
// Responsibilities (all connection logic; no domain knowledge):
//   * open an EventSource, filtered by `topics` (the backend ?events= param);
//   * relay each event to `onEvent({ id, type, data, timestamp })`;
//   * expose connection `status` (connecting | open | reconnecting | error | paused);
//   * support pause (close) and resume (reopen, resuming from Last-Event-ID);
//   * reconnect automatically (EventSource) and on filter changes.
//
// `onEvent` is held in a ref so changing the handler never forces a reconnect.
export function useEventStream({ topics = [], paused = false, onEvent }) {
  const [status, setStatus] = useState("connecting");
  const [lastEventId, setLastEventId] = useState(null);
  const onEventRef = useRef(onEvent);
  const lastIdRef = useRef(null);
  onEventRef.current = onEvent;

  const topicsKey = [...topics].sort().join(",");

  useEffect(() => {
    if (paused) {
      setStatus("paused");
      return undefined;
    }
    if (typeof EventSource === "undefined") {
      setStatus("error");
      return undefined;
    }

    setStatus("connecting");
    const params = new URLSearchParams();
    if (topicsKey) params.set("events", topicsKey);
    if (lastIdRef.current != null) params.set("last_event_id", lastIdRef.current);
    // EventSource cannot set request headers, so when authenticated we pass the
    // access token as a query param (the backend accepts it as a fallback).
    const token = getAccessToken();
    if (token) params.set("access_token", token);
    const query = params.toString();
    const source = new EventSource(`/api/stream${query ? `?${query}` : ""}`);

    source.onopen = () => setStatus("open");
    source.onerror = () =>
      setStatus(source.readyState === EventSource.CLOSED ? "error" : "reconnecting");

    const handler = (e) => {
      if (e.lastEventId) {
        lastIdRef.current = e.lastEventId;
        setLastEventId(e.lastEventId);
      }
      let data = {};
      try {
        data = e.data ? JSON.parse(e.data) : {};
      } catch {
        data = {};
      }
      onEventRef.current?.({
        id: e.lastEventId || null,
        type: e.type,
        data,
        timestamp: new Date().toISOString(),
      });
    };

    EVENT_TYPES.forEach((type) => source.addEventListener(type, handler));
    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicsKey, paused, getAccessToken()]);

  return { status, lastEventId };
}
