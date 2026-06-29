import asyncio
import json
import dataclasses
import logging
import re
import shutil
import threading
import numpy as np
from datetime import datetime
from scipy.io import wavfile
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
import pathlib
from pathlib import Path
from core import events, registry, pipeline_registry
from core.registry import call_tool_async
from core.loader import load_modules
from agents.chat_history import search as chat_search
from agents.memory_store import get_memory_store
from core.config import get_config, update_config, restore_system_prompt, reset_system_prompt_to_default
from voice.tts import get_tts_service
from voice.vram_broker import get_vram_broker
from core.mcp_client import get_mcp_status, disable_mcp_server, restart_mcp_servers

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

# state → code_verifier for Gmail PKCE OAuth flows
_email_oauth_verifiers: dict[str, str] = {}
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


import collections as _collections_top
import time as _time_top

_SERVER_START: float = _time_top.time()

_WORKFLOW_HISTORY: _collections_top.deque = _collections_top.deque(maxlen=100)

_CONFIG_HISTORY: _collections_top.deque = _collections_top.deque(maxlen=200)

_TOOL_STATS: dict[str, dict] = {}

_TURN_TRACES: _collections_top.deque = _collections_top.deque(maxlen=100)


def _on_agent_routing(payload: dict) -> None:
    if payload.get("type") != "agent_routing":
        return
    agent = payload.get("agent", "unknown")
    latency = payload.get("latency_ms", 0)
    # tool analytics
    entry = _TOOL_STATS.setdefault(agent, {"calls": 0, "total_latency_ms": 0, "errors": 0})
    entry["calls"] += 1
    entry["total_latency_ms"] += latency
    # turn trace
    _TURN_TRACES.appendleft({
        "ts": _time_top.time(),
        "agent": agent,
        "routing_method": payload.get("routing_method", "unknown"),
        "latency_ms": latency,
        "query": payload.get("query", ""),
    })


def setup_event_forwarding() -> None:
    """Call once at startup to wire the event bus to WebSocket clients."""
    if not events.is_subscribed(_broadcast):
        events.subscribe(_broadcast)
    from core.event_log import log_event
    if not events.is_subscribed(log_event):
        events.subscribe(log_event)
    if not events.is_subscribed(_on_agent_routing):
        events.subscribe(_on_agent_routing)


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    index = STATIC_DIR / "index.html"
    return HTMLResponse(index.read_text())


@router.post("/api/tts/synthesize")
async def tts_synthesize(body: dict):
    import time
    import io
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="'text' required")
    from voice.tts import get_tts_service as _get_tts
    svc = _get_tts()
    if svc is None:
        raise HTTPException(status_code=503, detail="TTS service not loaded")
    t0 = time.monotonic()
    try:
        audio = await asyncio.to_thread(svc.synthesise, text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    latency_ms = int((time.monotonic() - t0) * 1000)
    sample_rate = 24000
    audio_duration_s = round(len(audio) / sample_rate, 3)
    buf = io.BytesIO()
    wavfile.write(buf, sample_rate, audio)
    wav_bytes = buf.getvalue()
    from fastapi.responses import Response
    response = Response(content=wav_bytes, media_type="audio/wav")
    response.headers["X-Latency-Ms"] = str(latency_ms)
    response.headers["X-Audio-Duration-S"] = str(audio_duration_s)
    return response


@router.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    import time
    body = await request.body()
    if not body:
        return {"text": "", "latency_ms": 0, "audio_duration_s": 0.0, "sample_rate": 16000}
    audio = np.frombuffer(body, dtype=np.float32)
    sample_rate = 16000
    audio_duration_s = round(len(audio) / sample_rate, 3)
    from voice.stt import get_stt_service
    t0 = time.monotonic()
    text = await asyncio.to_thread(get_stt_service().transcribe, audio)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return {
        "text": text,
        "latency_ms": latency_ms,
        "audio_duration_s": audio_duration_s,
        "sample_rate": sample_rate,
    }


@router.post("/api/voice/detect-language")
async def voice_detect_language(request: Request):
    import time
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="Audio bytes required")
    audio = np.frombuffer(body, dtype=np.float32)
    from voice.stt import get_stt_service
    svc = get_stt_service()
    if svc._model is None:
        raise HTTPException(status_code=503, detail="STT model not loaded")
    t0 = time.monotonic()

    def _detect():
        result = svc._model.detect_language(audio)
        if isinstance(result, tuple) and len(result) == 2:
            lang, probs = result
            if isinstance(probs, float):
                prob = round(probs, 4)
            elif isinstance(probs, dict):
                prob = round(probs.get(lang, 0.0), 4)
            else:
                prob = round(getattr(probs, "language_probability", 0.0), 4)
        else:
            lang, prob = str(result), None
        return lang, prob

    lang, prob = await asyncio.to_thread(_detect)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return {"language": lang, "probability": prob, "latency_ms": latency_ms}


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
    from core.registry import _tools, _disabled_modules
    disabled = _disabled_modules()
    tools = []
    for name, entry in sorted(_tools.items()):
        schema = entry["schema"]["function"]
        tools.append({
            "name": name,
            "description": schema.get("description", ""),
            "module": entry.get("module", ""),
            "disabled": entry.get("module", "") in disabled,
            "parameters": schema.get("parameters", {"type": "object", "properties": {}, "required": []}),
        })
    return {"tools": tools}


_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


@router.get("/api/modules")
async def list_modules():
    from core.config import get_config
    disabled = set(get_config().disabled_modules)
    registered = registry.list_modules()
    # all .py files on disk
    disk_names = {p.stem for p in _MODULES_DIR.glob("*.py") if not p.name.startswith("_")}
    all_names = disk_names | set(registered.keys())
    result = []
    for name in sorted(all_names):
        tools = registered.get(name, [])
        result.append({
            "name": name,
            "tools": tools,
            "tool_count": len(tools),
            "enabled": name not in disabled,
            "on_disk": name in disk_names,
            "loaded": name in registered,
        })
    return result


@router.post("/api/modules/reload/{name}")
async def reload_single_module(name: str):
    import importlib
    import sys
    from core.registry import _tools
    mod_key = f"modules.{name}"
    # unregister tools for this module only
    to_remove = [k for k, v in list(_tools.items()) if v.get("module") == name]
    for k in to_remove:
        del _tools[k]
    # force reimport
    if mod_key in sys.modules:
        del sys.modules[mod_key]
    mod_path = _MODULES_DIR / f"{name}.py"
    if not mod_path.exists():
        raise HTTPException(status_code=404, detail=f"Module {name!r} not found on disk")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(mod_key, mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_key] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reload error: {exc}")
    registered = registry.list_modules()
    tools = registered.get(name, [])
    return {"ok": True, "name": name, "tools": tools}


@router.post("/api/modules/reload")
async def reload_modules():
    from core.registry import _tools
    # remove all non-MCP user module tools then re-import
    to_remove = [k for k, v in list(_tools.items()) if not v.get("module", "").startswith("mcp:")]
    for k in to_remove:
        del _tools[k]
    await asyncio.to_thread(load_modules)
    registered = registry.list_modules()
    return {"ok": True, "modules": len(registered), "tools": sum(len(t) for t in registered.values())}


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


@router.get("/api/ollama/models")
async def ollama_models():
    import httpx
    cfg = get_config()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{cfg.ollama_url}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unreachable: {exc}")
    models = [m["name"] for m in data.get("models", [])]
    return {"models": models, "current": cfg.ollama_model}


@router.post("/api/ollama/model")
async def set_ollama_model(body: dict):
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")
    await asyncio.to_thread(update_config, ollama_model=model)
    await events.emit("config_changed", {"key": "ollama_model", "value": model})
    return {"ok": True, "model": model}


@router.post("/api/ollama/pull")
async def ollama_pull(body: dict):
    import httpx
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model required")
    cfg = get_config()
    if not cfg.ollama_url:
        raise HTTPException(status_code=503, detail="Ollama URL not configured")

    async def _stream():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{cfg.ollama_url}/api/pull",
                    json={"name": model, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line:
                            yield f"data: {line}\n\n"
        except Exception as exc:
            yield f"data: {{\"error\": {json.dumps(str(exc))}}}\n\n"
        yield "data: {\"status\": \"done\"}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/api/config")
async def post_config(updates: dict):
    updates.pop("system_prompt_backup", None)  # internal field — not settable via public API
    _old_cfg = dataclasses.asdict(get_config())
    old_engine = get_config().tts_engine
    old_briefing_enabled = get_config().briefing_cron_enabled
    old_briefing_time = get_config().briefing_cron_time
    try:
        config = update_config(**updates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _changes = {k: {"old": _old_cfg.get(k), "new": v} for k, v in updates.items() if _old_cfg.get(k) != v}
    if _changes:
        _CONFIG_HISTORY.appendleft({"ts": _time_top.time(), "changes": _changes})
    # Sync briefing cron job when enabled/time changes
    if config.briefing_cron_enabled != old_briefing_enabled or config.briefing_cron_time != old_briefing_time:
        from agents.cron_store import get_cron_store
        store = get_cron_store()
        if config.briefing_cron_enabled:
            try:
                h, m = config.briefing_cron_time.split(":")
                expr = f"{int(m)} {int(h)} * * *"
            except Exception:
                expr = "0 7 * * *"
            await asyncio.to_thread(store.add, "morning_briefing", expr, "tool:morning_briefing")
        else:
            await asyncio.to_thread(store.remove, "morning_briefing")
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


@router.get("/api/system-prompt/diff")
async def system_prompt_diff():
    import difflib, dataclasses as _dc
    cfg = get_config()
    default_prompt: str = _dc.fields(cfg.__class__)[
        next(i for i, f in enumerate(_dc.fields(cfg.__class__)) if f.name == "system_prompt")
    ].default
    current = cfg.system_prompt
    backup = cfg.system_prompt_backup or ""

    def _diff(a: str, b: str, label_a: str, label_b: str) -> list[dict]:
        lines = list(difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            fromfile=label_a,
            tofile=label_b,
        ))
        return [{"line": ln.rstrip("\n"), "kind": "add" if ln.startswith("+") else "remove" if ln.startswith("-") else "meta" if ln.startswith("@") else "context"} for ln in lines]

    return {
        "vs_default": _diff(default_prompt, current, "default", "current"),
        "vs_backup": _diff(backup, current, "backup", "current") if backup else [],
        "has_backup": bool(backup),
    }


