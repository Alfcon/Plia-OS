# Plia-OS Design Spec
**Date:** 2026-06-05
**Status:** Approved

---

## Overview

Plia-OS is a local AI voice assistant for Linux, built around a FastAPI core that acts as the Master Control Program (MCP). It listens for a wake word, transcribes speech locally, reasons with a local LLM (Ollama), calls registered module tools, and responds with a fully customisable synthesised voice. Functionality is extended by dropping Python module files into a `modules/` directory. A web dashboard provides live visibility and voice configuration.

---

## Architecture

```
plia-os/
├── core/
│   ├── main.py            # FastAPI app entry point
│   ├── registry.py        # MCP tool registry
│   ├── agent.py           # Ollama LLM agent + tool-call orchestration
│   └── config.py          # Settings (model, voices, ports, wake word)
├── voice/
│   ├── pipeline.py        # Pipecat pipeline (wake → STT → LLM → TTS)
│   ├── wake.py            # OpenWakeWord detector
│   ├── stt.py             # Faster-Whisper STT processor
│   └── tts.py             # Chatterbox / Kokoro TTS (switchable)
├── modules/               # Drop-in feature modules
│   └── example_module.py
├── dashboard/
│   ├── server.py          # FastAPI routes + WebSocket
│   └── static/            # HTMX-based web UI
├── tests/
└── pyproject.toml
```

**Startup sequence:**
1. FastAPI starts, loads all files from `modules/` (failures are skipped with a warning)
2. Pipecat voice pipeline starts as an asyncio background task
3. Web dashboard becomes available at `http://localhost:8000`
4. System enters armed state — wake word detection active

---

## Components

### Core — FastAPI App (`core/`)

- Single process, single port (`8000` by default)
- Owns the MCP tool registry, the Ollama agent, and the web dashboard
- Provides a `@tool` decorator modules use to register callable tools
- Exposes REST endpoints and a WebSocket for the dashboard

### Voice Layer — Pipecat (`voice/`)

Runs as an asyncio background task inside the FastAPI process.

**Pipeline:**
```
[Mic] → OpenWakeWord → Faster-Whisper STT → Ollama agent → TTS → [Speaker]
```

**Wake word:** OpenWakeWord, default trigger `"Hey Plia"`. Model and keyword configurable in `config.py`. No API key required.

**STT:** Faster-Whisper, fully local. Model size configurable (`tiny` → `medium`). No network call.

**TTS — two engines, both wired in:**

| Engine | Default use | Key parameters |
|--------|-------------|----------------|
| Kokoro | Everyday responses — fast, CPU-only | `voice` (accent/character), `speed` |
| Chatterbox | Voice cloning, emotional delivery | `reference_audio` (5-sec clip), `exaggeration` (0.0–1.0) |

Engine selection is a config value — no code change required to switch. Kokoro is the default; Chatterbox activates when `reference_audio` is set or emotion control is needed.

**Voice customisation parameters:**

| Parameter | Engine | Effect |
|-----------|--------|--------|
| `voice` | Kokoro | Swap accent/character (US, UK, FR, JP, ZH, KO) |
| `speed` | Kokoro | Playback rate |
| `reference_audio` | Chatterbox | Clone voice from a 5-second audio clip |
| `exaggeration` | Chatterbox | Emotion dial — 0.0 (flat) → 1.0 (dramatic) |

### LLM Agent (`core/agent.py`)

- Calls Ollama via its HTTP API (OpenAI-compatible endpoint)
- Default model: configurable in `config.py` (e.g. `llama3.2`, `mistral`, `qwen2.5`)
- On each user turn: sends conversation history + registered tool schemas to Ollama
- Parses tool-call responses, executes the matching registered tool, feeds result back to Ollama
- Returns final text response to the voice pipeline for TTS

### Module System (`core/registry.py` + `modules/`)

Modules register tools using a `@tool` decorator. The registry auto-generates the JSON schema Ollama needs from Python type annotations.

