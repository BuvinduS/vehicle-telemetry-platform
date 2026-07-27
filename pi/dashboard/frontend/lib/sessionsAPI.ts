import { apiBaseUrl } from "./config";
import type { Session } from "./types";

export class SessionApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle(res: Response) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* body wasn't JSON — keep statusText */
    }
    throw new SessionApiError(res.status, detail);
  }
  return res.json();
}

export interface CreateSessionInput {
  name?: string;
  driver_id?: string;
  node_id?: string | null;
  notes?: string;
}

export async function createSession(input: CreateSessionInput): Promise<Session> {
  const res = await fetch(`${apiBaseUrl()}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return handle(res);
}

export async function endSession(sessionId: string): Promise<Session> {
  const res = await fetch(`${apiBaseUrl()}/sessions/${sessionId}/end`, { method: "POST" });
  return handle(res);
}

export async function listActiveSessions(): Promise<Session[]> {
  const res = await fetch(`${apiBaseUrl()}/sessions/active`);
  return handle(res);
}