@router.post("/api/tts/preview")
async def tts_preview(body: dict):
    import time, io
    text = (body.get("text") or "Hello, I am Plia.").strip()[:200]
    from voice.tts import get_tts_service as _get_tts
    svc = _get_tts()
    if svc is None:
        raise HTTPException(status_code=503, detail="TTS service not loaded")
    t0 = time.monotonic()
    try:
        audio = await asyncio.to_thread(svc.synthesise, text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    latency_ms = int((time.monotonic() - t0) * 1000)
    buf = io.BytesIO()
    wavfile.write(buf, 24000, audio)
    from fastapi.responses import Response
    r = Response(content=buf.getvalue(), media_type="audio/wav")
    r.headers["X-Latency-Ms"] = str(latency_ms)
    return r


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


@router.get("/api/history/export")
async def export_history(n: int = 10000, fmt: str = "json"):
    from agents.chat_history import get_recent
    messages = await asyncio.to_thread(get_recent, n)
    if fmt == "markdown":
        lines = [f"# Chat Export\n\n*{len(messages)} messages*\n"]
        for m in messages:
            ts = m.get("ts", "")
            role = m.get("role", "")
            content = m.get("content", "")
            prefix = "**You**" if role == "user" else "**Plia**"
            lines.append(f"### {prefix}  \n*{ts}*\n\n{content}\n")
        body = "\n---\n\n".join(lines)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=body,
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="chat_export.md"'},
        )
    # default: JSON
    import json as _json
    from fastapi.responses import Response
    return Response(
        content=_json.dumps({"messages": messages}, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="chat_export.json"'},
    )


@router.get("/api/history/search")
async def history_search(q: str = "", n: int = 50):
    if not q.strip():
        return {"query": q, "results": [], "total": 0}
    from agents.chat_history import search as _search
    rows = await asyncio.to_thread(_search, q, n)
    ql = q.lower()
    def _snippet(content: str, window: int = 80) -> str:
        idx = content.lower().find(ql)
        if idx == -1:
            return content[:window]
        start = max(0, idx - window // 2)
        end = min(len(content), idx + len(q) + window // 2)
        snippet = content[start:end]
        if start > 0:
            snippet = "…" + snippet
        if end < len(content):
            snippet = snippet + "…"
        return snippet
    results = [{"role": r["role"], "ts": r["ts"], "snippet": _snippet(r["content"]), "content": r["content"]} for r in rows]
    return {"query": q, "results": results, "total": len(results)}


@router.get("/api/history/export/pdf")
async def export_history_pdf(n: int = 10000):
    import tempfile, subprocess, shutil
    from agents.chat_history import get_recent
    if not shutil.which("wkhtmltopdf"):
        raise HTTPException(status_code=503, detail="wkhtmltopdf not found")
    messages = await asyncio.to_thread(get_recent, n)
    rows_html = ""
    for m in messages:
        role = m.get("role", "")
        content = (m.get("content") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        ts = m.get("ts", "")
        color = "#4fc3f7" if role == "user" else "#a5d6a7"
        label = "You" if role == "user" else "Plia"
        rows_html += f'<div class="msg"><span class="who" style="color:{color}">{label}</span><span class="ts">{ts}</span><div class="body">{content}</div></div>'
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:sans-serif;font-size:11pt;margin:20px}}
.msg{{margin-bottom:12px;border-bottom:1px solid #eee;padding-bottom:8px}}
.who{{font-weight:bold;font-size:10pt}} .ts{{color:#999;font-size:9pt;margin-left:8px}}
.body{{margin-top:4px;white-space:pre-wrap}}</style></head>
<body><h2>Plia-OS Chat Export</h2><p>{len(messages)} messages</p>{rows_html}</body></html>"""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as hf:
        hf.write(html)
        html_path = hf.name
    pdf_path = html_path.replace(".html", ".pdf")
    try:
        proc = await asyncio.create_subprocess_exec(
            "wkhtmltopdf", "--quiet", html_path, pdf_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0 or not pathlib.Path(pdf_path).exists():
            raise HTTPException(status_code=500, detail="PDF generation failed")
        pdf_bytes = pathlib.Path(pdf_path).read_bytes()
    finally:
        pathlib.Path(html_path).unlink(missing_ok=True)
        pathlib.Path(pdf_path).unlink(missing_ok=True)
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="chat_export.pdf"'},
    )


@router.get("/api/chat/tokens")
async def chat_token_count(n: int = 100):
    from agents.chat_history import get_recent
    messages = await asyncio.to_thread(get_recent, n)
    total_chars = sum(len(m.get("content") or "") for m in messages)
    estimated_tokens = round(total_chars / 4)
    return {
        "message_count": len(messages),
        "total_chars": total_chars,
        "estimated_tokens": estimated_tokens,
        "model_context_note": "GPT-4 style: ~4 chars/token",
    }


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
    all_facts = await asyncio.to_thread(lambda: get_memory_store().list_all())
    all_facts = [f for f in all_facts if not f["key"].startswith("note_")]
    if not q.strip():
        return all_facts
    q_lower = q.lower()
    return [f for f in all_facts if q_lower in f["key"].lower() or q_lower in f["value"].lower()]


@router.get("/api/memory/export")
async def memory_export():
    import sqlite3
    store = get_memory_store()

    def _dump():
        facts = store.list_all()
        with sqlite3.connect(store._db_path) as conn:
            conn.row_factory = sqlite3.Row
            hist = [dict(r) for r in conn.execute("SELECT role, content, ts FROM history ORDER BY id ASC").fetchall()]
            rems = [dict(r) for r in conn.execute(
                "SELECT id, message, fire_at, done, is_timer FROM reminders ORDER BY id ASC"
            ).fetchall()]
        return {"facts": facts, "history": hist, "reminders": rems}

    data = await asyncio.to_thread(_dump)
    from fastapi.responses import Response
    content = json.dumps(data, indent=2, ensure_ascii=False).encode()
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=plia_memory_export.json"})


@router.post("/api/memory/import")
async def memory_import(request: Request):
    body = await request.json()
    store = get_memory_store()

    def _restore():
        imported_facts = 0
        imported_rems = 0
        for fact in body.get("facts", []):
            k = (fact.get("key") or "").strip()
            v = (fact.get("value") or "").strip()
            if k and v:
                store.remember(k, v)
                imported_facts += 1
        for rem in body.get("reminders", []):
            if not rem.get("done"):
                store.add_reminder(rem["message"], rem["fire_at"], bool(rem.get("is_timer", False)))
                imported_rems += 1
        return imported_facts, imported_rems

    imported_facts, imported_rems = await asyncio.to_thread(_restore)
    return {"ok": True, "facts": imported_facts, "reminders": imported_rems}


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


@router.delete("/api/reminders/done")
async def delete_done_reminders():
    from agents.memory_store import get_memory_store
    deleted = await asyncio.to_thread(get_memory_store().delete_done_reminders)
    return {"ok": True, "deleted": deleted}


@router.post("/api/reminders/bulk-snooze")
async def bulk_snooze_reminders(body: dict):
    ids = body.get("ids") or []
    minutes = int(body.get("minutes", 10))
    if not ids:
        raise HTTPException(status_code=422, detail="ids list required")
    if minutes < 1 or minutes > 1440:
        raise HTTPException(status_code=400, detail="minutes must be 1-1440")
    from agents.memory_store import get_memory_store
    count = await asyncio.to_thread(get_memory_store().bulk_snooze_reminders, ids, minutes)
    return {"ok": True, "snoozed": count, "minutes": minutes}


@router.delete("/api/reminders/{reminder_id}")
async def cancel_reminder(reminder_id: int):
    from agents.memory_store import get_memory_store
    await asyncio.to_thread(get_memory_store().mark_reminder_done, reminder_id)
    return {"status": "cancelled", "id": reminder_id}


@router.patch("/api/reminders/{reminder_id}")
async def edit_reminder(reminder_id: int, body: dict):
    message = (body.get("message") or "").strip() or None
    fire_at = (body.get("fire_at") or "").strip() or None
    if not message and not fire_at:
        raise HTTPException(status_code=422, detail="message or fire_at required")
    if fire_at:
        try:
            parsed = datetime.fromisoformat(fire_at)
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=422, detail="fire_at must be ISO-8601 with timezone")
    from agents.memory_store import get_memory_store
    store = get_memory_store()

    def _update():
        with store._conn() as conn:
            row = conn.execute(
                "SELECT message, fire_at FROM reminders WHERE id=? AND done=0", (reminder_id,)
            ).fetchone()
            if row is None:
                return None
            new_msg = message if message is not None else row[0]
            new_fire = fire_at if fire_at is not None else row[1]
            conn.execute(
                "UPDATE reminders SET message=?, fire_at=? WHERE id=?",
                (new_msg, new_fire, reminder_id),
            )
            return {"id": reminder_id, "message": new_msg, "fire_at": new_fire}

    result = await asyncio.to_thread(_update)
    if result is None:
        raise HTTPException(status_code=404, detail="Reminder not found or already done")
    return result


@router.post("/api/reminders/{reminder_id}/snooze")
async def snooze_reminder(reminder_id: int, body: dict):
    minutes = int(body.get("minutes", 10))
    if minutes < 1 or minutes > 1440:
        raise HTTPException(status_code=400, detail="minutes must be 1-1440")
    from agents.memory_store import get_memory_store
    found = await asyncio.to_thread(get_memory_store().snooze_reminder, reminder_id, minutes)
    if not found:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"ok": True, "snoozed_minutes": minutes}


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


# --- Email accounts ---

@router.get("/api/email/accounts")
async def email_list_accounts():
    from agents.email_store import list_accounts
    accounts = await asyncio.to_thread(list_accounts)
    # Strip passwords from response
    return [
        {k: v for k, v in acc.items() if k != "password"}
        for acc in accounts
    ]


@router.post("/api/email/accounts")
async def email_add_account(request: Request):
    data = await request.json()
    if not data.get("name"):
        raise HTTPException(status_code=422, detail="name required")
    from agents.email_store import add_account
    acc = await asyncio.to_thread(add_account, data)
    return {k: v for k, v in acc.items() if k != "password"}


@router.delete("/api/email/accounts/{name}")
async def email_remove_account(name: str):
    from agents.email_store import remove_account
    removed = await asyncio.to_thread(remove_account, name)
    if not removed:
        raise HTTPException(status_code=404, detail="account not found")
    return {"removed": name}


@router.post("/api/email/accounts/{name}/auth")
async def email_account_auth(name: str, request: Request):
    from agents.email_store import get_account
    from agents.email_client import build_auth_url
    acc = await asyncio.to_thread(get_account, name)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    if not acc.get("gmail_credentials_file"):
        raise HTTPException(status_code=422, detail="gmail_credentials_file not set for this account")
    redirect_uri = str(request.base_url).rstrip("/") + f"/api/email/accounts/{name}/callback"
    auth_url, state, verifier = await asyncio.to_thread(build_auth_url, acc, redirect_uri)
    if verifier:
        _email_oauth_verifiers[state] = verifier
    return {"auth_url": auth_url}


@router.get("/api/email/accounts/{name}/callback")
async def email_account_callback(name: str, request: Request, code: str = "", state: str = ""):
    from agents.email_store import get_account
    from agents.email_client import exchange_code
    acc = await asyncio.to_thread(get_account, name)
    if acc is None:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
            "<h2>Account not found.</h2></body></html>",
            status_code=404,
        )
    redirect_uri = str(request.base_url).rstrip("/") + f"/api/email/accounts/{name}/callback"
    verifier = _email_oauth_verifiers.pop(state, "")
    try:
        await asyncio.to_thread(exchange_code, acc, redirect_uri, code, verifier)
    except (AttributeError, TypeError, ImportError, NameError):
        raise
    except Exception:
        logger.exception("Gmail OAuth callback failed for %s", name)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
            "<h2>Authorization failed.</h2><p>Close this tab and try again.</p></body></html>",
            status_code=400,
        )
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
        f"<h2>{name} connected.</h2><p>You can close this tab.</p></body></html>"
    )


@router.post("/api/email/accounts/{name}/test")
async def email_account_test(name: str):
    from agents.email_store import get_account
    from agents.email_client import imap_connection
    acc = await asyncio.to_thread(get_account, name)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    def _test():
        with imap_connection(acc) as mb:
            count = mb.folder.status("INBOX").get("UNSEEN", 0)
            return count
    try:
        unread = await asyncio.wait_for(asyncio.to_thread(_test), timeout=15.0)
        return {"ok": True, "message": f"Connected. {unread} unread."}
    except asyncio.TimeoutError:
        return {"ok": False, "message": "Connection timed out."}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.get("/api/email/accounts/{name}/status")
async def email_account_status(name: str):
    from agents.email_store import get_account
    from agents.email_client import is_connected
    acc = await asyncio.to_thread(get_account, name)
    if acc is None:
        raise HTTPException(status_code=404, detail="account not found")
    if acc.get("provider") == "gmail":
        connected = await asyncio.to_thread(is_connected, acc)
    else:
        connected = bool(acc.get("username"))
    return {"connected": connected}


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
    from core.context_compactor import maybe_compact
    from agents.chat_history import get_recent, _HISTORY_PRELOAD
    from core.shortcut_store import match_shortcut
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text required")
    mapped = match_shortcut(text)
    if mapped:
        text = mapped
    rows = await asyncio.to_thread(get_recent, _HISTORY_PRELOAD)
    history = [{"role": m["role"], "content": m["content"]} for m in rows]
    history.append({"role": "user", "content": text})
    history = await maybe_compact(history)
    response, _ = await run_turn(history)
    if response:
        await _broadcast({"type": "transcript", "role": "assistant", "text": response})
    return {"response": response}


@router.post("/api/tool-guard/respond/{approval_id}")
async def tool_guard_respond(approval_id: str, body: dict):
    from core.tool_guard import respond
    approved = bool(body.get("approved", False))
    found = respond(approval_id, approved)
    if not found:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"status": "approved" if approved else "denied"}


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


@router.post("/api/pipeline/restart")
async def pipeline_restart():
    task = pipeline_registry.get_task()
    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
        except Exception:
            pass
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


import collections as _collections
_VRAM_TIMELINE: _collections.deque = _collections.deque(maxlen=120)


async def run_vram_sampler() -> None:
    import time as _time
    while True:
        try:
            s = get_vram_broker().status()
            _VRAM_TIMELINE.append({
                "ts": round(_time.time(), 1),
                "used_gb": s["vram_used_gb"],
                "total_gb": s["vram_total_gb"],
                "models": {k: v["vram_gb"] for k, v in s.get("models", {}).items() if v.get("vram_gb", 0) > 0},
            })
        except Exception:
            pass
        await asyncio.sleep(5)


@router.get("/api/vram/timeline")
async def vram_timeline(n: int = 120):
    samples = list(_VRAM_TIMELINE)[-min(n, 120):]
    return {"samples": samples, "interval_s": 5}


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


@router.get("/api/airllm/status")
async def airllm_status():
    import agents.airllm_backend as be
    cfg = get_config()
    return {
        "loaded": be._model is not None,
        "model_id": be._model_id or "",
        "compression": cfg.airllm_compression,
        "configured": bool(cfg.airllm_model),
    }


@router.post("/api/airllm/unload")
async def airllm_unload():
    import agents.airllm_backend as be
    be.unload()
    update_config(airllm_model="")
    return {"ok": True}


_WAKE_MODEL = None


def _get_wake_model():
    global _WAKE_MODEL
    if _WAKE_MODEL is None:
        from openwakeword import get_pretrained_model_paths
        from openwakeword.model import Model as _WModel
        _WAKE_MODEL = _WModel(wakeword_model_paths=get_pretrained_model_paths())
    return _WAKE_MODEL


def _run_wake_prediction(audio_int16: "np.ndarray") -> dict:
    model = _get_wake_model()
    model.reset()
    CHUNK = 1280
    max_scores: dict[str, float] = {}
    n = len(audio_int16)
    for i in range(0, max(n, CHUNK), CHUNK):
        chunk = audio_int16[i:i + CHUNK] if i < n else np.zeros(CHUNK, dtype=np.int16)
        preds = model.predict(chunk)
        for k, v in preds.items():
            if not str(k).isdigit():
                max_scores[k] = max(max_scores.get(k, 0.0), float(v))
        if i >= n:
            break
    return max_scores


@router.get("/api/wake/models")
async def wake_models():
    from openwakeword import get_pretrained_model_paths
    import os
    paths = get_pretrained_model_paths()
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    cfg = get_config()
    return {"models": names, "configured": cfg.wake_word_model, "threshold": cfg.wake_word_threshold}


@router.post("/api/wake/test")
async def wake_test(request: Request):
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="audio required")
    audio = np.frombuffer(body, dtype=np.float32)
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    try:
        scores = await asyncio.to_thread(_run_wake_prediction, audio_int16)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    cfg = get_config()
    threshold = cfg.wake_word_threshold
    detected_by = [k for k, v in scores.items() if v >= threshold]
    return {
        "scores": {k: round(v, 4) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
        "threshold": threshold,
        "detected_by": detected_by,
    }


_DL_STATE: dict = {"state": "idle", "model": "", "file": "", "bytes": 0, "total": 0, "error": ""}


def _download_sync(model: str) -> None:
    from huggingface_hub import snapshot_download
    from tqdm import tqdm as _tqdm

    class _Tracker(_tqdm):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            _DL_STATE["file"] = str(self.desc or "")

        def update(self, n=1):
            super().update(n)
            _DL_STATE["bytes"] = int(self.n or 0)
            _DL_STATE["total"] = int(self.total or 0)
            _DL_STATE["file"] = str(self.desc or "")

    snapshot_download(model, tqdm_class=_Tracker)


async def _run_download(model: str) -> None:
    try:
        await asyncio.to_thread(_download_sync, model)
        _DL_STATE["state"] = "done"
    except Exception as exc:
        _DL_STATE.update({"state": "error", "error": str(exc)})


@router.post("/api/airllm/download")
async def airllm_download_start(body: dict):
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=422, detail="model required")
    if _DL_STATE["state"] == "downloading":
        raise HTTPException(status_code=409, detail="download already in progress")
    _DL_STATE.update({"state": "downloading", "model": model, "file": "", "bytes": 0, "total": 0, "error": ""})
    asyncio.create_task(_run_download(model))
    return {"ok": True, "model": model}


@router.get("/api/airllm/download/status")
async def airllm_download_status():
    pct = round(_DL_STATE["bytes"] / _DL_STATE["total"] * 100, 1) if _DL_STATE["total"] else 0
    return {**_DL_STATE, "pct": pct}


@router.get("/api/audio/devices")
async def list_audio_devices():
    try:
        import sounddevice as _sd
    except ImportError:
        raise HTTPException(status_code=503, detail="sounddevice not available")
    devs = await asyncio.to_thread(_sd.query_devices)
    cfg = get_config()
    defaults = _sd.default.device
    def_in = defaults[0] if isinstance(defaults, (list, tuple)) else defaults
    def_out = defaults[1] if isinstance(defaults, (list, tuple)) else defaults
    return {
        "devices": [
            {
                "index": i,
                "name": d["name"],
                "input_channels": d["max_input_channels"],
                "output_channels": d["max_output_channels"],
            }
            for i, d in enumerate(devs)
        ],
        "default_input": def_in,
        "default_output": def_out,
        "configured_input": cfg.audio_input_device,
        "configured_output": cfg.audio_output_device,
    }


@router.post("/api/audio/devices")
async def set_audio_devices(body: dict):
    inp = body.get("input_device")
    out = body.get("output_device")
    update_config(
        audio_input_device=int(inp) if inp is not None else None,
        audio_output_device=int(out) if out is not None else None,
    )
    return {"ok": True}


# ── Network diagnostics ───────────────────────────────────────────────────────

@router.post("/api/netdiag/ping")
async def netdiag_ping(body: dict):
    import time, re, asyncio as _aio
    host = (body.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="host required")
    t0 = time.monotonic()
    try:
        proc = await _aio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "2", host,
            stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        latency_ms = int((time.monotonic() - t0) * 1000)
        ok = proc.returncode == 0
        detail = stdout.decode(errors="replace")
        m = re.search(r"time=(\d+\.?\d*)\s*ms", detail)
        rtt = float(m.group(1)) if m else None
        return {"ok": ok, "host": host, "rtt_ms": rtt, "latency_ms": latency_ms, "detail": detail.strip().splitlines()[-1] if detail.strip() else ""}
    except Exception as exc:
        return {"ok": False, "host": host, "rtt_ms": None, "latency_ms": int((time.monotonic() - t0) * 1000), "detail": str(exc)}


@router.post("/api/netdiag/dns")
async def netdiag_dns(body: dict):
    import time
    host = (body.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="host required")
    t0 = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout=5)
        latency_ms = int((time.monotonic() - t0) * 1000)
        ips = list(dict.fromkeys(i[4][0] for i in infos))
        return {"ok": True, "host": host, "ips": ips, "latency_ms": latency_ms}
    except Exception as exc:
        return {"ok": False, "host": host, "ips": [], "latency_ms": int((time.monotonic() - t0) * 1000), "detail": str(exc)}


@router.post("/api/netdiag/port")
async def netdiag_port(body: dict):
    import time
    host = (body.get("host") or "").strip()
    port = body.get("port")
    if not host or port is None:
        raise HTTPException(status_code=422, detail="host and port required")
    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=5)
        writer.close()
        await writer.wait_closed()
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": True, "host": host, "port": int(port), "latency_ms": latency_ms, "detail": "open"}
    except Exception as exc:
        return {"ok": False, "host": host, "port": int(port) if port else None, "latency_ms": int((time.monotonic() - t0) * 1000), "detail": str(exc)}


# ── Notification log ──────────────────────────────────────────────────────────

_NOTIF_LOG: _collections.deque = _collections.deque(maxlen=200)


def _on_notif_event(payload: dict) -> None:
    if payload.get("type") not in ("reminder_fired",):
        return
    import time as _t
    _NOTIF_LOG.appendleft({
        "ts": _t.time(),
        "source": "reminder",
        "message": payload.get("message", ""),
        "id": payload.get("id"),
    })


events.subscribe(_on_notif_event)


@router.get("/api/notifications/log")
async def get_notification_log(n: int = 50):
    return {"notifications": list(_NOTIF_LOG)[:min(n, 200)]}


@router.delete("/api/notifications/log")
async def clear_notification_log():
    _NOTIF_LOG.clear()
    return {"ok": True}


# ── Config diff ───────────────────────────────────────────────────────────────

@router.get("/api/config/diff")
async def config_diff():
    import dataclasses
    defaults = dataclasses.asdict(type(get_config())())
    current = dataclasses.asdict(get_config())
    _BLOCKED = {"system_prompt_backup", "fallback_api_key", "hass_token", "gcal_credentials_file"}
    diffs = []
    for key, default_val in defaults.items():
        if key in _BLOCKED:
            continue
        cur_val = current.get(key)
        if cur_val != default_val:
            diffs.append({"key": key, "default": default_val, "current": cur_val})
    return {"diffs": diffs, "total": len(diffs)}


@router.get("/api/mcp/servers")
async def get_mcp_servers():
    return get_mcp_status()


@router.post("/api/mcp/servers/{name}/disable")
async def disable_mcp_server_endpoint(name: str):
    if not disable_mcp_server(name):
        raise HTTPException(status_code=404, detail=f"MCP server {name!r} not found")
    return {"ok": True}


@router.post("/api/mcp/restart")
async def restart_mcp_endpoint():
    await restart_mcp_servers()
    return {"ok": True}


@router.get("/api/mcp/config")
async def get_mcp_config():
    from core.mcp_client import _MCP_CONFIG
    if not _MCP_CONFIG.exists():
        return []
    try:
        return json.loads(_MCP_CONFIG.read_text())
    except Exception:
        return []


@router.put("/api/mcp/config")
async def put_mcp_config(request: Request):
    from core.mcp_client import _MCP_CONFIG, _validate_configs
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": f"Invalid JSON: {e}"})
    if not isinstance(body, list):
        return JSONResponse(status_code=422, content={"error": "Config must be a JSON array"})
    try:
        _validate_configs(body)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})
    _MCP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = _MCP_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, indent=2) + "\n")
    tmp.replace(_MCP_CONFIG)
    return {"ok": True}


@router.post("/api/news/search")
async def news_search(body: dict):
    query = body.get("query", "").strip()
    max_items = max(1, min(int(body.get("max_items", 10)), 20))
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required")
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise HTTPException(status_code=503, detail="ddgs not installed")
    try:
        results = await asyncio.to_thread(lambda: list(DDGS().news(query, max_results=max_items)))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    items = [
        {"title": r.get("title", ""), "date": r.get("date", "")[:10],
         "source": r.get("source", ""), "url": r.get("url", "")}
        for r in results if r.get("title")
    ]
    return {"query": query, "items": items}


@router.post("/api/news/rss")
async def news_rss(body: dict):
    url = body.get("url", "").strip()
    max_items = max(1, min(int(body.get("max_items", 10)), 50))
    if not url:
        raise HTTPException(status_code=400, detail="'url' is required")
    try:
        import feedparser
    except ImportError:
        raise HTTPException(status_code=503, detail="feedparser not installed")
    try:
        feed = await asyncio.to_thread(feedparser.parse, url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    feed_title = feed.feed.get("title", url)
    entries = [
        {"title": e.get("title", "(no title)"),
         "published": e.get("published", "")[:16],
         "link": e.get("link", "")}
        for e in feed.entries[:max_items]
    ]
    return {"feed_title": feed_title, "url": url, "items": entries}


# ── Tor / VPN ───────────────────────────────────────────────────────────────

@router.get("/api/tor/status")
async def get_tor_status():
    import core.tor_manager as tm
    return tm.get_status()


@router.post("/api/tor/enable")
async def post_tor_enable():
    import core.tor_manager as tm
    message = await asyncio.to_thread(tm.enable)
    success = message.lower().startswith("tor enabled")
    if success:
        await tm._start_monitor(tm._last_tor_uid)
    return {"success": success, "message": message}


@router.post("/api/tor/disable")
async def post_tor_disable():
    import core.tor_manager as tm
    message = await asyncio.to_thread(tm.disable)
    success = message.lower().startswith("tor disabled")
    return {"success": success, "message": message}


@router.get("/api/network/wifi")
async def network_wifi():
    import subprocess
    status: dict = {}
    try:
        r = await asyncio.to_thread(
            subprocess.run,
            ["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION,DEVICE", "--escape", "no", "dev", "status"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == "wifi" and "connected" in parts[1] and parts[2]:
                status = {"ssid": parts[2], "device": parts[3], "connected": True}
                break
    except Exception:
        pass
    networks: list = []
    try:
        r = await asyncio.to_thread(
            subprocess.run,
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,CHAN", "--escape", "no", "dev", "wifi", "list"],
            capture_output=True, text=True, timeout=15,
        )
        seen: set = set()
        for line in r.stdout.strip().splitlines():
            parts = line.rsplit(":", 3)
            if len(parts) < 4:
                continue
            ssid, signal, security, chan = parts
            ssid = ssid or "<hidden>"
            key = (ssid, chan)
            if key in seen:
                continue
            seen.add(key)
            networks.append({
                "ssid": ssid,
                "signal": int(signal) if signal.isdigit() else 0,
                "security": security or "open",
                "chan": chan,
            })
        networks.sort(key=lambda n: -n["signal"])
    except Exception:
        pass
    return {"status": status, "networks": networks}


@router.get("/api/network/mac")
async def network_mac_list():
    from modules.network_tools import list_macs
    result = await asyncio.to_thread(list_macs)
    return {"result": result}


@router.post("/api/network/mac/randomize")
async def network_mac_randomize(body: dict):
    from modules.network_tools import randomize_mac
    result = await asyncio.to_thread(randomize_mac, body.get("interface", ""))
    return {"result": result}


@router.post("/api/network/mac/restore")
async def network_mac_restore(body: dict):
    from modules.network_tools import restore_mac
    result = await asyncio.to_thread(restore_mac, body.get("interface", ""))
    return {"result": result}


# ── Observer ─────────────────────────────────────────────────────────────────

@router.get("/api/observer/status")
async def get_observer_status():
    import core.observer as obs_mod
    obs = obs_mod.get_observer()
    return {
        "enabled": get_config().observer_enabled,
        "running": obs.is_running(),
        "last_capture": obs.last_capture_ts(),
        "last_profile": obs.last_profile_ts(),
        "profile_preview": obs.get_profile()[:200],
    }


@router.post("/api/observer/enable")
async def post_observer_enable():
    import core.observer as obs_mod
    import core.config as cfg_mod
    obs = obs_mod.get_observer()
    if not obs.is_running():
        asyncio.create_task(obs.start())
    cfg_mod.update_config(observer_enabled=True)
    await events.emit("observer_status", {
        "enabled": True, "running": True,
        "last_capture": obs.last_capture_ts(),
        "last_profile": obs.last_profile_ts(),
        "profile_preview": obs.get_profile()[:200],
    })
    return {"success": True, "message": "Observer enabled"}


@router.post("/api/observer/disable")
async def post_observer_disable():
    import core.observer as obs_mod
    import core.config as cfg_mod
    obs = obs_mod.get_observer()
    if obs.is_running():
        asyncio.create_task(obs.stop())
    cfg_mod.update_config(observer_enabled=False)
    await events.emit("observer_status", {
        "enabled": False, "running": False,
        "last_capture": None, "last_profile": None, "profile_preview": "",
    })
    return {"success": True, "message": "Observer disabled"}


@router.get("/api/observer/activity")
async def get_observer_activity(minutes: int = 60):
    import core.observer as obs_mod
    from agents.observer_store import get_observer_store
    obs = obs_mod.get_observer()
    store = get_observer_store()
    recent = await asyncio.to_thread(store.get_recent_obs, minutes)
    focus = recent.get("focus", [])

    # Aggregate seconds per app
    app_seconds: dict[str, float] = {}
    for e in focus:
        app = e["app_name"] or "unknown"
        app_seconds[app] = app_seconds.get(app, 0) + e["duration_seconds"]
    top_apps = sorted(
        [{"app": k, "seconds": round(v)} for k, v in app_seconds.items()],
        key=lambda x: x["seconds"], reverse=True
    )[:8]

    timeline = [
        {"ts": e["ts"], "app": e["app_name"] or "unknown",
         "window": e["window_title"] or "", "duration": round(e["duration_seconds"])}
        for e in focus[-30:]
    ]

    return {
        "current_app": obs._current_app or "",
        "current_window": obs._current_window or "",
        "top_apps": top_apps,
        "timeline": timeline,
        "profile": obs.get_profile(),
    }


@router.get("/api/proactive/status")
async def get_proactive_status():
    import core.proactive as pro_mod
    pro = pro_mod.get_proactive()
    cfg = get_config()
    return {
        "enabled": cfg.proactive_enabled,
        "running": pro.is_running(),
        "last_message_ts": pro.last_message_ts(),
        "last_trigger_type": pro.last_trigger_type(),
        "quiet_hours_start": cfg.proactive_quiet_hours_start,
        "quiet_hours_end": cfg.proactive_quiet_hours_end,
        "distraction_threshold": cfg.proactive_distraction_threshold,
        "checkin_interval": cfg.proactive_checkin_interval,
    }


@router.post("/api/proactive/enable")
async def post_proactive_enable():
    import core.proactive as pro_mod
    import core.config as cfg_mod
    pro = pro_mod.get_proactive()
    if not pro.is_running():
        asyncio.create_task(pro.start())
    cfg_mod.update_config(proactive_enabled=True)
    await events.emit("proactive_status", {"enabled": True, "running": True})
    return {"success": True, "message": "Proactive assistant enabled"}


@router.post("/api/proactive/disable")
async def post_proactive_disable():
    import core.proactive as pro_mod
    import core.config as cfg_mod
    pro = pro_mod.get_proactive()
    if pro.is_running():
        asyncio.create_task(pro.stop())
    cfg_mod.update_config(proactive_enabled=False)
    await events.emit("proactive_status", {"enabled": False, "running": False})
    return {"success": True, "message": "Proactive assistant disabled"}


@router.get("/api/documents/sources")
async def list_document_sources():
    from agents.document_store import get_document_store
    sources = await asyncio.to_thread(get_document_store().list_sources)
    return {"sources": sources}


@router.post("/api/documents/index")
async def index_documents_endpoint(body: dict):
    from agents.document_store import get_document_store
    directory = body.get("directory", "").strip()
    glob = body.get("glob", "**/*.txt").strip() or "**/*.txt"
    if not directory:
        raise HTTPException(status_code=400, detail="'directory' is required")
    result = await asyncio.to_thread(get_document_store().index_directory, directory, glob)
    return {"result": result}


@router.post("/api/documents/remove")
async def remove_document_source(body: dict):
    from agents.document_store import get_document_store
    source = body.get("source", "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="'source' is required")
    n = await asyncio.to_thread(get_document_store().delete_source, source)
    return {"removed": n}


@router.post("/api/documents/search")
async def search_documents(body: dict):
    from agents.document_store import get_document_store
    query = body.get("query", "").strip()
    n_results = max(1, min(int(body.get("n_results", 5)), 20))
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required")
    result = await asyncio.to_thread(get_document_store().query, query, n_results)
    return {"result": result}


@router.get("/api/media/status")
async def media_status():
    import subprocess, re
    try:
        meta = await asyncio.to_thread(
            subprocess.run,
            ["playerctl", "metadata", "--format", "{{artist}} - {{title}}"],
            capture_output=True, text=True, timeout=5,
        )
        stat = await asyncio.to_thread(
            subprocess.run,
            ["playerctl", "status"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"text": "", "playing": False, "status": "unknown"}
    status = stat.stdout.strip() if stat.returncode == 0 else "unknown"
    track = meta.stdout.strip() if meta.returncode == 0 else ""
    if not track or re.fullmatch(r"\s*-\s*", track):
        track = ""
    playing = status == "Playing" and bool(track)
    return {"text": track, "playing": playing, "status": status}


@router.post("/api/media/{action}")
async def media_action(action: str):
    import subprocess
    if action not in {"play", "pause", "next", "previous", "stop"}:
        raise HTTPException(status_code=404, detail=f"Unknown action: {action}")
    try:
        r = await asyncio.to_thread(
            subprocess.run, ["playerctl", action],
            capture_output=True, text=True, timeout=5,
        )
        return {"result": "ok" if r.returncode == 0 else r.stderr.strip()}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="playerctl not installed")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="playerctl timed out")


@router.get("/api/media/volume")
async def media_volume_get():
    import subprocess, re
    try:
        r = await asyncio.to_thread(
            subprocess.run, ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"[\d.]+", r.stdout)
        if not m:
            return {"percent": 50, "muted": False}
        return {"percent": round(float(m.group()) * 100), "muted": "[MUTED]" in r.stdout}
    except Exception:
        return {"percent": 50, "muted": False}


@router.post("/api/media/volume")
async def media_volume_set(body: dict):
    import subprocess
    percent = max(0, min(100, int(body.get("percent", 50))))
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent / 100:.2f}"],
            check=True, capture_output=True, timeout=5,
        )
        return {"percent": percent}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="wpctl not installed")
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.stderr.decode().strip())


@router.post("/api/media/mute")
async def media_mute():
    import subprocess
    try:
        await asyncio.to_thread(
            subprocess.run, ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"],
            check=True, capture_output=True, timeout=5,
        )
        return {"muted": True}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="wpctl not installed")


@router.post("/api/media/unmute")
async def media_unmute():
    import subprocess
    try:
        await asyncio.to_thread(
            subprocess.run, ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
            check=True, capture_output=True, timeout=5,
        )
        return {"muted": False}
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="wpctl not installed")


# ── File browser ─────────────────────────────────────────────────────────────

_MAX_READ_BYTES = 2 * 1024 * 1024  # 2 MB


def _safe_path(raw: str) -> str:
    """Resolve and return absolute path; no traversal prevention — local assistant."""
    return str(pathlib.Path(raw).expanduser().resolve())


@router.get("/api/files")
async def files_list(path: str = "~"):
    import os, stat as _stat
    p = _safe_path(path)
    if not os.path.isdir(p):
        raise HTTPException(status_code=404, detail="Not a directory")
    entries = []
    try:
        for name in os.listdir(p):
            full = os.path.join(p, name)
            try:
                st = os.stat(full)
                entries.append({
                    "name": name,
                    "type": "dir" if _stat.S_ISDIR(st.st_mode) else "file",
                    "size": st.st_size,
                    "modified": int(st.st_mtime),
                })
            except OSError:
                pass
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
    parent = str(pathlib.Path(p).parent) if p != "/" else None
    return {"path": p, "parent": parent, "entries": entries}


@router.get("/api/files/read")
async def files_read(path: str):
    import os
    p = _safe_path(path)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="Not a file")
    size = os.path.getsize(p)
    if size > _MAX_READ_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large ({size} bytes)")
    raw = await asyncio.to_thread(pathlib.Path(p).read_bytes)
    try:
        content = raw.decode("utf-8")
        binary = False
    except UnicodeDecodeError:
        content = ""
        binary = True
    return {"path": p, "content": content, "size": size, "binary": binary}


@router.post("/api/files/write")
async def files_write(body: dict):
    path = body.get("path", "")
    content = body.get("content", "")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    p = pathlib.Path(_safe_path(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(p.write_text, content, encoding="utf-8")
    return {"ok": True, "path": str(p)}


@router.delete("/api/files")
async def files_delete(path: str):
    import os, shutil
    p = _safe_path(path)
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Not found")
    if os.path.isdir(p):
        await asyncio.to_thread(shutil.rmtree, p)
    else:
        await asyncio.to_thread(os.remove, p)
    return {"ok": True}


@router.post("/api/files/mkdir")
async def files_mkdir(body: dict):
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    p = pathlib.Path(_safe_path(path))
    await asyncio.to_thread(p.mkdir, parents=True, exist_ok=True)
    return {"ok": True, "path": str(p)}


@router.post("/api/files/rename")
async def files_rename(body: dict):
    src = body.get("from", "")
    dst = body.get("to", "")
    if not src or not dst:
        raise HTTPException(status_code=400, detail="from and to required")
    ps = pathlib.Path(_safe_path(src))
    pd = pathlib.Path(_safe_path(dst))
    if not ps.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    await asyncio.to_thread(ps.rename, pd)
    return {"ok": True}


# ── Voice clip manager ────────────────────────────────────────────────────────

_AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}


def _clip_path(filename: str) -> Path:
    safe = Path(filename).name
    if not safe or safe in (".", ".."):
        raise ValueError("Invalid filename")
    return UPLOADS_DIR / safe


def _list_clips_sync() -> list[dict]:
    import os, stat as _stat
    cfg = get_config()
    active = {cfg.chatterbox_reference_audio, cfg.dramabox_voice_ref}
    clips = []
    if not UPLOADS_DIR.exists():
        return []
    for p in UPLOADS_DIR.iterdir():
        if p.suffix.lower() not in _AUDIO_EXTS:
            continue
        st = p.stat()
        clips.append({
            "filename": p.name,
            "size": st.st_size,
            "modified": int(st.st_mtime),
            "active_chatterbox": str(p) == cfg.chatterbox_reference_audio,
            "active_dramabox": str(p) == cfg.dramabox_voice_ref,
        })
    clips.sort(key=lambda c: c["modified"], reverse=True)
    return clips


@router.get("/api/clips")
async def list_clips():
    clips = await asyncio.to_thread(_list_clips_sync)
    return {"clips": clips}


@router.post("/api/clips/upload")
async def upload_clip(file: UploadFile = File(...)):
    import time as _t
    allowed = {".wav", ".mp3", ".ogg", ".flac"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported format; allowed: {', '.join(sorted(allowed))}")
    ts = int(_t.time())
    safe_orig = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(file.filename or "unnamed").name)
    dest = UPLOADS_DIR / f"upload_{ts}_{safe_orig}"
    data = await file.read()
    dest.write_bytes(data)
    return {"ok": True, "filename": dest.name, "size": len(data)}


@router.get("/api/clips/{filename}")
async def serve_clip(filename: str):
    try:
        p = _clip_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(str(p), media_type="audio/mpeg" if p.suffix.lower() == ".mp3" else "audio/wav")


@router.post("/api/clips/{filename}/activate")
async def activate_clip(filename: str, body: dict):
    try:
        p = _clip_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    target = body.get("target", "chatterbox")
    if target == "dramabox":
        await asyncio.to_thread(update_config, dramabox_voice_ref=str(p))
    else:
        await asyncio.to_thread(update_config, chatterbox_reference_audio=str(p))
    return {"ok": True, "target": target, "path": str(p)}


@router.delete("/api/clips/{filename}")
async def delete_clip(filename: str):
    import os
    try:
        p = _clip_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    cfg = get_config()
    updates: dict = {}
    if cfg.chatterbox_reference_audio == str(p):
        updates["chatterbox_reference_audio"] = None
    if cfg.dramabox_voice_ref == str(p):
        updates["dramabox_voice_ref"] = None
    await asyncio.to_thread(os.remove, p)
    if updates:
        await asyncio.to_thread(update_config, **updates)
    return {"ok": True}


@router.post("/api/clips/{filename}/rename")
async def rename_clip(filename: str, body: dict):
    new_name = (body.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="name required")
    try:
        src = _clip_path(filename)
        dst = _clip_path(new_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    if dst.exists():
        raise HTTPException(status_code=409, detail="Name already taken")
    await asyncio.to_thread(src.rename, dst)
    cfg = get_config()
    updates: dict = {}
    if cfg.chatterbox_reference_audio == str(src):
        updates["chatterbox_reference_audio"] = str(dst)
    if cfg.dramabox_voice_ref == str(src):
        updates["dramabox_voice_ref"] = str(dst)
    if updates:
        await asyncio.to_thread(update_config, **updates)
    return {"ok": True, "filename": dst.name}


# ── Variable store ───────────────────────────────────────────────────────────

@router.get("/api/vars")
async def list_vars_endpoint():
    from agents.variable_store import list_vars
    return {"vars": await asyncio.to_thread(list_vars)}


@router.post("/api/vars")
async def set_var_endpoint(body: dict):
    from agents.variable_store import set_var
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    value = str(body.get("value", ""))
    description = body.get("description", "")
    await asyncio.to_thread(set_var, name, value, description)
    return {"ok": True, "name": name}


@router.delete("/api/vars/{name}")
async def delete_var_endpoint(name: str):
    from agents.variable_store import delete_var
    deleted = await asyncio.to_thread(delete_var, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Variable not found")
    return {"ok": True}


# ── Config snapshots ──────────────────────────────────────────────────────────

@router.get("/api/snapshots")
async def list_snapshots_endpoint():
    from core.snapshot_store import list_snapshots
    return {"snapshots": await asyncio.to_thread(list_snapshots)}


@router.post("/api/snapshots")
async def create_snapshot_endpoint(body: dict):
    from core.snapshot_store import create_snapshot
    label = body.get("label", "")
    name = await asyncio.to_thread(create_snapshot, label)
    return {"ok": True, "name": name}


@router.post("/api/snapshots/{name}/restore")
async def restore_snapshot_endpoint(name: str):
    from core.snapshot_store import restore_snapshot
    try:
        result = await asyncio.to_thread(restore_snapshot, name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, **result}


@router.delete("/api/snapshots/{name}")
async def delete_snapshot_endpoint(name: str):
    from core.snapshot_store import delete_snapshot
    deleted = await asyncio.to_thread(delete_snapshot, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"ok": True}


# ── Conversation forks ───────────────────────────────────────────────────────

@router.get("/api/chat/forks")
async def list_chat_forks():
    from core.fork_store import list_forks
    return {"forks": await asyncio.to_thread(list_forks)}


@router.post("/api/chat/forks")
async def save_chat_fork(body: dict):
    from core.fork_store import save_fork
    from agents.chat_history import get_recent
    label = body.get("label", "")
    turns = await asyncio.to_thread(get_recent, 500)
    if not turns:
        raise HTTPException(status_code=400, detail="No chat history to fork")
    name = await asyncio.to_thread(save_fork, label, turns)
    return {"ok": True, "name": name, "turn_count": len(turns)}


@router.get("/api/chat/forks/{name}")
async def get_chat_fork(name: str):
    from core.fork_store import get_fork
    fork = await asyncio.to_thread(get_fork, name)
    if fork is None:
        raise HTTPException(status_code=404, detail="Fork not found")
    return fork


@router.post("/api/chat/forks/{name}/restore")
async def restore_chat_fork(name: str):
    from core.fork_store import get_fork, save_fork
    from agents.chat_history import get_recent, add_message, clear
    fork = await asyncio.to_thread(get_fork, name)
    if fork is None:
        raise HTTPException(status_code=404, detail="Fork not found")
    # Auto-save current history before overwriting
    current = await asyncio.to_thread(get_recent, 500)
    if current:
        await asyncio.to_thread(save_fork, "pre-restore", current)
    await asyncio.to_thread(clear)
    turns = fork.get("turns", [])
    for turn in turns:
        await asyncio.to_thread(add_message, turn["role"], turn["content"])
    await events.emit("clear_history", {})
    return {"ok": True, "restored": name, "turn_count": len(turns)}


@router.delete("/api/chat/forks/{name}")
async def delete_chat_fork(name: str):
    from core.fork_store import delete_fork
    deleted = await asyncio.to_thread(delete_fork, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Fork not found")
    return {"ok": True}


# ── Pipeline replay ───────────────────────────────────────────────────────────

@router.post("/api/pipeline/replay")
async def pipeline_replay(body: dict):
    from core.supervisor import run_turn
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    cfg = get_config()
    messages = [
        {"role": "system", "content": cfg.system_prompt},
        {"role": "user", "content": message},
    ]
    t0 = asyncio.get_event_loop().time()
    response, _ = await run_turn(messages)
    latency_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
    return {"response": response, "latency_ms": latency_ms}


# ── Git panel ─────────────────────────────────────────────────────────────────

_GIT_ROOT = Path(__file__).resolve().parent.parent


async def _git(*args: str, check: bool = False) -> tuple[int, str, str]:
    import subprocess
    result = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(_GIT_ROOT), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.returncode, result.stdout, result.stderr


def _parse_status(porcelain: str) -> dict:
    staged, unstaged, untracked = [], [], []
    _STATUS_LABELS = {
        "M": "modified", "A": "added", "D": "deleted",
        "R": "renamed", "C": "copied", "U": "unmerged",
    }
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        x, y, path = line[0], line[1], line[3:]
        if x == "?" and y == "?":
            untracked.append(path)
            continue
        if x != " " and x != "?":
            staged.append({"status": _STATUS_LABELS.get(x, x), "path": path})
        if y != " " and y != "?":
            unstaged.append({"status": _STATUS_LABELS.get(y, y), "path": path})
    return {"staged": staged, "unstaged": unstaged, "untracked": untracked}


@router.get("/api/git/status")
async def git_status():
    rc, branch_out, _ = await _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        raise HTTPException(status_code=500, detail="Not a git repository")
    branch = branch_out.strip()
    _, porcelain, _ = await _git("status", "--porcelain=v1")
    parsed = _parse_status(porcelain)
    parsed["branch"] = branch
    parsed["clean"] = not (parsed["staged"] or parsed["unstaged"] or parsed["untracked"])
    return parsed


@router.get("/api/git/log")
async def git_log(n: int = 25):
    _, out, _ = await _git("log", f"--format=%H|%ai|%an|%s", f"-n{n}")
    commits = []
    for line in out.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            h, date, author, msg = parts
            commits.append({"hash": h, "short": h[:7], "date": date[:16], "author": author, "message": msg})
    return {"commits": commits}


@router.get("/api/git/diff")
async def git_diff(path: str = "", staged: bool = False):
    args = ["diff"]
    if staged:
        args.append("--cached")
    if path:
        args += ["--", path]
    _, out, _ = await _git(*args)
    return {"diff": out}


@router.post("/api/git/stage")
async def git_stage(body: dict):
    files = body.get("files", [])
    all_files = body.get("all", False)
    if all_files:
        rc, _, err = await _git("add", "-A")
    elif files:
        rc, _, err = await _git("add", "--", *files)
    else:
        raise HTTPException(status_code=400, detail="files or all required")
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip())
    return {"ok": True}


@router.post("/api/git/unstage")
async def git_unstage(body: dict):
    files = body.get("files", [])
    if not files:
        raise HTTPException(status_code=400, detail="files required")
    rc, _, err = await _git("restore", "--staged", "--", *files)
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip())
    return {"ok": True}


@router.post("/api/git/commit")
async def git_commit(body: dict):
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    rc, out, err = await _git("commit", "-m", message)
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip() or out.strip())
    return {"ok": True, "output": out.strip()}


@router.post("/api/git/push")
async def git_push():
    rc, out, err = await _git("push")
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip() or out.strip())
    return {"ok": True, "output": (out + err).strip()}


@router.post("/api/git/pull")
async def git_pull():
    rc, out, err = await _git("pull")
    if rc != 0:
        raise HTTPException(status_code=500, detail=err.strip() or out.strip())
    return {"ok": True, "output": (out + err).strip()}


# ── Log buffer ────────────────────────────────────────────────────────────────

_LEVEL_MAP = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


@router.get("/api/logs")
async def get_logs(n: int = 200, level: str = "DEBUG"):
    from core.log_buffer import get_log_buffer
    min_level = _LEVEL_MAP.get(level.upper(), 0)
    records = await asyncio.to_thread(get_log_buffer().get, n, min_level)
    return {"records": records}


@router.post("/api/logs/clear")
async def clear_logs():
    from core.log_buffer import get_log_buffer
    await asyncio.to_thread(get_log_buffer().clear)
    return {"ok": True}


@router.get("/api/logs/tail")
async def log_tail(level: str = "DEBUG"):
    from core.log_buffer import get_log_buffer
    min_level = _LEVEL_MAP.get(level.upper(), 0)
    buf = get_log_buffer()
    with buf._lock:
        seq = buf._seq

    async def _stream():
        nonlocal seq
        while True:
            records = await asyncio.to_thread(buf.get_since, seq - 1, min_level)
            if records:
                for r in records:
                    yield f"data: {json.dumps(r)}\n\n"
                seq = records[-1]["seq"] + 1
            await asyncio.sleep(0.5)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── Workflows ─────────────────────────────────────────────────────────────────

@router.get("/api/workflows/history")
async def workflow_history(n: int = 50):
    return {"history": list(_WORKFLOW_HISTORY)[:n]}


@router.delete("/api/workflows/history")
async def clear_workflow_history():
    _WORKFLOW_HISTORY.clear()
    return {"ok": True}


@router.get("/api/workflows")
async def list_workflows_endpoint():
    from agents.workflow_store import list_workflows
    return {"workflows": await asyncio.to_thread(list_workflows)}


@router.post("/api/workflows")
async def save_workflow_endpoint(body: dict):
    from agents.workflow_store import save_workflow
    name = body.get("name", "").strip()
    steps = body.get("steps", [])
    description = body.get("description", "")
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    if not isinstance(steps, list):
        raise HTTPException(status_code=400, detail="steps must be a list")
    await asyncio.to_thread(save_workflow, name, steps, description)
    return {"ok": True, "name": name}


@router.delete("/api/workflows/{name}")
async def delete_workflow_endpoint(name: str):
    from agents.workflow_store import delete_workflow
    deleted = await asyncio.to_thread(delete_workflow, name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"ok": True}


@router.post("/api/workflows/{name}/run")
async def run_workflow_endpoint(name: str):
    import time as _t
    from agents.workflow_store import run_workflow
    t0 = _t.monotonic()
    try:
        results = await run_workflow(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    duration_ms = int((_t.monotonic() - t0) * 1000)
    success = all(s.get("error") is None for s in results)
    _WORKFLOW_HISTORY.appendleft({
        "ts": _time_top.time(),
        "name": name,
        "steps": len(results),
        "duration_ms": duration_ms,
        "success": success,
        "errors": [s["error"] for s in results if s.get("error")],
    })
    return {"name": name, "steps": results}


# ── Webhooks ──────────────────────────────────────────────────────────────────

@router.get("/api/webhooks")
async def list_webhooks_endpoint():
    from agents.webhook_store import list_webhooks
    return {"webhooks": await asyncio.to_thread(list_webhooks)}


@router.post("/api/webhooks")
async def save_webhook_endpoint(body: dict):
    from agents.webhook_store import save_webhook
    slug = body.get("slug", "").strip().replace(" ", "-")
    target = body.get("target", "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug required")
    if not target:
        raise HTTPException(status_code=400, detail="target required")
    await asyncio.to_thread(
        save_webhook, slug,
        name=body.get("name", ""),
        target_type=body.get("target_type", "workflow"),
        target=target,
        params=body.get("params", {}),
        description=body.get("description", ""),
        secret=body.get("secret", ""),
    )
    return {"ok": True, "slug": slug}


@router.delete("/api/webhooks/{slug}")
async def delete_webhook_endpoint(slug: str):
    from agents.webhook_store import delete_webhook
    deleted = await asyncio.to_thread(delete_webhook, slug)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return {"ok": True}


@router.get("/api/prompts")
async def list_prompts_endpoint():
    from agents.prompt_store import list_prompts
    return {"prompts": await asyncio.to_thread(list_prompts)}


@router.post("/api/prompts")
async def save_prompt_endpoint(body: dict):
    from agents.prompt_store import save_prompt
    name = (body.get("name") or "").strip()
    text = (body.get("text") or "").strip()
    description = (body.get("description") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="'name' required")
    if not text:
        raise HTTPException(status_code=422, detail="'text' required")
    try:
        await asyncio.to_thread(save_prompt, name, text, description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "name": name}


@router.delete("/api/prompts/{name}")
async def delete_prompt_endpoint(name: str):
    from agents.prompt_store import delete_prompt
    deleted = await asyncio.to_thread(delete_prompt, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found")
    return {"ok": True}


@router.post("/api/prompts/{name}/apply")
async def apply_prompt_endpoint(name: str):
    from agents.prompt_store import get_prompt
    prompt = await asyncio.to_thread(get_prompt, name)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt {name!r} not found")
    try:
        config = update_config(system_prompt=prompt["text"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "system_prompt": config.system_prompt}


@router.post("/api/webhooks/{slug}/test")
async def test_webhook(slug: str, body: dict):
    """Fire a webhook from the dashboard — skips secret check, adds timing."""
    import time
    from agents.webhook_store import get_webhook, fire_webhook
    wh = await asyncio.to_thread(get_webhook, slug)
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"body": payload}
    t0 = time.monotonic()
    try:
        result = await fire_webhook(slug, payload)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": result.get("ok", True), "result": result, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "error": str(exc), "result": None, "latency_ms": latency_ms}


@router.post("/api/webhooks/trigger/{slug}")
async def trigger_webhook(slug: str, request: Request):
    from agents.webhook_store import get_webhook, fire_webhook
    wh = await asyncio.to_thread(get_webhook, slug)
    if wh is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    secret = wh.get("secret", "")
    if secret:
        provided = request.headers.get("X-Webhook-Secret", "")
        if provided != secret:
            raise HTTPException(status_code=401, detail="Invalid secret")
    try:
        body = await request.json()
        payload = body if isinstance(body, dict) else {"body": body}
    except Exception:
        payload = {}
    result = await fire_webhook(slug, payload)
    return result


# ── Global search ─────────────────────────────────────────────────────────────

@router.get("/api/search")
async def global_search(q: str = "", n: int = 20):
    if not q.strip():
        return {"query": q, "results": {}}

    from agents.variable_store import list_vars
    from agents.workflow_store import list_workflows
    from agents.webhook_store import list_webhooks

    store = get_memory_store()
    ql = q.lower()

    def _search_all():
        hits: dict[str, list] = {}

        chat = chat_search(q, n)
        if chat:
            hits["chat"] = [{"role": m["role"], "content": m["content"], "ts": m["ts"]} for m in chat]

        facts = store.search_facts(q, n)
        if facts:
            hits["facts"] = facts

        reminders = store.search_reminders(q, n)
        if reminders:
            hits["reminders"] = reminders

        # variables (in-memory JSON)
        var_hits = [v for v in list_vars() if ql in v["name"].lower() or ql in v["value"].lower()
                    or ql in (v.get("description") or "").lower()]
        if var_hits:
            hits["variables"] = var_hits[:n]

        # workflows
        wf_hits = [w for w in list_workflows()
                   if ql in w["name"].lower() or ql in (w.get("description") or "").lower()
                   or any(ql in (s.get("tool") or "").lower() or ql in (s.get("note") or "").lower()
                          for s in w.get("steps", []))]
        if wf_hits:
            hits["workflows"] = [{"name": w["name"], "description": w.get("description", ""),
                                   "steps": len(w.get("steps", []))} for w in wf_hits[:n]]

        # webhooks
        try:
            wh_hits = [h for h in list_webhooks()
                       if ql in h.get("slug", "").lower() or ql in h.get("name", "").lower()
                       or ql in h.get("target", "").lower()]
            if wh_hits:
                hits["webhooks"] = [{"slug": h["slug"], "name": h.get("name", ""),
                                     "target": h.get("target", "")} for h in wh_hits[:n]]
        except Exception:
            pass

        return hits

    results = await asyncio.to_thread(_search_all)
    total = sum(len(v) for v in results.values())
    return {"query": q, "results": results, "total": total}


# ── Event history ─────────────────────────────────────────────────────────────

@router.get("/api/events")
async def list_events(n: int = 200, type: str | None = None):
    from core.event_log import get_events, get_event_types
    events_list = await asyncio.to_thread(get_events, n, type)
    types = await asyncio.to_thread(get_event_types)
    return {"events": events_list, "types": types, "count": len(events_list)}


@router.delete("/api/events")
async def clear_events_endpoint():
    from core.event_log import clear_events
    deleted = await asyncio.to_thread(clear_events)
    return {"ok": True, "deleted": deleted}


@router.get("/api/events/types")
async def list_event_types():
    from core.event_log import get_event_types
    types = await asyncio.to_thread(get_event_types)
    return {"types": types}


@router.get("/api/health")
async def system_health():
    import time
    import httpx
    config = get_config()
    results = []

    async def check(name: str, coro):
        try:
            detail = await coro
            results.append({"name": name, "status": "ok", "detail": detail or "OK"})
        except Exception as exc:
            results.append({"name": name, "status": "error", "detail": str(exc)})

    async def probe_ollama():
        if not config.ollama_url:
            results.append({"name": "ollama", "status": "unconfigured", "detail": "No URL set"})
            return
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{config.ollama_url}/api/tags")
        r.raise_for_status()
        data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        results.append({"name": "ollama", "status": "ok", "detail": f"{len(models)} model(s)"})

    async def probe_hass():
        if not config.hass_url or not config.hass_token:
            results.append({"name": "hass", "status": "unconfigured", "detail": "URL or token not set"})
            return
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(
                f"{config.hass_url.rstrip('/')}/api/",
                headers={"Authorization": f"Bearer {config.hass_token}"},
            )
        r.raise_for_status()
        results.append({"name": "hass", "status": "ok", "detail": r.json().get("message", "Connected")})

    async def probe_chromadb():
        def _check():
            import chromadb
            chroma_path = str(pathlib.Path(config.memory_dir).expanduser() / "chroma")
            chromadb.PersistentClient(path=chroma_path)
            return "Connected"
        detail = await asyncio.to_thread(_check)
        results.append({"name": "chromadb", "status": "ok", "detail": detail})

    async def probe_gcal():
        cred = config.gcal_credentials_file
        if not cred:
            results.append({"name": "gcal", "status": "unconfigured", "detail": "No credentials file set"})
            return
        p = pathlib.Path(cred).expanduser()
        if not p.exists():
            results.append({"name": "gcal", "status": "error", "detail": f"File not found: {cred}"})
        else:
            results.append({"name": "gcal", "status": "ok", "detail": str(p)})

    async def probe_email():
        def _check():
            from agents.email_store import list_accounts
            accounts = list_accounts()
            return accounts
        accounts = await asyncio.to_thread(_check)
        if not accounts:
            results.append({"name": "email", "status": "unconfigured", "detail": "No accounts configured"})
        else:
            names = ", ".join(a.get("email", a.get("name", "?")) for a in accounts)
            results.append({"name": "email", "status": "ok", "detail": names})

    async def probe_memory():
        def _check():
            from agents.memory_store import get_memory_store
            store = get_memory_store()
            facts = store.list_all()
            return len(facts)
        count = await asyncio.to_thread(_check)
        results.append({"name": "memory", "status": "ok", "detail": f"{count} facts stored"})

    async def probe_fallback_llm():
        provider = config.fallback_provider
        if not provider:
            results.append({"name": "fallback_llm", "status": "unconfigured", "detail": "No fallback provider set"})
            return
        key = config.fallback_api_key
        results.append({
            "name": "fallback_llm",
            "status": "ok" if key else "error",
            "detail": f"{provider} — {'API key set' if key else 'API key missing'}",
        })

    await asyncio.gather(
        probe_ollama(),
        probe_hass(),
        probe_chromadb(),
        probe_gcal(),
        probe_email(),
        probe_memory(),
        probe_fallback_llm(),
        return_exceptions=True,
    )

    order = ["ollama", "hass", "chromadb", "gcal", "email", "memory", "fallback_llm"]
    results.sort(key=lambda x: order.index(x["name"]) if x["name"] in order else 99)
    return {"services": results, "checked_at": time.time()}


@router.get("/api/inspector")
async def inspector(n: int = 50):
    from core.event_log import get_events
    raw = await asyncio.to_thread(get_events, n, "agent_routing")
    turns = []
    for ev in raw:
        d = ev.get("data", {})
        turns.append({
            "ts": ev["ts"],
            "agent": d.get("agent", "unknown"),
            "routing_method": d.get("routing_method", "unknown"),
            "query": d.get("query", ""),
            "latency_ms": d.get("latency_ms", 0),
            "tool": d.get("tool"),
        })
    return {"turns": turns, "count": len(turns)}


# ── Tool playground ───────────────────────────────────────────────────────────

@router.post("/api/tools/{name}/run")
async def run_tool_endpoint(name: str, body: dict):
    params = body.get("params", {})
    try:
        result = await call_tool_async(name, params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"Bad params: {exc}")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "result": None}
    return {"ok": True, "result": str(result) if result is not None else ""}


@router.get("/api/token-usage")
async def get_token_usage():
    from core.token_usage import get_stats
    return get_stats()


@router.post("/api/token-usage/reset")
async def reset_token_usage():
    from core.token_usage import reset
    reset()
    return {"ok": True}


@router.get("/api/cron")
async def list_cron_jobs():
    from agents.cron_store import get_cron_store
    from croniter import croniter
    from datetime import datetime, timezone
    jobs = await asyncio.to_thread(get_cron_store().list_all)
    now = datetime.now(timezone.utc)
    for job in jobs:
        try:
            job["next_run"] = croniter(job["expr"], now).get_next(datetime).isoformat()
        except Exception:
            job["next_run"] = None
    return jobs


@router.post("/api/cron")
async def add_cron_job(body: dict):
    name = (body.get("name") or "").strip()
    expr = (body.get("expr") or "").strip()
    message = (body.get("message") or "").strip()
    if not name or not expr or not message:
        raise HTTPException(status_code=422, detail="name, expr, and message required")
    try:
        from croniter import croniter
        if not croniter.is_valid(expr):
            raise HTTPException(status_code=422, detail=f"Invalid cron expression: {expr!r}")
    except ImportError:
        pass
    from agents.cron_store import get_cron_store
    jid = await asyncio.to_thread(get_cron_store().add, name, expr, message)
    return {"id": jid, "name": name, "expr": expr, "message": message}


@router.get("/api/cron/{name}/next")
async def cron_next_runs(name: str, n: int = 5):
    from agents.cron_store import get_cron_store
    from croniter import croniter
    from datetime import datetime, timezone
    jobs = await asyncio.to_thread(get_cron_store().list_all)
    job = next((j for j in jobs if j["name"] == name), None)
    if not job:
        raise HTTPException(status_code=404, detail=f"No cron job named {name!r}")
    n = max(1, min(n, 20))
    now = datetime.now(timezone.utc)
    try:
        cron = croniter(job["expr"], now)
        runs = [cron.get_next(datetime).isoformat() for _ in range(n)]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cron parse error: {exc}")
    return {"name": name, "expr": job["expr"], "next_runs": runs}


@router.delete("/api/cron/{name}")
async def delete_cron_job(name: str):
    from agents.cron_store import get_cron_store
    removed = await asyncio.to_thread(get_cron_store().remove, name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No cron job named {name!r}")
    return {"ok": True}


@router.patch("/api/cron/{name}")
async def patch_cron_job(name: str, body: dict):
    enabled = body.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=422, detail="'enabled' field required")
    from agents.cron_store import get_cron_store
    ok = await asyncio.to_thread(get_cron_store().set_enabled, name, bool(enabled))
    if not ok:
        raise HTTPException(status_code=404, detail=f"No cron job named {name!r}")
    return {"ok": True}


import collections as _collections
_BENCH_HISTORY: _collections.deque = _collections.deque(maxlen=50)
_BENCH_DEFAULT_PROMPT = "Respond in exactly one sentence: What is the capital of France?"


@router.post("/api/benchmark")
async def run_benchmark(body: dict):
    import time
    import httpx
    config = get_config()
    prompt = (body.get("prompt") or _BENCH_DEFAULT_PROMPT).strip()
    model = (body.get("model") or config.ollama_model).strip()
    runs = max(1, min(int(body.get("runs") or 1), 5))

    results = []
    for _ in range(runs):
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{config.ollama_url}/api/chat",
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
                )
            resp.raise_for_status()
            body_json = resp.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "results": []}
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        content = body_json.get("message", {}).get("content", "")
        prompt_tokens = body_json.get("prompt_eval_count") or 0
        completion_tokens = body_json.get("eval_count") or 0
        eval_duration_ns = body_json.get("eval_duration") or 0
        tps = round(completion_tokens / (eval_duration_ns / 1e9), 1) if eval_duration_ns > 0 else 0.0
        entry = {
            "ts": time.time(),
            "model": model,
            "prompt": prompt[:80],
            "latency_ms": elapsed_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tokens_per_sec": tps,
            "response_snippet": content[:120],
        }
        results.append(entry)
        _BENCH_HISTORY.appendleft(entry)

    avg_latency = int(sum(r["latency_ms"] for r in results) / len(results))
    avg_tps = round(sum(r["tokens_per_sec"] for r in results) / len(results), 1)
    return {"ok": True, "runs": results, "avg_latency_ms": avg_latency, "avg_tokens_per_sec": avg_tps}


@router.get("/api/benchmark/history")
async def benchmark_history(n: int = 20):
    return {"history": list(_BENCH_HISTORY)[:n]}


# ── Voice audio level ─────────────────────────────────────────────────────────

@router.get("/api/voice/level")
async def voice_audio_level():
    try:
        import voice.pipeline as _vp
        level = _vp._CURRENT_AUDIO_LEVEL
    except Exception:
        level = 0.0
    return {"level": round(level, 4)}


# ── LLM streaming (SSE) ───────────────────────────────────────────────────────

@router.post("/api/chat/stream")
async def chat_stream(body: dict):
    import httpx

    messages = body.get("messages") or []
    prompt = (body.get("prompt") or "").strip()
    if not messages and prompt:
        messages = [{"role": "user", "content": prompt}]
    if not messages:
        raise HTTPException(status_code=400, detail="prompt or messages required")

    async def _gen():
        cfg = get_config()
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST",
                    f"{cfg.ollama_url}/api/chat",
                    json={"model": cfg.ollama_model, "messages": messages, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("message", {}).get("content", "")
                            if token:
                                yield f"data: {json.dumps({'token': token})}\n\n"
                        except Exception:
                            pass
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── Context compactor stats ───────────────────────────────────────────────────

@router.get("/api/context/stats")
async def context_compactor_stats():
    from core.context_compactor import get_stats
    return get_stats()


@router.post("/api/context/stats/reset")
async def reset_context_stats():
    from core.context_compactor import _STATS
    _STATS["compactions"] = 0
    _STATS["messages_summarised"] = 0
    _STATS["messages_kept"] = 0
    _STATS["failures"] = 0
    return {"ok": True}


# ── Workflow dry-run ──────────────────────────────────────────────────────────

@router.post("/api/workflows/{name}/dryrun")
async def dry_run_workflow_endpoint(name: str):
    from agents.workflow_store import dry_run_workflow
    try:
        results = await dry_run_workflow(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"name": name, "dry_run": True, "steps": results}


# ── MCP health monitor ────────────────────────────────────────────────────────

import collections as _collections_mcp
_MCP_HEALTH: dict[str, dict] = {}


async def _ping_mcp_server(name: str) -> dict:
    import time as _time
    from core.mcp_client import _servers, _disabled_servers
    if name in _disabled_servers:
        return {"name": name, "status": "disabled", "latency_ms": None, "last_error": None, "checked_at": _time.time()}
    srv = _servers.get(name)
    if srv is None:
        return {"name": name, "status": "failed", "latency_ms": None, "last_error": "not connected", "checked_at": _time.time()}
    t0 = _time.monotonic()
    try:
        await asyncio.wait_for(srv.session.list_tools(), timeout=5.0)
        latency_ms = int((_time.monotonic() - t0) * 1000)
        return {"name": name, "status": "ok", "latency_ms": latency_ms, "last_error": None, "checked_at": _time.time()}
    except Exception as exc:
        return {"name": name, "status": "error", "latency_ms": None, "last_error": str(exc), "checked_at": _time.time()}


async def run_mcp_health_monitor() -> None:
    while True:
        try:
            from core.mcp_client import get_mcp_status
            for srv in get_mcp_status():
                name = srv["name"]
                result = await _ping_mcp_server(name)
                _MCP_HEALTH[name] = result
        except Exception:
            pass
        await asyncio.sleep(60)


@router.get("/api/mcp/health")
async def mcp_health():
    from core.mcp_client import get_mcp_status
    servers = get_mcp_status()
    health = []
    for srv in servers:
        name = srv["name"]
        h = _MCP_HEALTH.get(name, {
            "name": name, "status": "unknown", "latency_ms": None,
            "last_error": None, "checked_at": None,
        })
        health.append({**h, "healthy": srv.get("healthy", False)})
    return {"servers": health, "total": len(health)}


@router.post("/api/mcp/health/ping")
async def ping_mcp_servers():
    from core.mcp_client import get_mcp_status
    servers = get_mcp_status()
    results = []
    for srv in servers:
        name = srv["name"]
        result = await _ping_mcp_server(name)
        _MCP_HEALTH[name] = result
        results.append(result)
    return {"servers": results}


# ── Wake phrase samples ───────────────────────────────────────────────────────

def _wake_samples_dir() -> pathlib.Path:
    from core.config import get_config
    return pathlib.Path(get_config().memory_dir) / "wake_samples"


@router.get("/api/wake/phrases")
async def list_wake_phrases():
    d = _wake_samples_dir()
    if not d.exists():
        return {"phrases": []}
    phrases = []
    for p in sorted(d.iterdir()):
        if p.is_dir():
            samples = list(p.glob("*.wav"))
            phrases.append({"phrase": p.name, "sample_count": len(samples), "path": str(p)})
    return {"phrases": phrases}


@router.post("/api/wake/phrases/{phrase}/samples")
async def upload_wake_sample(phrase: str, file: UploadFile = File(...)):
    import re
    safe = re.sub(r"[^\w\-]", "_", phrase.strip())[:40]
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid phrase name")
    d = _wake_samples_dir() / safe
    d.mkdir(parents=True, exist_ok=True)
    idx = len(list(d.glob("*.wav"))) + 1
    dest = d / f"sample_{idx:03d}.wav"
    content = await file.read()
    dest.write_bytes(content)
    return {"ok": True, "phrase": safe, "sample": dest.name, "total_samples": idx}


@router.delete("/api/wake/phrases/{phrase}")
async def delete_wake_phrase(phrase: str):
    import shutil as _shutil
    import re
    safe = re.sub(r"[^\w\-]", "_", phrase.strip())[:40]
    d = _wake_samples_dir() / safe
    if not d.exists():
        raise HTTPException(status_code=404, detail="Phrase not found")
    await asyncio.to_thread(_shutil.rmtree, str(d))
    return {"ok": True}


@router.get("/api/wake/phrases/{phrase}/samples")
async def list_wake_samples(phrase: str):
    import re
    safe = re.sub(r"[^\w\-]", "_", phrase.strip())[:40]
    d = _wake_samples_dir() / safe
    if not d.exists():
        return {"phrase": safe, "samples": []}
    samples = [{"name": p.name, "size": p.stat().st_size} for p in sorted(d.glob("*.wav"))]
    return {"phrase": safe, "samples": samples}


# ── Scheduled messages ────────────────────────────────────────────────────────

@router.get("/api/scheduled/messages")
async def list_scheduled_messages():
    from core.scheduled_msg_store import list_scheduled_messages
    return {"messages": await asyncio.to_thread(list_scheduled_messages)}


@router.post("/api/scheduled/messages")
async def add_scheduled_message(body: dict):
    from core.scheduled_msg_store import add_scheduled_message
    message = (body.get("message") or "").strip()
    fire_at = (body.get("fire_at") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message required")
    if not fire_at:
        raise HTTPException(status_code=400, detail="fire_at (ISO 8601) required")
    msg_id = await asyncio.to_thread(add_scheduled_message, message, fire_at)
    return {"ok": True, "id": msg_id, "fire_at": fire_at}


@router.delete("/api/scheduled/messages/{msg_id}")
async def delete_scheduled_message(msg_id: int):
    from core.scheduled_msg_store import delete_scheduled_message
    deleted = await asyncio.to_thread(delete_scheduled_message, msg_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"ok": True}


# ── Plugin sandbox ────────────────────────────────────────────────────────────

@router.post("/api/modules/sandbox")
async def sandbox_module(body: dict):
    import sys
    import subprocess
    code = (body.get("code") or "").strip()
    timeout = min(int(body.get("timeout", 5)), 30)
    if not code:
        raise HTTPException(status_code=400, detail="code required")
    t0 = asyncio.get_event_loop().time()
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "ok": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Timed out after {timeout}s",
                "duration_ms": int((asyncio.get_event_loop().time() - t0) * 1000),
            }
    except Exception as exc:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": str(exc), "duration_ms": 0}
    duration_ms = int((asyncio.get_event_loop().time() - t0) * 1000)
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace")[:4096],
        "stderr": stderr.decode(errors="replace")[:2048],
        "duration_ms": duration_ms,
    }


# ── System resource alerts ────────────────────────────────────────────────────

_ALERT_LOG: _collections.deque = _collections.deque(maxlen=100)


async def run_resource_alert_loop() -> None:
    while True:
        try:
            from core.config import get_config as _gc
            cfg = _gc()
            if cfg.alerts_enabled:
                import time as _t
                try:
                    import psutil
                    cpu = psutil.cpu_percent(interval=None)
                    ram = psutil.virtual_memory().percent
                    _check = lambda val, thresh, name: (
                        _ALERT_LOG.appendleft({"ts": _t.time(), "resource": name, "value": round(val, 1), "threshold": thresh})
                        or asyncio.ensure_future(events.emit("system_alert", {"resource": name, "value": round(val, 1), "threshold": thresh}))
                    ) if val >= thresh else None
                    _check(cpu, cfg.cpu_alert_threshold, "cpu")
                    _check(ram, cfg.ram_alert_threshold, "ram")
                except ImportError:
                    pass
                try:
                    broker = get_vram_broker()
                    st = broker.status()
                    used = st.get("vram_used_gb", 0) or 0
                    total = st.get("vram_total_gb", 0) or 0
                    if total > 0:
                        pct = (used / total) * 100
                        if pct >= cfg.gpu_alert_threshold:
                            _ALERT_LOG.appendleft({"ts": _t.time(), "resource": "gpu", "value": round(pct, 1), "threshold": cfg.gpu_alert_threshold})
                            await events.emit("system_alert", {"resource": "gpu", "value": round(pct, 1), "threshold": cfg.gpu_alert_threshold})
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(30)


@router.get("/api/alerts/log")
async def get_alert_log(n: int = 50):
    return {"alerts": list(_ALERT_LOG)[:n]}


@router.delete("/api/alerts/log")
async def clear_alert_log():
    _ALERT_LOG.clear()
    return {"ok": True}


@router.get("/api/alerts/config")
async def get_alert_config():
    cfg = get_config()
    return {
        "alerts_enabled": cfg.alerts_enabled,
        "cpu_alert_threshold": cfg.cpu_alert_threshold,
        "ram_alert_threshold": cfg.ram_alert_threshold,
        "gpu_alert_threshold": cfg.gpu_alert_threshold,
    }


@router.post("/api/alerts/config")
async def set_alert_config(body: dict):
    kwargs: dict = {}
    if "alerts_enabled" in body:
        kwargs["alerts_enabled"] = bool(body["alerts_enabled"])
    for key in ("cpu_alert_threshold", "ram_alert_threshold", "gpu_alert_threshold"):
        if key in body:
            val = int(body[key])
            if not (1 <= val <= 100):
                raise HTTPException(status_code=400, detail=f"{key} must be 1-100")
            kwargs[key] = val
    if kwargs:
        await asyncio.to_thread(update_config, **kwargs)
    return {"ok": True}


@router.get("/api/uptime")
async def uptime():
    elapsed = _time_top.time() - _SERVER_START
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = int(elapsed % 60)
    human = f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")
    return {"uptime_seconds": round(elapsed, 1), "human": human, "started_at": _SERVER_START}


@router.get("/api/cache/stats")
async def llm_cache_stats():
    from core.supervisor import _RESPONSE_CACHE, _CACHE_STATS
    cfg = get_config()
    return {
        "enabled": cfg.llm_cache_enabled,
        "size": len(_RESPONSE_CACHE),
        "max": cfg.llm_cache_max,
        "hits": _CACHE_STATS["hits"],
        "misses": _CACHE_STATS["misses"],
        "hit_rate": round(_CACHE_STATS["hits"] / max(_CACHE_STATS["hits"] + _CACHE_STATS["misses"], 1) * 100, 1),
    }


@router.delete("/api/cache")
async def flush_llm_cache():
    from core.supervisor import _RESPONSE_CACHE, _CACHE_STATS
    _RESPONSE_CACHE.clear()
    _CACHE_STATS["hits"] = 0
    _CACHE_STATS["misses"] = 0
    return {"ok": True}


@router.post("/api/cache/toggle")
async def toggle_llm_cache(body: dict):
    enabled = bool(body.get("enabled", not get_config().llm_cache_enabled))
    await asyncio.to_thread(update_config, llm_cache_enabled=enabled)
    return {"ok": True, "enabled": enabled}


@router.post("/api/clips/{filename}/trim")
async def trim_clip(filename: str, body: dict):
    try:
        p = _clip_path(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    if p.suffix.lower() != ".wav":
        raise HTTPException(status_code=400, detail="Only WAV clips can be trimmed")
    start_s = float(body.get("start_s", 0))
    end_s = body.get("end_s")
    if start_s < 0:
        raise HTTPException(status_code=400, detail="start_s must be >= 0")

    def _trim() -> bytes:
        import io
        rate, data = wavfile.read(str(p))
        start_idx = int(start_s * rate)
        end_idx = int(end_s * rate) if end_s is not None else len(data)
        end_idx = min(end_idx, len(data))
        if start_idx >= end_idx:
            raise ValueError("start_s must be less than end_s and clip duration")
        trimmed = data[start_idx:end_idx]
        buf = io.BytesIO()
        wavfile.write(buf, rate, trimmed)
        return buf.getvalue()

    try:
        wav_bytes = await asyncio.to_thread(_trim)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    from fastapi.responses import Response
    stem = p.stem
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": f'attachment; filename="{stem}_trimmed.wav"'},
    )


@router.get("/api/config/history")
async def config_history(n: int = 50):
    return {"history": list(_CONFIG_HISTORY)[:n]}


@router.delete("/api/config/history")
async def clear_config_history():
    _CONFIG_HISTORY.clear()
    return {"ok": True}


@router.get("/api/config/presets")
async def list_config_presets():
    from core.preset_store import list_presets
    names = await asyncio.to_thread(list_presets)
    return {"presets": names}


@router.post("/api/config/presets/{name}/apply")
async def apply_config_preset(name: str):
    from core.preset_store import apply_preset
    ok = await asyncio.to_thread(apply_preset, name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Preset {name!r} not found")
    return {"ok": True}


@router.post("/api/config/presets/{name}")
async def save_config_preset(name: str):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    from core.preset_store import save_preset
    await asyncio.to_thread(save_preset, name)
    return {"ok": True, "name": name}


@router.delete("/api/config/presets/{name}")
async def delete_config_preset(name: str):
    from core.preset_store import delete_preset
    ok = await asyncio.to_thread(delete_preset, name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Preset {name!r} not found")
    return {"ok": True}


@router.get("/api/tools/stats")
async def tool_stats():
    result = []
    for agent, s in _TOOL_STATS.items():
        calls = s["calls"]
        avg_latency = round(s["total_latency_ms"] / calls) if calls else 0
        result.append({"agent": agent, "calls": calls, "avg_latency_ms": avg_latency, "errors": s["errors"]})
    result.sort(key=lambda x: x["calls"], reverse=True)
    return {"stats": result}


@router.post("/api/tools/stats/reset")
async def reset_tool_stats():
    _TOOL_STATS.clear()
    return {"ok": True}


@router.get("/api/shortcuts")
async def list_shortcuts():
    from core.shortcut_store import list_shortcuts as _list
    return {"shortcuts": await asyncio.to_thread(_list)}


@router.post("/api/shortcuts")
async def add_shortcut(body: dict):
    keyword = (body.get("keyword") or "").strip()
    message = (body.get("message") or "").strip()
    if not keyword or not message:
        raise HTTPException(status_code=400, detail="keyword and message required")
    from core.shortcut_store import add_shortcut as _add
    shortcut_id = await asyncio.to_thread(_add, keyword, message)
    return {"ok": True, "id": shortcut_id}


@router.delete("/api/shortcuts/{shortcut_id}")
async def delete_shortcut(shortcut_id: int):
    from core.shortcut_store import delete_shortcut as _del
    found = await asyncio.to_thread(_del, shortcut_id)
    if not found:
        raise HTTPException(status_code=404, detail="shortcut not found")
    return {"ok": True}


@router.get("/api/trace/recent")
async def recent_traces(n: int = 50):
    return {"traces": list(_TURN_TRACES)[:n]}


@router.delete("/api/trace/recent")
async def clear_traces():
    _TURN_TRACES.clear()
    return {"ok": True}


import collections as _notif_collections
_NOTIFY_HISTORY: _notif_collections.deque = _notif_collections.deque(maxlen=50)


@router.post("/api/notify")
async def send_notification(body: dict):
    import time
    title = (body.get("title") or "Plia").strip()
    message = (body.get("message") or "").strip()
    urgency = (body.get("urgency") or "normal").strip().lower()
    if urgency not in ("low", "normal", "critical"):
        urgency = "normal"
    if not message:
        raise HTTPException(status_code=422, detail="message required")

    proc = await asyncio.create_subprocess_exec(
        "notify-send", "-u", urgency, title, message,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    entry = {"ts": time.time(), "title": title, "message": message, "urgency": urgency, "ok": proc.returncode == 0}
    if proc.returncode != 0:
        entry["error"] = stderr.decode().strip()
    _NOTIFY_HISTORY.appendleft(entry)
    return entry


@router.get("/api/notify/history")
async def notify_history(n: int = 20):
    return {"history": list(_NOTIFY_HISTORY)[:n]}


@router.get("/api/benchmark/chart")
async def benchmark_chart_data(n: int = 50):
    history = list(_BENCH_HISTORY)[:n]
    history.reverse()
    return {
        "labels": [h["ts"] for h in history],
        "latency_ms": [h["latency_ms"] for h in history],
        "tokens_per_sec": [h["tokens_per_sec"] for h in history],
        "models": [h["model"] for h in history],
    }


# ── Clipboard ────────────────────────────────────────────────────────────────

async def _run_clip_proc(*args, stdin: bytes | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate(input=stdin)
    return proc.returncode, stdout.decode(errors="replace").strip()


@router.get("/api/clipboard")
async def read_clipboard():
    rc, text = await _run_clip_proc("xclip", "-o", "-selection", "clipboard")
    if rc != 0:
        rc, text = await _run_clip_proc("xsel", "--clipboard", "--output")
    if rc != 0:
        raise HTTPException(status_code=503, detail="No clipboard tool available (install xclip or xsel)")
    return {"text": text}


@router.post("/api/clipboard")
async def write_clipboard(body: dict):
    text = body.get("text", "")
    encoded = text.encode()
    rc, _ = await _run_clip_proc("xclip", "-i", "-selection", "clipboard", stdin=encoded)
    if rc != 0:
        rc, _ = await _run_clip_proc("xsel", "--clipboard", "--input", stdin=encoded)
    if rc != 0:
        raise HTTPException(status_code=503, detail="No clipboard tool available (install xclip or xsel)")
    return {"ok": True, "length": len(text)}


# ── Watchdog ──────────────────────────────────────────────────────────────────

_WATCHDOG_REGISTRY: dict = {}


def register_watchdog_task(name: str, factory) -> None:
    _WATCHDOG_REGISTRY[name] = {"factory": factory, "task": None}


def _watchdog_set_task(name: str, task) -> None:
    if name in _WATCHDOG_REGISTRY:
        _WATCHDOG_REGISTRY[name]["task"] = task


@router.get("/api/watchdog")
async def get_watchdog():
    all_tasks = list(asyncio.all_tasks())
    task_list = [
        {"name": t.get_name(), "done": t.done()}
        for t in sorted(all_tasks, key=lambda t: t.get_name())
    ]
    named = {
        name: {"running": bool(info.get("task") and not info["task"].done())}
        for name, info in _WATCHDOG_REGISTRY.items()
    }
    return {"tasks": task_list, "total": len(all_tasks), "named": named}


@router.post("/api/watchdog/restart/{name}")
async def restart_watchdog_task(name: str):
    if name not in _WATCHDOG_REGISTRY:
        raise HTTPException(status_code=404, detail=f"No registered task '{name}'")
    info = _WATCHDOG_REGISTRY[name]
    old = info.get("task")
    if old and not old.done():
        old.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(old), timeout=2.0)
        except (asyncio.CancelledError, Exception):
            pass
    new_task = asyncio.create_task(info["factory"]())
    _WATCHDOG_REGISTRY[name]["task"] = new_task
    return {"ok": True, "name": name}


# ── Screenshot ────────────────────────────────────────────────────────────────

@router.post("/api/screenshot")
async def take_screenshot():
    import base64 as _b64
    import tempfile as _tmp
    import os as _os
    with _tmp.NamedTemporaryFile(suffix=".png", delete=False) as f:
        fname = f.name
    try:
        cmds = [
            ["scrot", fname],
            ["gnome-screenshot", "-f", fname],
            ["import", "-window", "root", fname],
        ]
        for cmd in cmds:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0 and _os.path.exists(fname) and _os.path.getsize(fname) > 0:
                break
        else:
            raise HTTPException(status_code=503, detail="No screenshot tool available (install scrot or gnome-screenshot)")
        data = Path(fname).read_bytes()
        return {"image": _b64.b64encode(data).decode(), "size": len(data)}
    finally:
        try:
            _os.unlink(fname)
        except Exception:
            pass


# ── Shell runner ──────────────────────────────────────────────────────────────

import collections as _shell_cols

_SHELL_HISTORY: _shell_cols.deque = _shell_cols.deque(maxlen=50)


@router.post("/api/shell")
async def run_shell_command(body: dict):
    import time as _t
    from core.shell_guard import check_command, ShellBlockedError
    cmd = (body.get("command") or "").strip()
    timeout = min(max(int(body.get("timeout", 10)), 1), 30)
    if not cmd:
        raise HTTPException(status_code=422, detail="command required")
    try:
        check_command(cmd)
    except ShellBlockedError as _e:
        raise HTTPException(status_code=422, detail=str(_e))
    t0 = _t.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            entry = {
                "command": cmd, "stdout": "", "stderr": "Timed out",
                "returncode": -1, "elapsed_ms": int((_t.time() - t0) * 1000),
            }
            _SHELL_HISTORY.appendleft(entry)
            return entry
        entry = {
            "command": cmd,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "returncode": proc.returncode,
            "elapsed_ms": int((_t.time() - t0) * 1000),
        }
        _SHELL_HISTORY.appendleft(entry)
        return entry
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/shell/history")
async def shell_history():
    return {"history": list(_SHELL_HISTORY)}


# ── HTTP probe ────────────────────────────────────────────────────────────────

import collections as _probe_cols

_PROBE_HISTORY: _probe_cols.deque = _probe_cols.deque(maxlen=100)


@router.post("/api/probe")
async def http_probe(body: dict):
    import httpx as _httpx
    import time as _t
    url = (body.get("url") or "").strip()
    timeout = min(float(body.get("timeout", 5.0)), 30.0)
    method = (body.get("method") or "GET").upper()
    if not url:
        raise HTTPException(status_code=422, detail="url required")
    t0 = _t.time()
    try:
        async with _httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.request(method, url)
        elapsed_ms = int((_t.time() - t0) * 1000)
        entry = {
            "url": url, "method": method, "status": resp.status_code,
            "elapsed_ms": elapsed_ms, "ok": resp.is_success, "error": None,
        }
    except Exception as exc:
        elapsed_ms = int((_t.time() - t0) * 1000)
        entry = {
            "url": url, "method": method, "status": None,
            "elapsed_ms": elapsed_ms, "ok": False, "error": str(exc),
        }
    _PROBE_HISTORY.appendleft(entry)
    return entry


@router.get("/api/probe/history")
async def probe_history():
    return {"history": list(_PROBE_HISTORY)}


# ── Docker status ─────────────────────────────────────────────────────────────

async def _docker_action(container_id: str, action: str) -> dict:
    safe_id = re.sub(r"[^a-zA-Z0-9_.\-]", "", container_id)
    if not safe_id:
        raise HTTPException(status_code=400, detail="Invalid container id")
    proc = await asyncio.create_subprocess_exec(
        "docker", action, safe_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=stderr.decode(errors="replace").strip())
    return {"ok": True, "action": action, "container": safe_id}


@router.get("/api/docker")
async def docker_status():
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-a", "--format", "{{json .}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail=f"Docker unavailable: {stderr.decode(errors='replace').strip()}",
        )
    containers = []
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                containers.append(json.loads(line))
            except Exception:
                pass
    return {"containers": containers, "total": len(containers)}


@router.post("/api/docker/{container_id}/restart")
async def docker_restart(container_id: str):
    return await _docker_action(container_id, "restart")


@router.post("/api/docker/{container_id}/stop")
async def docker_stop(container_id: str):
    return await _docker_action(container_id, "stop")


@router.post("/api/docker/{container_id}/start")
async def docker_start(container_id: str):
    return await _docker_action(container_id, "start")


# ── Systemd services ──────────────────────────────────────────────────────────

async def _systemctl_action(name: str, action: str) -> dict:
    safe_name = re.sub(r"[^a-zA-Z0-9@._\-]", "", name)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid service name")
    proc = await asyncio.create_subprocess_exec(
        "systemctl", action, safe_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=stderr.decode(errors="replace").strip())
    return {"ok": True, "action": action, "service": safe_name}


@router.get("/api/services")
async def list_services(filter: str = ""):
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "list-units", "--no-pager", "--no-legend",
        "--type=service", "--all", "--output=json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail=f"systemctl unavailable: {stderr.decode(errors='replace').strip()}",
        )
    try:
        units = json.loads(stdout.decode(errors="replace"))
    except Exception:
        units = []
    if filter:
        fl = filter.lower()
        units = [u for u in units if fl in (u.get("unit", "") + u.get("description", "")).lower()]
    return {"units": units, "total": len(units)}


@router.post("/api/services/{name}/restart")
async def service_restart(name: str):
    return await _systemctl_action(name, "restart")


@router.post("/api/services/{name}/start")
async def service_start(name: str):
    return await _systemctl_action(name, "start")


@router.post("/api/services/{name}/stop")
async def service_stop(name: str):
    return await _systemctl_action(name, "stop")


# ── QR code ───────────────────────────────────────────────────────────────────

@router.post("/api/qr")
async def generate_qr(body: dict):
    import base64 as _b64
    import os as _os
    import tempfile as _tmp
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text required")
    size = min(max(int(body.get("size", 8)), 1), 50)

    with _tmp.NamedTemporaryFile(suffix=".png", delete=False) as f:
        fname = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "qrencode", "-o", fname, "-s", str(size), "--", text,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0 and _os.path.getsize(fname) > 0:
            data = Path(fname).read_bytes()
            return {"image": _b64.b64encode(data).decode(), "size": len(data)}
    finally:
        try:
            _os.unlink(fname)
        except Exception:
            pass

    try:
        import qrcode as _qrcode
        import io as _io
        qr = _qrcode.QRCode(box_size=size)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image()
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        return {"image": _b64.b64encode(data).decode(), "size": len(data)}
    except ImportError:
        pass

    raise HTTPException(
        status_code=503,
        detail="No QR tool available (install qrencode or: pip install 'qrcode[pil]')",
    )


# ── File watcher (SSE) ────────────────────────────────────────────────────────

_WATCH_ALLOWED_ROOTS = ("/tmp", "/home", "/var/log", "/var/tmp")


@router.get("/api/watch")
async def file_watch_sse(path: str = "/tmp", request: Request = None):
    import os as _os
    real = _os.path.realpath(path)
    if not any(real == r or real.startswith(r + "/") for r in _WATCH_ALLOWED_ROOTS):
        async def _deny():
            yield f"data: {json.dumps({'error': 'Path not in allowed roots: ' + ', '.join(_WATCH_ALLOWED_ROOTS)})}\n\n"
        return StreamingResponse(_deny(), media_type="text/event-stream")
    async def event_gen():
        try:
            proc = await asyncio.create_subprocess_exec(
                "inotifywait", "-m", "-r", "--format", "%e\t%w%f",
                "-e", "create,delete,modify,moved_to,moved_from",
                real,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            yield f"data: {json.dumps({'error': 'inotifywait not found; install inotify-tools'})}\n\n"
            return
        try:
            while True:
                if request and await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'ping': True})}\n\n"
                    continue
                if not line:
                    break
                parts = line.decode(errors="replace").strip().split("\t", 1)
                evt = parts[0] if parts else ""
                fpath = parts[1] if len(parts) > 1 else ""
                yield f"data: {json.dumps({'event': evt, 'path': fpath})}\n\n"
        finally:
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ── Text diff ─────────────────────────────────────────────────────────────────

@router.post("/api/diff")
async def text_diff(body: dict):
    import difflib
    a = body.get("a") or ""
    b = body.get("b") or ""
    fname_a = body.get("filename_a", "a")
    fname_b = body.get("filename_b", "b")
    a_lines = a.splitlines(keepends=True)
    b_lines = b.splitlines(keepends=True)
    raw = list(difflib.unified_diff(a_lines, b_lines, fromfile=fname_a, tofile=fname_b))
    lines = []
    for line in raw:
        if line.startswith("+") and not line.startswith("+++"):
            lines.append({"type": "add", "text": line[1:]})
        elif line.startswith("-") and not line.startswith("---"):
            lines.append({"type": "remove", "text": line[1:]})
        elif line.startswith("@@"):
            lines.append({"type": "header", "text": line})
        else:
            lines.append({"type": "context", "text": line[1:] if line.startswith(" ") else line})
    return {
        "unified": "".join(raw),
        "lines": lines,
        "added": sum(1 for l in lines if l["type"] == "add"),
        "removed": sum(1 for l in lines if l["type"] == "remove"),
    }


# ── Password generator ───────────────────────────────────────────────────────

def _relative_time(ts: float) -> str:
    import time as _t
    diff = _t.time() - ts
    abs_diff = abs(diff)
    suffix = "ago" if diff > 0 else "from now"
    if abs_diff < 60:
        return f"{int(abs_diff)}s {suffix}"
    if abs_diff < 3600:
        return f"{int(abs_diff / 60)}m {suffix}"
    if abs_diff < 86400:
        return f"{int(abs_diff / 3600)}h {suffix}"
    return f"{int(abs_diff / 86400)}d {suffix}"


@router.post("/api/password")
async def generate_password(body: dict):
    import secrets
    import string
    import math
    length = min(max(int(body.get("length", 16)), 4), 128)
    count = min(max(int(body.get("count", 1)), 1), 20)
    charset = ""
    if body.get("upper", True):
        charset += string.ascii_uppercase
    if body.get("lower", True):
        charset += string.ascii_lowercase
    if body.get("digits", True):
        charset += string.digits
    if body.get("symbols", True):
        charset += "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not charset:
        raise HTTPException(status_code=422, detail="At least one character class required")
    passwords = ["".join(secrets.choice(charset) for _ in range(length)) for _ in range(count)]
    entropy = round(length * math.log2(len(charset)), 1)
    return {"passwords": passwords, "length": length, "charset_size": len(charset), "entropy_bits": entropy}


# ── Timestamp converter ───────────────────────────────────────────────────────

@router.post("/api/timestamp")
async def convert_timestamp(body: dict):
    from datetime import datetime, timezone
    import time as _t
    value = body.get("value")
    if value is None:
        ts = _t.time()
    elif isinstance(value, (int, float)):
        ts = float(value)
    elif isinstance(value, str):
        try:
            ts = float(value)
        except ValueError:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                ts = dt.timestamp()
            except Exception:
                raise HTTPException(status_code=422, detail=f"Cannot parse: {value!r}")
    else:
        raise HTTPException(status_code=422, detail="value must be number or ISO string")
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    dt_local = datetime.fromtimestamp(ts)
    return {
        "unix": ts,
        "unix_ms": int(ts * 1000),
        "iso_utc": dt_utc.isoformat(),
        "iso_local": dt_local.isoformat(),
        "human_utc": dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "human_local": dt_local.strftime("%Y-%m-%d %H:%M:%S"),
        "relative": _relative_time(ts),
    }


# ── JSON formatter ────────────────────────────────────────────────────────────

def _count_keys(obj: object, n: int = 0) -> int:
    if isinstance(obj, dict):
        n += len(obj)
        for v in obj.values():
            n = _count_keys(v, n)
    elif isinstance(obj, list):
        for item in obj:
            n = _count_keys(item, n)
    return n


@router.post("/api/json/format")
async def json_format(body: dict):
    import json as _j
    raw = body.get("json", "")
    indent = min(max(int(body.get("indent", 2)), 1), 8)
    try:
        parsed = _j.loads(raw)
        formatted = _j.dumps(parsed, indent=indent, ensure_ascii=False)
        return {"ok": True, "result": formatted, "keys": _count_keys(parsed)}
    except _j.JSONDecodeError as e:
        return {"ok": False, "error": str(e), "line": e.lineno, "col": e.colno, "result": None}


@router.post("/api/json/minify")
async def json_minify(body: dict):
    import json as _j
    raw = body.get("json", "")
    try:
        parsed = _j.loads(raw)
        minified = _j.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
        return {"ok": True, "result": minified, "saved": len(raw) - len(minified)}
    except _j.JSONDecodeError as e:
        return {"ok": False, "error": str(e), "result": None}


# ── Network interfaces ────────────────────────────────────────────────────────

@router.get("/api/network/interfaces")
async def network_interfaces():
    proc = await asyncio.create_subprocess_exec(
        "ip", "-j", "addr",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            status_code=503,
            detail=f"ip command failed: {stderr.decode(errors='replace').strip()}",
        )
    try:
        interfaces = json.loads(stdout.decode(errors="replace"))
    except Exception:
        interfaces = []
    return {"interfaces": interfaces, "total": len(interfaces)}


# ── Encoder / decoder ────────────────────────────────────────────────────────

@router.post("/api/encode/{scheme}")
async def encode_text(scheme: str, body: dict):
    import base64 as _b64
    text = body.get("text", "")
    data = text.encode("utf-8")
    if scheme == "base64":
        return {"result": _b64.b64encode(data).decode()}
    if scheme == "base64url":
        return {"result": _b64.urlsafe_b64encode(data).decode()}
    if scheme == "hex":
        return {"result": data.hex()}
    raise HTTPException(status_code=400, detail=f"Unknown scheme '{scheme}'; use base64, base64url, hex")


@router.post("/api/decode/{scheme}")
async def decode_text(scheme: str, body: dict):
    import base64 as _b64
    text = (body.get("text") or "").strip()
    try:
        if scheme == "base64":
            result = _b64.b64decode(text).decode("utf-8", errors="replace")
        elif scheme == "base64url":
            result = _b64.urlsafe_b64decode(text + "==").decode("utf-8", errors="replace")
        elif scheme == "hex":
            result = bytes.fromhex(text).decode("utf-8", errors="replace")
        else:
            raise HTTPException(status_code=400, detail=f"Unknown scheme '{scheme}'")
        return {"result": result}
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Hash calculator ───────────────────────────────────────────────────────────

@router.post("/api/hash")
async def compute_hash(body: dict):
    import hashlib
    text = body.get("text", "")
    data = text.encode("utf-8")
    return {
        "md5":    hashlib.md5(data).hexdigest(),
        "sha1":   hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha512": hashlib.sha512(data).hexdigest(),
        "length": len(data),
    }


# ── Regex tester ──────────────────────────────────────────────────────────────

@router.post("/api/regex")
async def test_regex(body: dict):
    import re as _re
    pattern = body.get("pattern", "")
    text = body.get("text", "")
    flags_raw = body.get("flags", "")
    if not pattern:
        raise HTTPException(status_code=422, detail="pattern required")
    flags = 0
    if "i" in flags_raw:
        flags |= _re.IGNORECASE
    if "m" in flags_raw:
        flags |= _re.MULTILINE
    if "s" in flags_raw:
        flags |= _re.DOTALL
    try:
        compiled = _re.compile(pattern, flags)
    except _re.error as exc:
        return {"ok": False, "error": str(exc), "matches": [], "count": 0}
    matches = []
    for m in compiled.finditer(text):
        matches.append({
            "match": m.group(0),
            "start": m.start(),
            "end": m.end(),
            "groups": list(m.groups()),
        })
    return {"ok": True, "error": None, "matches": matches, "count": len(matches)}


# ── Disk usage ────────────────────────────────────────────────────────────────

@router.get("/api/disk")
async def disk_usage():
    proc = await asyncio.create_subprocess_exec(
        "df", "-h", "--output=source,fstype,size,used,avail,pcent,target",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=503, detail=stderr.decode(errors="replace").strip())
    lines = stdout.decode(errors="replace").splitlines()
    partitions = []
    for line in lines[1:]:
        # split with maxsplit=6 so mount points containing spaces stay intact in parts[6]
        parts = line.split(None, 6)
        if len(parts) >= 7:
            pct_str = parts[5].rstrip("%")
            try:
                pct = int(pct_str)
            except ValueError:
                pct = 0
            partitions.append({
                "source": parts[0],
                "fstype": parts[1],
                "size": parts[2],
                "used": parts[3],
                "avail": parts[4],
                "percent": pct,
                "target": parts[6],
            })
    return {"partitions": partitions, "total": len(partitions)}


# ── Color converter ───────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple:
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    lf = (mx + mn) / 2
    if mx == mn:
        hf = sf = 0.0
    else:
        d = mx - mn
        sf = d / (2 - mx - mn) if lf > 0.5 else d / (mx + mn)
        if mx == rf:
            hf = ((gf - bf) / d + (6 if gf < bf else 0)) / 6
        elif mx == gf:
            hf = ((bf - rf) / d + 2) / 6
        else:
            hf = ((rf - gf) / d + 4) / 6
    return round(hf * 360), round(sf * 100), round(lf * 100)


def _hsl_to_rgb(h: float, s: float, lv: float) -> tuple:
    h, s, lv = h / 360, s / 100, lv / 100
    if s == 0:
        v = round(lv * 255)
        return v, v, v

    def _h2rgb(p: float, q: float, t: float) -> float:
        t = t % 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 0.5:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = lv * (1 + s) if lv < 0.5 else lv + s - lv * s
    p = 2 * lv - q
    return round(_h2rgb(p, q, h + 1/3) * 255), round(_h2rgb(p, q, h) * 255), round(_h2rgb(p, q, h - 1/3) * 255)


@router.post("/api/color")
async def color_convert(body: dict):
    import re as _re
    value = str(body.get("value", "")).strip()
    if not value:
        raise HTTPException(status_code=422, detail="value required")
    vl = value.lower()
    if _re.match(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", value):
        r, g, b = _hex_to_rgb(value)
    elif vl.startswith("rgba") or vl.startswith("hsla"):
        raise HTTPException(status_code=422, detail="rgba/hsla not supported; use rgb/hsl")
    elif vl.startswith("rgb"):
        nums = _re.findall(r"\d+", value)
        if len(nums) < 3:
            raise HTTPException(status_code=422, detail="Invalid rgb value")
        r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
    elif vl.startswith("hsl"):
        nums = _re.findall(r"[\d.]+", value)
        if len(nums) < 3:
            raise HTTPException(status_code=422, detail="Invalid hsl value")
        r, g, b = _hsl_to_rgb(float(nums[0]), float(nums[1]), float(nums[2]))
    else:
        raise HTTPException(status_code=422, detail=f"Cannot parse color: {value!r}")
    r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    hx = f"#{r:02x}{g:02x}{b:02x}"
    hs, ss, ls = _rgb_to_hsl(r, g, b)
    return {
        "hex": hx,
        "hex_upper": hx.upper(),
        "rgb": f"rgb({r}, {g}, {b})",
        "rgb_values": [r, g, b],
        "hsl": f"hsl({hs}, {ss}%, {ls}%)",
        "hsl_values": [hs, ss, ls],
        "luminance": round(0.2126 * r / 255 + 0.7152 * g / 255 + 0.0722 * b / 255, 3),
    }


# ── UUID generator ────────────────────────────────────────────────────────────

@router.post("/api/uuid")
async def generate_uuid(body: dict):
    import uuid as _uuid
    version = int(body.get("version", 4))
    count = min(max(int(body.get("count", 5)), 1), 50)
    upper = bool(body.get("upper", False))
    if version not in (1, 4):
        raise HTTPException(status_code=422, detail="version must be 1 or 4")
    fn = _uuid.uuid1 if version == 1 else _uuid.uuid4
    uuids = [(str(fn()).upper() if upper else str(fn())) for _ in range(count)]
    return {"uuids": uuids, "version": version, "count": count}


# ── Markdown renderer ─────────────────────────────────────────────────────────

@router.post("/api/markdown")
async def render_markdown(body: dict):
    import html as _html
    text = body.get("text", "")
    try:
        import markdown as _md
        html_out = _md.markdown(text, extensions=["fenced_code", "tables"])
        return {"html": html_out, "length": len(text), "engine": "markdown"}
    except ImportError:
        pass
    try:
        import markdown2 as _md2
        html_out = _md2.markdown(text, extras=["fenced-code-blocks", "tables"])
        return {"html": html_out, "length": len(text), "engine": "markdown2"}
    except ImportError:
        pass
    lines = [f"<p>{_html.escape(line)}</p>" for line in text.splitlines()]
    return {"html": "\n".join(lines), "length": len(text), "engine": "fallback"}


# ── CSV viewer ────────────────────────────────────────────────────────────────

@router.post("/api/csv/parse")
async def csv_parse(body: dict):
    import csv
    import io
    text = body.get("text", "")
    delimiter = (body.get("delimiter") or ",")[:1] or ","
    has_header = bool(body.get("header", True))
    max_rows = min(int(body.get("max_rows", 1000)), 5000)
    if not text:
        return {"headers": [], "rows": [], "total": 0, "columns": 0}
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    all_rows = list(reader)[: max_rows + (1 if has_header else 0)]
    if has_header and all_rows:
        headers, rows = all_rows[0], all_rows[1:]
    else:
        headers = [f"col{i}" for i in range(len(all_rows[0]) if all_rows else 0)]
        rows = all_rows
    return {"headers": headers, "rows": rows, "total": len(rows), "columns": len(headers)}


# ── JWT decoder ───────────────────────────────────────────────────────────────

@router.post("/api/jwt/decode")
async def jwt_decode(body: dict):
    import base64
    import json as _json

    token = str(body.get("token", "")).strip()
    if not token:
        raise HTTPException(status_code=422, detail="token required")
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=422, detail="JWT must have 3 parts")

    def _b64d(s: str) -> dict:
        pad = (-len(s)) % 4
        try:
            return _json.loads(base64.urlsafe_b64decode(s + "=" * pad).decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid JWT segment: {exc}") from exc

    header = _b64d(parts[0])
    payload = _b64d(parts[1])
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="JWT payload must be a JSON object")

    import time as _time
    now = _time.time()
    exp = payload.get("exp")
    iat = payload.get("iat")
    nbf = payload.get("nbf")
    expired = exp is not None and now > exp
    return {
        "header": header,
        "payload": payload,
        "signature": parts[2],
        "exp_iso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(exp)) if exp is not None else None,
        "iat_iso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(iat)) if iat is not None else None,
        "nbf_iso": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(nbf)) if nbf is not None else None,
        "expired": expired,
        "seconds_until_exp": round(exp - now) if exp is not None else None,
    }


# ── IP / CIDR calculator ──────────────────────────────────────────────────────

@router.post("/api/ip/calc")
async def ip_calc(body: dict):
    import ipaddress

    value = str(body.get("value", "")).strip()
    if not value:
        raise HTTPException(status_code=422, detail="value required")
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if net.prefixlen < 8:
        raise HTTPException(status_code=422, detail="Prefix too large (minimum /8); use a more specific range")
    total_hosts = net.num_addresses
    # IPv4 /31 and /32 have no "usable" hosts in the traditional sense
    usable = max(total_hosts - 2, 0) if net.version == 4 and total_hosts > 2 else total_hosts
    na = net.network_address
    ba = net.broadcast_address if net.version == 4 else None
    first_host = str(na + 1) if total_hosts > 2 else (str(na) if total_hosts else None)
    last_host = str(ba - 1) if (ba and total_hosts > 2) else (str(na) if total_hosts == 1 else None)
    return {
        "network": str(na),
        "broadcast": str(ba) if ba else None,
        "mask": str(net.netmask) if net.version == 4 else None,
        "prefix": net.prefixlen,
        "version": net.version,
        "total_addresses": total_hosts,
        "usable_hosts": usable,
        "first_host": first_host,
        "last_host": last_host,
        "cidr": str(net),
        "is_private": net.is_private,
        "is_loopback": net.is_loopback,
        "is_multicast": net.is_multicast,
    }


# ── Process list ──────────────────────────────────────────────────────────────

@router.get("/api/processes")
async def list_processes(sort: str = "cpu", limit: int = 25):
    sort = sort if sort in ("cpu", "mem") else "cpu"
    limit = min(max(int(limit), 1), 200)
    col_map = {"cpu": "%cpu", "mem": "%mem"}
    sort_key = col_map[sort]

    proc = await asyncio.create_subprocess_exec(
        "ps", "aux", "--no-headers",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=503, detail="ps failed")

    rows = []
    for line in stdout.decode(errors="replace").splitlines():
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        try:
            rows.append({
                "user": parts[0],
                "pid": int(parts[1]),
                "cpu": float(parts[2]),
                "mem": float(parts[3]),
                "vsz": int(parts[4]),
                "rss": int(parts[5]),
                "stat": parts[7],
                "command": parts[10],
            })
        except (ValueError, IndexError):
            continue

    rows.sort(key=lambda r: r[sort], reverse=True)
    return {"processes": rows[:limit], "total": len(rows), "sort": sort}


@router.post("/api/processes/{pid}/kill")
async def kill_process(pid: int, body: dict):
    import re as _re
    if pid < 2:
        raise HTTPException(status_code=422, detail="PID must be >= 2")
    signal = str(body.get("signal", "TERM"))
    if not _re.match(r"^[A-Z0-9]+$", signal):
        raise HTTPException(status_code=422, detail="invalid signal")
    proc = await asyncio.create_subprocess_exec(
        "kill", f"-{signal}", str(pid),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(status_code=400, detail=stderr.decode(errors="replace").strip())
    return {"killed": pid, "signal": signal}


# ── URL parser ────────────────────────────────────────────────────────────────

@router.post("/api/url/parse")
async def url_parse(body: dict):
    from urllib.parse import urlparse, parse_qs, unquote, quote

    raw = str(body.get("url", "")).strip()
    if not raw:
        raise HTTPException(status_code=422, detail="url required")
    if "://" not in raw and not raw.startswith("//"):
        raw = "https://" + raw
    try:
        p = urlparse(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    params = parse_qs(p.query, keep_blank_values=True)
    params_flat = {k: v[0] if len(v) == 1 else v for k, v in params.items()}
    return {
        "scheme": p.scheme,
        "host": p.hostname,
        "port": p.port,
        "path": p.path,
        "query": p.query,
        "fragment": p.fragment,
        "username": p.username,
        "password": p.password,
        "params": params_flat,
        "decoded_path": unquote(p.path),
        "encoded_url": quote(raw, safe=":/?#[]@!$&'()*+,;=%"),
        "origin": f"{p.scheme}://{p.netloc}" if p.netloc else None,
    }


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
