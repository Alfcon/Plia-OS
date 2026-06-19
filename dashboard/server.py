import asyncio
import json
import dataclasses
import logging
import shutil
import threading
import numpy as np
from datetime import datetime
from scipy.io import wavfile
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from pathlib import Path
from core import events, registry, pipeline_registry
from core.config import get_config, update_config, restore_system_prompt, reset_system_prompt_to_default
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
_engine_switch_lock = asyncio.Lock()

UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

router = APIRouter()
_ws_clients: list[WebSocket] = []
_recent_notifications: list[dict] = []  # replay buffer for clients that connect after startup
_NOTIFICATION_REPLAY_TYPES: set[str] = {"status", "vram_status", "agent_routing"}
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
    if not events.is_subscribed(_broadcast):
        events.subscribe(_broadcast)


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text())


@router.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    body = await request.body()
    if not body:
        return {"text": ""}
    audio = np.frombuffer(body, dtype=np.float32)
    from voice.stt import get_stt_service
    text = await asyncio.to_thread(get_stt_service().transcribe, audio)
    return {"text": text}


@router.get("/api/hass/entities")
async def hass_entities():
    config = get_config()
    if not config.hass_url or not config.hass_token:
        return []
    from agents.home_assistant import list_entities
    try:
        return await list_entities(config.hass_url, config.hass_token, domains=["light", "switch"])
    except Exception:
        return []


@router.post("/api/hass/toggle/{entity_id}")
async def hass_toggle(entity_id: str):
    config = get_config()
    if not config.hass_url or not config.hass_token:
        raise HTTPException(status_code=503, detail="Home Assistant not configured")
    if "." not in entity_id:
        raise HTTPException(status_code=422, detail="Invalid entity_id: must contain a domain prefix (e.g. light.living_room)")
    domain = entity_id.split(".")[0]
    from agents.home_assistant import call_service
    result = await call_service(config.hass_url, config.hass_token, domain, "toggle", entity_id)
    return {"result": result}


@router.get("/api/tools")
async def get_tools():
    return registry.list_tools()


@router.get("/api/modules")
async def list_modules():
    from core.config import get_config
    disabled = set(get_config().disabled_modules)
    modules = registry.list_modules()
    return [
        {"name": name, "tools": tools, "enabled": name not in disabled}
        for name, tools in sorted(modules.items())
    ]


@router.post("/api/modules/{name}/enable")
async def enable_module(name: str):
    cfg = get_config()
    disabled = [m for m in cfg.disabled_modules if m != name]
    update_config(disabled_modules=disabled)
    return {"name": name, "enabled": True}


@router.post("/api/modules/{name}/disable")
async def disable_module(name: str):
    cfg = get_config()
    disabled = cfg.disabled_modules
    if name not in disabled:
        disabled = disabled + [name]
    update_config(disabled_modules=disabled)
    return {"name": name, "enabled": False}


@router.get("/api/config")
async def get_config_route():
    return dataclasses.asdict(get_config())


@router.post("/api/config")
async def post_config(updates: dict):
    updates.pop("system_prompt_backup", None)  # internal field — not settable via public API
    old_engine = get_config().tts_engine
    try:
        config = update_config(**updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if config.tts_engine != old_engine:
        svc = get_tts_service()
        if svc is not None:
            new_engine = config.tts_engine
            async def _switch_and_broadcast():
                async with _engine_switch_lock:
                    try:
                        await asyncio.to_thread(svc.switch_engine, new_engine)
                    except Exception:
                        logger.exception("TTS engine switch to %r failed", new_engine)
                        return
                await _broadcast({"type": "vram_status", **get_vram_broker().status()})
            asyncio.create_task(_switch_and_broadcast())
    return dataclasses.asdict(config)


@router.post("/api/system-prompt/undo")
async def undo_system_prompt():
    restored = await asyncio.to_thread(restore_system_prompt)
    if not restored:
        raise HTTPException(status_code=422, detail="No previous prompt to restore")
    return {"system_prompt": restored}


@router.post("/api/system-prompt/reset")
async def reset_system_prompt():
    default = await asyncio.to_thread(reset_system_prompt_to_default)
    return {"system_prompt": default}


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


@router.get("/api/memory")
async def list_memory():
    from agents.memory_store import get_memory_store
    all_facts = await asyncio.to_thread(lambda: get_memory_store().list_all())
    return [f for f in all_facts if not f["key"].startswith("note_")]


@router.get("/api/memory/search")
async def search_memory(q: str = ""):
    from agents.memory_store import get_memory_store
    if not q.strip():
        all_facts = await asyncio.to_thread(lambda: get_memory_store().list_all())
        return [f for f in all_facts if not f["key"].startswith("note_")]
    results = await asyncio.to_thread(lambda: get_memory_store().recall(q))
    return [{"key": "", "value": r} for r in results]


@router.post("/api/memory")
async def create_memory(request: Request):
    from agents.memory_store import get_memory_store
    body = await request.json()
    key = (body.get("key") or "").strip()
    value = (body.get("value") or "").strip()
    if not key or not value:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="key and value required")
    await asyncio.to_thread(lambda: get_memory_store().remember(key, value))
    return {"key": key, "value": value}


