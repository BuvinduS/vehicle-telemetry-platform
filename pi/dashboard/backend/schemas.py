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