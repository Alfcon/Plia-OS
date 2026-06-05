import asyncio
import json
import dataclasses
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from core import events, registry
from core.config import get_config, update_config

router = APIRouter()
_ws_clients: list[WebSocket] = []

STATIC_DIR = Path(__file__).parent / "static"


async def _broadcast(payload: dict) -> None:
    dead = []
    for ws in list(_ws_clients):
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


def setup_event_forwarding() -> None:
    """Call once at startup to wire the event bus to WebSocket clients."""
    if _broadcast not in events._subscribers:
        events.subscribe(_broadcast)


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text())


@router.get("/api/tools")
async def get_tools():
    return registry.list_tools()


@router.get("/api/config")
async def get_config_route():
    return dataclasses.asdict(get_config())


@router.post("/api/config")
async def post_config(updates: dict):
    try:
        config = update_config(**updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return dataclasses.asdict(config)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive; we only push
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