@router.put("/api/memory/{key}")
async def update_memory(key: str, request: Request):
    from agents.memory_store import get_memory_store
    body = await request.json()
    value = (body.get("value") or "").strip()
    if not value:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="value required")
    await asyncio.to_thread(lambda: get_memory_store().remember(key, value))
    return {"key": key, "value": value}


@router.delete("/api/memory/{key}")
async def forget_memory(key: str):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(lambda: get_memory_store().forget(key))
    return {"status": "deleted", "key": key}


@router.get("/api/notes")
async def list_notes():
    from agents.memory_store import get_memory_store
    all_facts = await asyncio.to_thread(lambda: get_memory_store().list_all())
    return [f for f in all_facts if f["key"].startswith("note_")]


@router.post("/api/notes")
async def create_note(request: Request):
    from datetime import datetime, timezone
    from agents.memory_store import get_memory_store
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="text required")
    key = f"note_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    await asyncio.to_thread(lambda: get_memory_store().remember(key, text))
    return {"key": key, "value": text}


@router.put("/api/notes/{key}")
async def update_note(key: str, request: Request):
    from agents.memory_store import get_memory_store
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="text required")
    await asyncio.to_thread(lambda: get_memory_store().remember(key, text))
    return {"key": key, "value": text}


@router.delete("/api/notes/{key}")
async def delete_note(key: str):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(lambda: get_memory_store().forget(key))
    return {"status": "deleted", "key": key}


@router.get("/api/reminders")
async def list_reminders():
    from agents.memory_store import get_memory_store
    return await asyncio.to_thread(get_memory_store().list_pending)


@router.delete("/api/reminders/{reminder_id}")
async def cancel_reminder(reminder_id: int):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(get_memory_store().mark_reminder_done, reminder_id)
    return {"status": "cancelled", "id": reminder_id}


@router.get("/api/timers")
async def list_timers():
    from agents.memory_store import get_memory_store
    return await asyncio.to_thread(lambda: get_memory_store().list_pending(timers_only=True))


@router.delete("/api/timers/{timer_id}")
async def cancel_timer(timer_id: int):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(get_memory_store().mark_reminder_done, timer_id)
    return {"status": "cancelled", "id": timer_id}


@router.get("/api/calendar/google/status")
async def google_calendar_status():
    from agents.google_calendar import is_connected
    connected = await asyncio.to_thread(is_connected)
    return {"connected": connected}


@router.post("/api/calendar/google/auth")
async def google_calendar_auth(request: Request):
    from agents.google_calendar import build_auth_url
    config = get_config()
    if not config.gcal_credentials_file:
        raise HTTPException(status_code=422, detail="gcal_credentials_file not configured")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/calendar/google/callback"
    auth_url = await asyncio.to_thread(build_auth_url, config.gcal_credentials_file, redirect_uri)
    return {"auth_url": auth_url}


@router.get("/api/calendar/google/callback")
async def google_calendar_callback(request: Request, code: str = ""):
    from agents.google_calendar import exchange_code
    config = get_config()
    redirect_uri = str(request.base_url).rstrip("/") + "/api/calendar/google/callback"
    try:
        await asyncio.to_thread(exchange_code, config.gcal_credentials_file, redirect_uri, code)
    except (AttributeError, TypeError, ImportError, NameError):
        raise  # programming errors → FastAPI 500, not a user-facing auth failure
    except Exception:
        logger.exception("Google Calendar OAuth callback failed")
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
            "<h2>Authorization failed.</h2><p>Close this tab and try again.</p></body></html>",
            status_code=400,
        )
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
        "<h2>Google Calendar connected.</h2><p>You can close this tab.</p></body></html>"
    )


