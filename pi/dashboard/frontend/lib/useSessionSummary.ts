"use client";

import { useEffect, useState } from "react";
import { getSessionSummary, SessionApiError } from "./sessionsAPI";
import type { Session, SessionSummary } from "./types";

const POLL_MS = 5000;

/**
 * Summary stats for one session. Takes the Session (not just its id) so
 * it knows whether the session is still open: open sessions are polled,
 * ended ones are fetched once. The open -> ended flip re-runs the effect,
 * which gives the final fetch with the complete stats.
 *
 * Previous data stays in place during refetches (no flicker); it's only
 * cleared when a different session is selected.
 */
export function useSessionSummary(session: Session | null) {
  const [summary, setSummary] = useState<SessionSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const id = session?.id ?? null;
  const open = session !== null && session.ended_at === null;

  useEffect(() => {
    setSummary(null);
    setError(null);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let busy = false;

    async function load() {
      if (busy) return; // a slow response must not stack up polls
      busy = true;
      setLoading(true);
      try {
        const data = await getSessionSummary(id!);
        if (!cancelled) {
          setSummary(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof SessionApiError ? err.message : "Couldn't reach the backend.");
        }
      } finally {
        busy = false;
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const timer = open ? setInterval(load, POLL_MS) : null;
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [id, open]);

  return { summary, loading, error };
}