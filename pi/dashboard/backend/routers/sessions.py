# pi/dashboard/routers/sessions.py
import uuid

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..schemas import SessionCreateRequest, SessionResponse

from .. import db, session_stats
from ..schemas import SessionCreateRequest, SessionResponse, SessionSummaryResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _row_to_response(row) -> SessionResponse:
    (session_id, name, driver_id, node_id, started_at, ended_at, notes) = row
    return SessionResponse(
        id=session_id,
        name=name,
        driver_id=driver_id,
        node_id=node_id,
        started_at=db.to_display_tz(started_at),
        ended_at=db.to_display_tz(ended_at),
        notes=notes,
    )


SELECT_COLS = "id, name, driver_id, node_id, started_at, ended_at, notes"


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(payload: SessionCreateRequest):
    """Create a new open session. started_at = NOW(), ended_at = NULL.
    architecture.md §3.3: sessions are pure metadata, acquisition is
    already decoupled — creating a session does not affect ingestion."""
    session_id = uuid.uuid4().hex
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO sessions (id, name, driver_id, node_id, notes)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {SELECT_COLS}
                """,
                (session_id, payload.name, payload.driver_id, payload.node_id, payload.notes),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_response(row)


@router.post("/{session_id}/end", response_model=SessionResponse)
def end_session(session_id: str):
    """Set ended_at explicitly to NOW(). NEVER leave this NULL on a
    finished session — see lessons-learned.md: a NULL ended_at means
    'still open, covers up to NOW()' under the §3.3 model, and would
    silently keep absorbing any telemetry written after this call."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ended_at FROM sessions WHERE id = %s", (session_id,))
            existing = cur.fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Session not found")
            if existing[0] is not None:
                raise HTTPException(status_code=409, detail="Session already ended")

            cur.execute(
                f"""
                UPDATE sessions SET ended_at = NOW()
                WHERE id = %s
                RETURNING {SELECT_COLS}
                """,
                (session_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_response(row)


@router.get("/active", response_model=list[SessionResponse])
def list_active_sessions():
    """Sessions with ended_at IS NULL. Overlapping open sessions are
    valid (architecture.md §3.3) — returns a list, not a single value,
    since more than one can legitimately be open at once."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {SELECT_COLS} FROM sessions WHERE ended_at IS NULL ORDER BY started_at"
            )
            rows = cur.fetchall()
    return [_row_to_response(r) for r in rows]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {SELECT_COLS} FROM sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _row_to_response(row)

@router.get("/{session_id}/summary", response_model=SessionSummaryResponse)
def get_session_summary(session_id: str):
    """Summary stats for one session. Membership a time-range
    join works for live and finished sessions alike."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM sessions WHERE id = %s", (session_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Session not found")

            cur.execute(
                f"""
                SELECT {", ".join(f"t.{c}" for c in session_stats.COLUMNS)}
                FROM telemetry t
                JOIN sessions s
                  ON t.time BETWEEN s.started_at AND COALESCE(s.ended_at, NOW())
                WHERE s.id = %s
                ORDER BY t.time
                """,
                (session_id,),
            )
            rows = cur.fetchall()

    summary = session_stats.summarize(rows)
    return {
        "session_id": session_id,
        **summary,
        "speed_trace": session_stats.speed_trace(rows),
    }

@router.get("", response_model=list[SessionResponse])
def list_sessions(limit: int = Query(50, ge=1, le=200)):
    """Most recent sessions first, for the dashboard's session picker.
    Includes both open and ended sessions. Capped at `limit` since the
    picker only needs recent ones and the table grows unbounded."""
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {SELECT_COLS} FROM sessions
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [_row_to_response(r) for r in rows]