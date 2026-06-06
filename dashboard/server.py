import asyncio
import json
import dataclasses
import shutil
import threading
import numpy as np
from datetime import datetime
from scipy.io import wavfile
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from pathlib import Path
from core import events, registry
from core.config import get_config, update_config

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None  # type: ignore[assignment]

_RECORD_SAMPLE_RATE = 16_000


class _Recorder:
    def __init__(self) -> None:
        self.active: bool = False
        self.thread: threading.Thread | None = None
        self.chunks: list[np.ndarray] = []
        self._stop_event: threading.Event = threading.Event()


_recorder = _Recorder()

UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

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


@router.post("/api/upload-reference-audio")
async def upload_reference_audio(file: UploadFile = File(...)):
    dest = UPLOADS_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    update_config(chatterbox_reference_audio=str(dest))
    return {"path": str(dest), "filename": file.filename}


@router.post("/api/start-recording")
async def start_recording():
    if _recorder.active:
        raise HTTPException(status_code=409, detail="Already recording")
    if sd is None:
        raise HTTPException(status_code=500, detail="sounddevice not available")
    _recorder.chunks = []
    _recorder._stop_event.clear()
    _recorder.active = True

    def _run() -> None:
        def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            if not _recorder._stop_event.is_set():
                _recorder.chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=_RECORD_SAMPLE_RATE, channels=1, dtype="int16", callback=_callback
        ):
            _recorder._stop_event.wait()

    _recorder.thread = threading.Thread(target=_run, daemon=True)
    _recorder.thread.start()
    return {"recording": True}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive; we only push
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