@router.get("/api/calendar")
async def list_calendar_events():
    from agents.google_calendar import is_connected, list_events as gcal_list
    if await asyncio.to_thread(is_connected):
        config = get_config()
        return await asyncio.to_thread(gcal_list, config.gcal_calendar_id)
    from agents.calendar_store import get_calendar_store
    return await asyncio.to_thread(get_calendar_store().list_events_json)


@router.post("/api/calendar")
async def create_calendar_event(body: dict):
    title = (body.get("title") or "").strip()
    date = (body.get("date") or "").strip()
    time_str = (body.get("time") or "09:00").strip()
    try:
        duration = int(body.get("duration_min") or 60)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="duration_min must be an integer")
    if not title or not date:
        raise HTTPException(status_code=422, detail="title and date required")
    from agents.google_calendar import is_connected, create_event as gcal_create
    if await asyncio.to_thread(is_connected):
        from datetime import timedelta, timezone
        config = get_config()
        dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        dtend = dt + timedelta(minutes=duration)
        try:
            uid = await asyncio.to_thread(gcal_create, title, dt.isoformat(), dtend.isoformat(), config.gcal_calendar_id)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return {"uid": uid, "title": title, "date": date, "time": time_str, "duration_min": duration}
    from agents.calendar_store import get_calendar_store
    try:
        uid = await asyncio.to_thread(lambda: get_calendar_store().add_event(title, date, time_str, duration))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"uid": uid, "title": title, "date": date, "time": time_str, "duration_min": duration}


@router.delete("/api/calendar/{uid}")
async def delete_calendar_event(uid: str):
    from agents.google_calendar import is_connected, delete_event as gcal_delete
    if await asyncio.to_thread(is_connected):
        config = get_config()
        try:
            await asyncio.to_thread(gcal_delete, uid, config.gcal_calendar_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Event not found in Google Calendar")
        return {"status": "deleted", "uid": uid}
    from agents.calendar_store import get_calendar_store
    deleted = await asyncio.to_thread(lambda: get_calendar_store().delete_event(uid))
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"status": "deleted", "uid": uid}


@router.post("/api/reminders")
async def create_reminder(body: dict):
    message = (body.get("message") or "").strip()
    fire_at = (body.get("fire_at") or "").strip()
    if not message or not fire_at:
        raise HTTPException(status_code=422, detail="message and fire_at required")
    try:
        parsed_dt = datetime.fromisoformat(fire_at)
        if parsed_dt.tzinfo is None:
            raise ValueError("naive datetime")
    except ValueError:
        raise HTTPException(status_code=422, detail="fire_at must be ISO-8601 with timezone offset")
    from agents.memory_store import get_memory_store
    rid = await asyncio.to_thread(lambda: get_memory_store().add_reminder(message, fire_at))
    return {"id": rid, "message": message, "fire_at": fire_at}


@router.post("/api/chat")
async def chat(body: dict):
    from core.supervisor import run_turn
    from agents.chat_history import get_recent, _HISTORY_PRELOAD
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text required")
    rows = await asyncio.to_thread(get_recent, _HISTORY_PRELOAD)
    history = [{"role": m["role"], "content": m["content"]} for m in rows]
    history.append({"role": "user", "content": text})
    response, _ = await run_turn(history)
    if response:
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


@router.get("/api/pipeline/status")
async def pipeline_status():
    return {"state": pipeline_registry.get_state()}


@router.post("/api/pipeline/stop")
async def pipeline_stop():
    task = pipeline_registry.get_task()
    if task and not task.done():
        task.cancel()
    pipeline_registry.set_state("stopped")
    pipeline_registry.set_task(None)
    return {"state": "stopped"}


@router.post("/api/pipeline/start")
async def pipeline_start():
    task = pipeline_registry.get_task()
    if task and not task.done():
        return {"state": pipeline_registry.get_state()}
    from core.pipeline_runner import start_pipeline
    new_task = asyncio.create_task(start_pipeline())
    pipeline_registry.set_task(new_task)
    pipeline_registry.set_state("starting")
    return {"state": "starting"}


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


