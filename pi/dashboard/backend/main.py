# pi/dashboard/backend/main.py
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, mqtt_bridge
from .routers import sessions, ws

import os

def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3001")
    return [o.strip() for o in raw.split(",") if o.strip()]

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    loop = asyncio.get_running_loop()
    mqtt_bridge.bridge.start(loop)
    yield
    mqtt_bridge.bridge.stop()
    db.close_pool()


app = FastAPI(title="Vehicle Telemetry Platform API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(ws.router)


@app.get("/health")
def health():
    return {"status": "ok"}