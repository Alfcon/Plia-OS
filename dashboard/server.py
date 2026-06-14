import asyncio
import json
import dataclasses
import logging
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
from voice.tts import get_tts_service
from voice.vram_broker import get_vram_broker

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover
    sd = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

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
_recent_notifications: list[dict] = []  # replay buffer for clients that connect after startup
_NOTIFICATION_REPLAY_TYPES = {"reminder_fired"}
_NOTIFICATION_REPLAY_MAX = 20

STATIC_DIR = Path(__file__).parent / "static"


async def _broadcast(payload: dict) -> None:
    if payload.get("type") in _NOTIFICATION_REPLAY_TYPES:
        _recent_notifications.append(payload)
        if len(_recent_notifications) > _NOTIFICATION_REPLAY_MAX:
            _recent_notifications.pop(0)
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
async def upload_reference_audio(file: UploadFile = File(...), target: str = "chatterbox"):
    raw = Path(file.filename or "upload").name or "upload"
    safe_name = raw if raw not in (".", "..") else "upload"
    dest = UPLOADS_DIR / safe_name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    if target == "dramabox":
        update_config(dramabox_voice_ref=str(dest))
    else:
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
        try:
            def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
                if not _recorder._stop_event.is_set():
                    _recorder.chunks.append(indata.copy())

            with sd.InputStream(
                samplerate=_RECORD_SAMPLE_RATE, channels=1, dtype="int16", callback=_callback
            ):
                _recorder._stop_event.wait()
        except Exception:
            logger.warning("Recording thread error", exc_info=True)
        finally:
            _recorder.active = False
            _recorder.thread = None

    _recorder.thread = threading.Thread(target=_run, daemon=True)
    _recorder.thread.start()
    return {"recording": True}