# --- Permissions ---

_OS_PERMISSION_GROUPS = [
    {
        "id": "network_mac",
        "name": "Network Interface Control",
        "description": "Allows tools to change MAC addresses using ip link set (requires sudo).",
        "tools": ["randomize_mac", "set_mac", "restore_mac"],
        "sudoers_file": "/etc/sudoers.d/plia-mac",
        "grant_cmd": (
            "echo 'alfcon ALL=(ALL) NOPASSWD: /usr/sbin/ip link set dev * down,"
            " /usr/sbin/ip link set dev * address *,"
            " /usr/sbin/ip link set dev * up'"
            " | sudo tee /etc/sudoers.d/plia-mac && sudo chmod 440 /etc/sudoers.d/plia-mac"
        ),
        "revoke_cmd": "sudo rm /etc/sudoers.d/plia-mac",
    },
    {
        "id": "wireless_tools",
        "name": "Wireless Tools",
        "description": "Allows airmon-ng, airodump-ng, aireplay-ng, reaver and wash to run with sudo for monitor mode and packet capture.",
        "tools": ["start_monitor_mode", "stop_monitor_mode", "capture_handshake", "attack_wps", "scan_wps_networks"],
        "sudoers_file": "/etc/sudoers.d/plia-wireless",
        "grant_cmd": (
            "echo 'alfcon ALL=(ALL) NOPASSWD:"
            " /usr/sbin/airmon-ng, /usr/sbin/airodump-ng, /usr/sbin/aireplay-ng,"
            " /usr/sbin/reaver, /usr/bin/wash, /usr/sbin/wash,"
            " /usr/sbin/service, /usr/bin/service,"
            " /usr/bin/systemctl restart NetworkManager'"
            " | sudo tee /etc/sudoers.d/plia-wireless && sudo chmod 440 /etc/sudoers.d/plia-wireless"
        ),
        "revoke_cmd": "sudo rm /etc/sudoers.d/plia-wireless",
    },
]


@router.get("/api/permissions")
async def get_permissions():
    import pathlib
    cfg = get_config()
    os_groups = []
    for g in _OS_PERMISSION_GROUPS:
        granted = pathlib.Path(g["sudoers_file"]).exists()
        os_groups.append({**g, "granted": granted})
    from core.registry import get_tool_schemas
    tool_names = [s["function"]["name"] for s in get_tool_schemas()]
    tools = {name: cfg.tool_permissions.get(name, "user") for name in sorted(tool_names)}
    return {"os_groups": os_groups, "tool_permissions": tools}


@router.post("/api/permissions/tools")
async def set_tool_permissions(body: dict):
    # body: {"tool_name": "admin"|"user", ...}
    cfg = get_config()
    perms = dict(cfg.tool_permissions)
    for tool, level in body.items():
        if level not in ("admin", "user"):
            raise HTTPException(status_code=422, detail=f"Invalid level {level!r} for {tool!r}")
        perms[tool] = level
    update_config(tool_permissions=perms)
    return {"tool_permissions": perms}


@router.get("/api/tools/schemas")
async def tool_schemas():
    from core.registry import get_tool_schemas
    return get_tool_schemas()


@router.post("/api/tools/run")
async def run_tool(body: dict):
    """Call any registered tool directly — no LLM involved.
    Body: {"tool": "tool_name", "params": {...}}
    """
    from core.registry import call_tool_async
    tool_name = body.get("tool")
    params = body.get("params", {})
    if not tool_name:
        raise HTTPException(status_code=400, detail="'tool' is required")
    try:
        result = await call_tool_async(tool_name, params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    result_str = str(result)
    await _broadcast({"type": "transcript", "role": "tool", "text": f"[{tool_name}]\n{result_str}"})
    return {"tool": tool_name, "result": result_str}


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
    svc = get_tts_service()
    if svc is not None:
        async with _engine_switch_lock:
            try:
                await asyncio.to_thread(svc.switch_engine, "kokoro")
            except Exception:
                logger.exception("TTS engine switch to 'kokoro' after VRAM release failed")
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
