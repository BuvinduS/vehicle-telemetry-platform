"use client";

import { useEffect, useState } from "react";
import { useTelemetryContext } from "@/lib/telemetry-context";
import { createSession, endSession, listActiveSessions, SessionApiError } from "@/lib/sessionsAPI";
import type { Session } from "@/lib/types";

export default function SessionPanel() {
  const { activeSessions: wsSessions } = useTelemetryContext();

  const [sessions, setSessions] = useState<Session[]>([]);
  const [loaded, setLoaded] = useState(false);

  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [creating, setCreating] = useState(false);
  const [endingId, setEndingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // seed from REST once on mount
  useEffect(() => {
    listActiveSessions()
      .then(setSessions)
      .catch(() => {
        /* the WS push below will populate this shortly either way */
      })
      .finally(() => setLoaded(true));
  }, []);

  // after the initial load, trust the WS push for sessions changed elsewhere
  useEffect(() => {
    if (loaded) setSessions(wsSessions);
  }, [wsSessions, loaded]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setCreating(true);
    try {
      const session = await createSession({
        name: name.trim() || undefined,
        notes: notes.trim() || undefined,
      });
      setSessions((prev) => [...prev, session]);
      setName("");
      setNotes("");
    } catch (err) {
      setError(err instanceof SessionApiError ? err.message : "Couldn't reach the backend.");
    } finally {
      setCreating(false);
    }
  }

  async function handleEnd(id: string) {
    setError(null);
    setEndingId(id);
    try {
      const ended = await endSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== ended.id));
    } catch (err) {
      setError(err instanceof SessionApiError ? err.message : "Couldn't reach the backend.");
    } finally {
      setEndingId(null);
    }
  }

  return (
    <div
      className="flex flex-col gap-4 rounded-sm p-4"
      style={{ backgroundColor: "var(--color-panel)", border: "1px solid var(--color-hairline)" }}
    >
      <span className="text-xs font-semibold uppercase tracking-widest text-ink-dim">Sessions</span>

      <form onSubmit={handleCreate} className="flex flex-col gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Session name (optional)"
          className="text-sm px-3 py-2 rounded-sm"
          style={{ backgroundColor: "var(--color-bg)", border: "1px solid var(--color-hairline)", color: "var(--color-ink)" }}
        />
        <input
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes (optional)"
          className="text-sm px-3 py-2 rounded-sm"
          style={{ backgroundColor: "var(--color-bg)", border: "1px solid var(--color-hairline)", color: "var(--color-ink)" }}
        />
        <button
          type="submit"
          disabled={creating}
          className="text-xs font-semibold uppercase tracking-widest px-4 py-2 rounded-sm disabled:opacity-40"
          style={{ backgroundColor: "var(--color-accent)", color: "var(--color-accent-ink)" }}
        >
          {creating ? "Starting…" : "Start session"}
        </button>
        {error && <p className="text-xs" style={{ color: "var(--color-danger)" }}>{error}</p>}
      </form>

      <div className="flex flex-col gap-2 pt-2" style={{ borderTop: "1px solid var(--color-hairline)" }}>
        {sessions.length === 0 ? (
          <p className="text-sm text-ink-faint">No sessions currently open.</p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between rounded-sm px-3 py-2"
              style={{ backgroundColor: "var(--color-panel-raised)" }}
            >
              <span className="text-sm text-ink">{s.name || "Untitled session"}</span>
              <button
                onClick={() => handleEnd(s.id)}
                disabled={endingId === s.id}
                className="text-xs font-semibold uppercase tracking-widest px-2 py-1 disabled:opacity-40"
                style={{ color: "var(--color-danger)" }}
              >
                {endingId === s.id ? "Ending…" : "End"}
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}