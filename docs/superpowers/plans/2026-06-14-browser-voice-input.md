# Browser Voice Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mic button to the dashboard chat input that captures audio from the browser microphone, transcribes it via the existing STT engine, and populates the chat input with the result.

**Architecture:** The browser captures audio using `AudioContext` at 16 kHz and `ScriptProcessor`, accumulates raw float32 PCM samples, then POSTs them as binary (`application/octet-stream`) to `POST /api/voice/transcribe`. The backend reads the body as a numpy float32 array and passes it to a shared `STTService` singleton — the same model the voice pipeline uses, so no second model load occurs. The transcript is returned as `{"text": "..."}` and injected into the chat input field.

**Tech Stack:** faster-whisper (existing), numpy (existing), FastAPI (existing), Web Audio API (ScriptProcessor), vanilla JS fetch

---

## File Map

| File | Change |
|------|--------|
| `voice/stt.py` | Add `get_stt_service()` singleton with lazy load |
| `voice/pipeline.py` | Use `get_stt_service()` instead of creating own `STTService` |
| `dashboard/server.py` | Add `POST /api/voice/transcribe` |
| `dashboard/static/index.html` | Mic button + recording JS + transcript injection |
| `tests/test_voice_transcribe.py` | New — endpoint tests |

---

### Task 1: STT singleton + pipeline refactor

**Files:**
- Modify: `voice/stt.py`
- Modify: `voice/pipeline.py`

Context: `VoicePipeline.__init__` at `voice/pipeline.py` line 35 does `self._stt = STTService()`, and `load()` at line 44 calls `self._stt.load()`. We want both pipeline and the new web endpoint to share one loaded model. STT runs on CPU so it's RAM-only — but loading twice wastes ~200 MB.

Current `voice/stt.py` (28 lines total):
```python
import numpy as np
from core.config import get_config

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

class STTService:
    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        config = get_config()
        self._model = WhisperModel(config.stt_model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("Call load() before transcribe()")
        config = get_config()
        segments, _ = self._model.transcribe(audio, language=config.stt_language)
        return " ".join(seg.text.strip() for seg in segments).strip()
```

- [ ] **Step 1: Add `get_stt_service()` to `voice/stt.py`**

Append after the `STTService` class (after line 27):

```python

_stt_service: STTService | None = None


def get_stt_service() -> STTService:
    """Lazy singleton — loads the Whisper model on first call."""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
        _stt_service.load()
    return _stt_service
```

- [ ] **Step 2: Refactor `voice/pipeline.py` to use singleton**

In `voice/pipeline.py`:
1. Change line 9 from `from voice.stt import STTService` to `from voice.stt import get_stt_service`
2. In `__init__` (line 35), remove `self._stt = STTService()`
3. In `load()` (around line 44), replace `self._stt.load()` with `self._stt = get_stt_service()`

