# pi/dashboard/backend/main.py
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db, mqtt_bridge
from .routers import sessions, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    loop = asyncio.get_running_loop()
    mqtt_bridge.bridge.start(loop)
    yield
    mqtt_bridge.bridge.stop()
    db.close_pool()


app = FastAPI(title="Vehicle Telemetry Platform API", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(ws.router)


@app.get("/health")
def health():
    return {"status": "ok"}