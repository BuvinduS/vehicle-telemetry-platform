# pi/dashboard/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .routers import sessions


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    yield
    db.close_pool()


app = FastAPI(title="Vehicle Telemetry Platform API", lifespan=lifespan)
app.include_router(sessions.router)


@app.get("/health")
def health():
    return {"status": "ok"}