@router.post("/api/stop-recording")
async def stop_recording(target: str = "chatterbox"):
    if not _recorder.active:
        raise HTTPException(status_code=409, detail="Not recording")
    _recorder._stop_event.set()
    t = _recorder.thread
    if t is not None:
        t.join(timeout=2.0)
        if t.is_alive():
            logger.warning("Recording thread did not exit within 2 s — sounddevice may be hung")
        else:
            _recorder.thread = None
    _recorder.active = False
    _recorder._stop_event.clear()

    if not _recorder.chunks:
        raise HTTPException(status_code=500, detail="No audio captured")

    audio = np.concatenate(_recorder.chunks, axis=0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = UPLOADS_DIR / f"recording_{ts}.wav"
    wavfile.write(str(dest), _RECORD_SAMPLE_RATE, audio)
    _recorder.chunks = []
    if target == "dramabox":
        update_config(dramabox_voice_ref=str(dest))
    else:
        update_config(chatterbox_reference_audio=str(dest))
    return {"path": str(dest), "filename": dest.name}


@router.post("/api/generate-dramabox")
async def generate_dramabox(body: dict):
    svc = get_tts_service()
    if svc is None:
        raise HTTPException(status_code=409, detail="TTS service not available")
    await asyncio.to_thread(svc._ensure_dramabox, get_config())
    if svc._dramabox is None:
        raise HTTPException(status_code=409, detail="Dramabox failed to load")
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt required")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = UPLOADS_DIR / f"dramabox_{ts}.wav"
    loop = asyncio.get_event_loop()

    def _progress(chunk_idx: int, total: int, est_dur: float) -> None:
        asyncio.run_coroutine_threadsafe(
            _broadcast({
                "type": "dramabox_progress",
                "chunk": chunk_idx + 1,
                "total": total,
                "est_duration_s": round(est_dur, 1),
            }),
            loop,
        )

    await asyncio.to_thread(
        svc._dramabox.generate_to_file, prompt, str(dest), _progress
    )
    return {"path": str(dest), "filename": dest.name}


@router.post("/api/generate-chatterbox")
async def generate_chatterbox(body: dict):
    svc = get_tts_service()
    if svc is None:
        raise HTTPException(status_code=409, detail="TTS service not available")
    await asyncio.to_thread(svc._ensure_chatterbox, get_config())
    if svc._chatterbox is None:
        raise HTTPException(status_code=409, detail="Chatterbox failed to load")
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt required")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = UPLOADS_DIR / f"chatterbox_{ts}.wav"

    def _synth_and_write():
        audio = svc._synthesise_chatterbox(prompt)
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        wavfile.write(str(dest), 24_000, pcm)

    await asyncio.to_thread(_synth_and_write)
    return {"path": str(dest), "filename": dest.name}


@router.get("/api/history")
async def get_history(n: int = 100):
    from agents.chat_history import get_recent
    return await asyncio.to_thread(get_recent, n)


@router.delete("/api/history")
async def clear_history():
    from agents.chat_history import clear
    from agents.memory_store import get_memory_store

    def _clear_all() -> None:
        clear()
        get_memory_store().clear_history()

    await asyncio.to_thread(_clear_all)
    await events.emit("clear_history", {})
    return {"status": "cleared"}


@router.get("/api/reminders")
async def list_reminders():
    from agents.memory_store import get_memory_store
    return await asyncio.to_thread(get_memory_store().list_pending)


@router.delete("/api/reminders/{reminder_id}")
async def cancel_reminder(reminder_id: int):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(get_memory_store().mark_reminder_done, reminder_id)
    return {"status": "cancelled", "id": reminder_id}


@router.post("/api/reminders")
async def create_reminder(body: dict):
    from fastapi import HTTPException
    message = (body.get("message") or "").strip()
    fire_at = (body.get("fire_at") or "").strip()
    if not message or not fire_at:
        raise HTTPException(status_code=422, detail="message and fire_at required")
    from agents.memory_store import get_memory_store
    rid = await asyncio.to_thread(get_memory_store().add_reminder, message, fire_at)
    return {"id": rid, "message": message, "fire_at": fire_at}


@router.post("/api/chat")
async def chat(body: dict):
    from core.supervisor import run_turn
    from agents.chat_history import get_recent
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text required")
    rows = await asyncio.to_thread(get_recent, 20)
    history = [{"role": m["role"], "content": m["content"]} for m in rows]
    history.append({"role": "user", "content": text})
    response, _ = await run_turn(history)
    await _broadcast({"type": "transcript", "role": "assistant", "text": response})
    return {"response": response}


@router.post("/api/shutdown")
async def shutdown():
    import os, signal
    async def _do() -> None:
        await asyncio.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)
    asyncio.create_task(_do())
    return {"status": "shutting down"}


@router.get("/api/system/info")
async def system_info():
    import platform
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        vm = psutil.virtual_memory()
        ram_total_gb = round(vm.total / 1024**3, 1)
        ram_used_gb = round(vm.used / 1024**3, 1)
        disk = psutil.disk_usage("/")
        disk_total_gb = round(disk.total / 1024**3, 1)
        disk_used_gb = round(disk.used / 1024**3, 1)
    except ImportError:
        cpu_percent = cpu_count = ram_total_gb = ram_used_gb = disk_total_gb = disk_used_gb = None
    from core.system_fit import get_gpu_vram_gb, get_gpu_name
    return {
        "os": platform.system(),
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "ram_total_gb": ram_total_gb,
        "ram_used_gb": ram_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "vram_gb": get_gpu_vram_gb(),
        "gpu_name": get_gpu_name(),
    }


@router.get("/api/system/capabilities")
async def system_capabilities():
    from core.system_fit import capabilities
    return capabilities()


@router.get("/api/vram/status")
async def vram_status():
    return get_vram_broker().status()


@router.post("/api/vram/release")
async def vram_release(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name required")
    get_vram_broker().release(name)
    update_config(tts_engine="kokoro")
    await _broadcast({"type": "vram_status", **get_vram_broker().status()})
    return get_vram_broker().status()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    for notification in _recent_notifications:
        try:
            await ws.send_text(json.dumps(notification))
        except Exception:
            pass
    _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive; we only push
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