After change, `__init__` has no `self._stt` init (it's set in `load()`), and `load()` does `self._stt = get_stt_service()` instead of `self._stt.load()`.

- [ ] **Step 3: Run full test suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all tests pass (same count as before).

- [ ] **Step 4: Commit**

```bash
git add voice/stt.py voice/pipeline.py
git commit -m "refactor(stt): extract get_stt_service() singleton; pipeline uses shared model"
```

---

### Task 2: `POST /api/voice/transcribe` endpoint + tests

**Files:**
- Modify: `dashboard/server.py`
- Create: `tests/test_voice_transcribe.py`

The endpoint receives raw float32 PCM bytes as `application/octet-stream`, converts to numpy array, calls `get_stt_service().transcribe()`, returns `{"text": "..."}`. Uses `asyncio.to_thread` since STT is CPU-bound.

- [ ] **Step 1: Write failing tests**

Create `tests/test_voice_transcribe.py`:

```python
import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_transcribe_returns_text(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "hello world"
    audio = np.zeros(16000, dtype=np.float32)
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/voice/transcribe",
                content=audio.tobytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.status_code == 200
    assert r.json()["text"] == "hello world"
    mock_stt.transcribe.assert_called_once()
    called_audio = mock_stt.transcribe.call_args[0][0]
    assert isinstance(called_audio, np.ndarray)
    assert called_audio.dtype == np.float32
    assert len(called_audio) == 16000


@pytest.mark.asyncio
async def test_transcribe_empty_body_returns_empty_text(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/api/voice/transcribe",
            content=b"",
            headers={"Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    assert r.json()["text"] == ""


@pytest.mark.asyncio
async def test_transcribe_empty_transcript_returns_empty(app):
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = ""
    audio = np.zeros(8000, dtype=np.float32)
    with patch("voice.stt.get_stt_service", return_value=mock_stt):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post(
                "/api/voice/transcribe",
                content=audio.tobytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
    assert r.status_code == 200
    assert r.json()["text"] == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/test_voice_transcribe.py -v
```

Expected: FAIL (404 — route not yet defined).

- [ ] **Step 3: Add endpoint to `dashboard/server.py`**

First, read `dashboard/server.py` to find the right imports section and a good insertion point (near the `GET /api/tools` route). Then:

Add `import numpy as np` at the top with other imports.

Add the route before the first `@router.get("/api/tools")`:

```python
@router.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    body = await request.body()
    if not body:
        return {"text": ""}
    audio = np.frombuffer(body, dtype=np.float32)
    from voice.stt import get_stt_service
    text = await asyncio.to_thread(get_stt_service().transcribe, audio)
    return {"text": text}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
source .venv/bin/activate && pytest tests/test_voice_transcribe.py -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run full suite**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_voice_transcribe.py
git commit -m "feat(dashboard): add POST /api/voice/transcribe for browser mic input"
```

---

### Task 3: Mic button + recording JS in dashboard

**Files:**
- Modify: `dashboard/static/index.html`

No backend tests — pure HTML/JS. Pattern reference: the dashboard already uses `AudioContext`/`MediaStream` for Chatterbox reference audio recording.

UI: small mic button (🎤) next to the send button in the chat input bar (`#chat-input-bar`). The send button is `<button id="chat-send-btn" onclick="sendChat()">Send</button>` at line 381.

States: idle (🎤) → recording (⏹, red text) → processing (⏳) → idle.

On transcript: append to `#chat-input` (preserving existing text + space) and focus.

- [ ] **Step 1: Add mic button HTML**

Find this line in `dashboard/static/index.html`:
```html
    <button id="chat-send-btn" onclick="sendChat()">Send</button>
```

Add the mic button immediately before it:
```html
    <button id="mic-btn" onclick="toggleMicRecording()" title="Voice input" style="background:#1e1e1e;border:1px solid #333;border-radius:4px;color:#aaa;font-size:1rem;padding:6px 10px;cursor:pointer;margin-right:4px;">🎤</button>
```

- [ ] **Step 2: Add mic recording JS functions**

Find the `loadModules` function. Add the following block immediately after it (before the closing `</script>` or next function):

```javascript
  let _micCtx = null;
  let _micStream = null;
  let _micProcessor = null;
  let _micChunks = [];
  let _micRecording = false;

  async function toggleMicRecording() {
    if (_micRecording) {
      stopMicRecording();
    } else {
      await startMicRecording();
    }
  }

  async function startMicRecording() {
    const btn = document.getElementById('mic-btn');
    try {
      _micStream = await navigator.mediaDevices.getUserMedia({audio: true});
    } catch(e) {
      btn.title = 'Microphone permission denied';
      return;
    }
    _micChunks = [];
    _micCtx = new AudioContext({sampleRate: 16000});
    const source = _micCtx.createMediaStreamSource(_micStream);
    _micProcessor = _micCtx.createScriptProcessor(4096, 1, 1);
    _micProcessor.onaudioprocess = (e) => {
      _micChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    source.connect(_micProcessor);
    _micProcessor.connect(_micCtx.destination);
    _micRecording = true;
    btn.textContent = '⏹';
    btn.style.color = '#ef9a9a';
    btn.title = 'Stop recording';
  }

  async function stopMicRecording() {
    _micRecording = false;
    const btn = document.getElementById('mic-btn');
    btn.textContent = '🎤';
    btn.style.color = '#aaa';
    btn.title = 'Voice input';

    if (_micProcessor) { _micProcessor.disconnect(); _micProcessor = null; }
    if (_micCtx) { await _micCtx.close(); _micCtx = null; }
    if (_micStream) { _micStream.getTracks().forEach(t => t.stop()); _micStream = null; }

    if (_micChunks.length === 0) return;

    const total = _micChunks.reduce((n, c) => n + c.length, 0);
    const merged = new Float32Array(total);
    let offset = 0;
    for (const chunk of _micChunks) { merged.set(chunk, offset); offset += chunk.length; }
    _micChunks = [];

    btn.textContent = '⏳';
    btn.title = 'Transcribing…';
    try {
      const r = await fetch('/api/voice/transcribe', {
        method: 'POST',
        body: merged.buffer,
        headers: {'Content-Type': 'application/octet-stream'},
      });
      if (r.ok) {
        const data = await r.json();
        if (data.text) {
          const inp = document.getElementById('chat-input');
          inp.value = (inp.value ? inp.value + ' ' : '') + data.text;
          inp.focus();
        }
      }
    } catch(e) { /* silently reset on network error */ }
    btn.textContent = '🎤';
    btn.title = 'Voice input';
  }
```

- [ ] **Step 3: Run full suite for regressions**

```bash
source .venv/bin/activate && pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add browser mic button for voice-to-text chat input"
```

---

## Self-Review

**Spec coverage:**
- ✅ Browser mic capture → raw float32 PCM (AudioContext 16kHz + ScriptProcessor)
- ✅ POST to `/api/voice/transcribe`
- ✅ Backend decodes binary → numpy → faster-whisper via singleton
- ✅ Transcript injected into chat input
- ✅ STT singleton prevents double model load
- ✅ Empty body → `{"text": ""}` 200
- ✅ Recording state indicator (⏹ red when recording, ⏳ when processing)
- ✅ Mic permission denied handled gracefully

**Placeholder scan:** None found — all steps have complete code.

**Type consistency:**
- `get_stt_service()` returns `STTService` — used in pipeline and endpoint consistently
- `STTService.transcribe(audio: np.ndarray) -> str` — called correctly in endpoint with `np.frombuffer(..., dtype=np.float32)`
- `_micChunks: Float32Array[]` → merged to `Float32Array` → `.buffer` is `ArrayBuffer` → sent as body ✅
