# pi/dashboard/schemas.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    name: Optional[str] = None
    driver_id: Optional[str] = None
    node_id: Optional[str] = None
    notes: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    name: Optional[str] = None
    driver_id: Optional[str] = None
    node_id: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    notes: Optional[str] = None

class SpeedPoint(BaseModel):
    t: str
    v: float


class SessionSummaryResponse(BaseModel):
    session_id: str
    row_count: int
    duration_s: float | None = None
    avg_speed_kmh: float | None = None
    max_speed_kmh: float | None = None
    avg_rpm: float | None = None
    max_rpm: float | None = None
    avg_throttle_pct: float | None = None
    max_throttle_pct: float | None = None
    avg_coolant_temp_c: float | None = None
    max_coolant_temp_c: float | None = None
    avg_engine_load_pct: float | None = None
    max_abs_accel_x: float | None = None
    max_abs_accel_y: float | None = None
    distance_km: float | None = None
    idle_pct: float | None = None
    peak_g: float | None = None
    harsh_accel_count: int | None = None
    harsh_brake_count: int | None = None
    best_0_60_s: float | None = None
    speed_trace: list[SpeedPoint] = []