```python
# modules/example_module.py
from core.registry import tool

@tool(description="Get the current time")
def get_time() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")

@tool(description="Set a reminder in N minutes")
def set_reminder(message: str, minutes: int) -> str:
    ...
```

**Module rules:**
- One file per module in `modules/`
- Tools are typed Python functions (sync or async)
- Modules may import anything — file I/O, subprocess, HTTP, hardware libs
- Modules do not depend on each other — they talk to the outside world only
- Failed imports are logged and skipped; the rest of the system loads normally

### Web Dashboard (`dashboard/`)

Served by FastAPI at `http://localhost:8000`. No separate server, no build step.

**Frontend:** HTMX — plain HTML with small JS snippets. WebSocket pushes HTML fragments as events occur. Upgradeable to React later without changing the backend.

**Panels:**

| Panel | Content |
|-------|---------|
| Conversation feed | Live transcript: wake detections, speech, replies, tool calls |
| Voice controls | Switch TTS engine, pick voice, set emotion/speed, upload reference clip |
| Module manager | Registered modules and tools — enable/disable per module |
| System status | Ollama model, mic state, wake word armed, pipeline state |

**API routes:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Dashboard HTML |
| `GET` | `/api/tools` | List all registered tools |
| `GET` | `/api/config` | Current voice + model config |
| `POST` | `/api/config` | Update voice or model settings |
| `WS` | `/ws` | Live event stream |

---

## Data Flow

```
Wake word detected
    → VAD confirms speech
        → Faster-Whisper transcribes → text
            → agent.py sends [history + tools] to Ollama
                → Ollama responds with text or tool_call
                    → if tool_call: registry executes tool, result fed back to Ollama
                    → Ollama produces final text
                        → TTS synthesises audio
                            → audio plays
                                → pipeline resets to armed state
```

All steps emit events to the WebSocket, which updates the dashboard in real time.

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Ollama not running at startup | Warning logged, voice pipeline disabled; retries every 30s |
| STT transcription fails | TTS speaks "I didn't catch that, please try again" |
| Tool call raises exception | Exception message returned to Ollama as the tool result; LLM handles it |
| Chatterbox TTS fails | Falls back to Kokoro automatically; error logged |
| Module import fails | Module skipped with warning; rest of system loads normally |
| Wake word missed / silence | Pipeline self-resets after 15s timeout, returns to armed state |

No exception propagates to crash the process. The pipeline always returns to the armed, waiting state.

---

## Testing

| File | Covers |
|------|--------|
| `tests/test_registry.py` | Tool registration, JSON schema generation, duplicate name handling |
| `tests/test_agent.py` | Ollama tool-call parsing with a mock LLM response |
| `tests/test_pipeline.py` | Pipeline state transitions (idle → listening → speaking → idle) with injected audio frames |
| `tests/test_modules/` | One file per module — tool functions tested directly, no voice layer |
| `tests/test_dashboard.py` | FastAPI routes and WebSocket event emission |

Voice hardware (mic, speaker) is never required in tests. Pipecat's frame API is used to inject synthetic audio frames.

---

## Future Extensions

- **Multi-agent:** `agent.py` is upgraded so a tool can spin up a sub-agent — a second Ollama call with its own tool subset. Module API unchanged.
- **New modules:** Drop a `.py` file in `modules/`, restart — tool appears in Ollama's context automatically.
- **React dashboard:** FastAPI backend unchanged; swap HTMX frontend for React against the same `/api` and `/ws` endpoints.
- **Remote voice clients:** Pipecat supports WebRTC transport — a future module can stream voice from a phone or remote device.

---

## Dependencies

| Package | Role |
|---------|------|
| `pipecat-ai` | Voice pipeline framework |
| `openwakeword` | Wake word detection |
| `faster-whisper` | Local STT |
| `kokoro` | TTS engine (default) |
| `chatterbox-tts` | TTS engine (voice cloning / emotion) |
| `ollama` | Local LLM HTTP client |
| `fastapi` | Core app + dashboard API |
| `uvicorn` | ASGI server |
| `websockets` | WebSocket support |
