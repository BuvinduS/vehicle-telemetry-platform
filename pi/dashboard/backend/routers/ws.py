# pi/dashboard/backend/routers/ws.py
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import mqtt_bridge

log = logging.getLogger("ws_router")

router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await mqtt_bridge.manager.connect(websocket)
    try:
        # Send current active sessions immediately on connect, rather
        # than making the client wait for the next poll tick.
        sessions = mqtt_bridge._fetch_active_sessions()
        await mqtt_bridge.manager.send_to(websocket, {"type": "active_sessions", "data": sessions})

        # Server is push-only; just keep the connection alive and detect
        # disconnects. Client isn't expected to send anything.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await mqtt_bridge.manager.disconnect(websocket)