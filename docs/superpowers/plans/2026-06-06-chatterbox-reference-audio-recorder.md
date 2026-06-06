# Chatterbox Reference Audio Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Record/Stop buttons to the dashboard's Chatterbox controls that capture reference audio from the system mic server-side, with a live browser level meter for visual feedback.

**Architecture:** Two new FastAPI endpoints (`/api/start-recording`, `/api/stop-recording`) control a `sounddevice.InputStream` running in a daemon thread. The browser calls these endpoints and independently drives a Web Audio API level meter from its own mic access (visual only — no audio data flows browser→server). The recording is saved as a WAV to `uploads/` and automatically set as `chatterbox_reference_audio`.

**Tech Stack:** Python `sounddevice`, `scipy.io.wavfile`, `threading`, `numpy`; vanilla JS `MediaDevices`, `AudioContext`, `AnalyserNode`, `requestAnimationFrame`.

---

## File Map

| File | Change |
|---|---|
| `dashboard/server.py` | Add imports, `_RECORD_SAMPLE_RATE`, `_Recorder` class, `_recorder` instance, two new endpoints |
| `dashboard/static/index.html` | Add Record/Stop buttons, timer span, canvas meter, and JS functions inside Chatterbox controls |
| `tests/test_dashboard.py` | Add `reset_recorder` fixture and four new tests |

---

## Task 1: Backend — `_Recorder` + `start-recording` endpoint

**Files:**
- Modify: `dashboard/server.py`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dashboard.py` after the existing imports:

```python
import threading
import numpy as np
from unittest.mock import patch, MagicMock
from dashboard import server as dashboard_server
```

Add these fixtures and tests after the existing tests:

```python
@pytest.fixture(autouse=True)
def reset_recorder():
    yield
    dashboard_server._recorder._stop_event.set()
    if dashboard_server._recorder.thread:
        dashboard_server._recorder.thread.join(timeout=1.0)
    dashboard_server._recorder.active = False
    dashboard_server._recorder.thread = None
    dashboard_server._recorder.chunks = []
    dashboard_server._recorder._stop_event.clear()


def _make_mock_sd():
    """Return a mock sounddevice module whose InputStream is a no-op context manager."""
    mock_sd = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    mock_sd.InputStream.return_value = cm
    return mock_sd


async def test_start_recording_returns_200(app):
    with patch("dashboard.server.sd", _make_mock_sd()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/start-recording")
    assert resp.status_code == 200
    assert resp.json() == {"recording": True}
    assert dashboard_server._recorder.active is True


async def test_start_recording_while_active_returns_409(app):
    dashboard_server._recorder.active = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/start-recording")
    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_dashboard.py::test_start_recording_returns_200 tests/test_dashboard.py::test_start_recording_while_active_returns_409 -v
```

Expected: `FAILED` — `AttributeError: module 'dashboard.server' has no attribute '_recorder'`

- [ ] **Step 3: Add imports and `_Recorder` to `dashboard/server.py`**

Add after the existing imports (after `from core.config import get_config, update_config`):

```python
import threading
import numpy as np
from datetime import datetime
from scipy.io import wavfile

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
```

- [ ] **Step 4: Add `start-recording` endpoint to `dashboard/server.py`**

Add after the existing `upload_reference_audio` endpoint:

```python
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
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_dashboard.py::test_start_recording_returns_200 tests/test_dashboard.py::test_start_recording_while_active_returns_409 -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_dashboard.py
git commit -m "feat: add _Recorder and start-recording endpoint"
```

---

## Task 2: Backend — `stop-recording` endpoint

**Files:**
- Modify: `dashboard/server.py`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_dashboard.py` after the tests from Task 1:

```python
async def test_stop_recording_saves_wav_and_updates_config(app, tmp_path):
    chunk = np.zeros((1600, 1), dtype=np.int16)
    dashboard_server._recorder.active = True
    dashboard_server._recorder.chunks = [chunk, chunk]
    dashboard_server._recorder.thread = None

    with patch.object(dashboard_server, "UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/stop-recording")

    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"].startswith("recording_")
    assert data["filename"].endswith(".wav")
    assert (tmp_path / data["filename"]).exists()
    from core.config import get_config
    assert get_config().chatterbox_reference_audio == data["path"]


async def test_stop_recording_when_idle_returns_409(app):
    dashboard_server._recorder.active = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/stop-recording")
    assert resp.status_code == 409
```

Add `patch` to the existing import line:
```python
from unittest.mock import patch, MagicMock
```
(already added in Task 1)

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_dashboard.py::test_stop_recording_saves_wav_and_updates_config tests/test_dashboard.py::test_stop_recording_when_idle_returns_409 -v
```

Expected: `FAILED` — `404 Not Found` (endpoint doesn't exist yet)

- [ ] **Step 3: Add `stop-recording` endpoint to `dashboard/server.py`**

Add directly after the `start_recording` endpoint:

```python
@router.post("/api/stop-recording")
async def stop_recording():
    if not _recorder.active:
        raise HTTPException(status_code=409, detail="Not recording")
    _recorder._stop_event.set()
    if _recorder.thread:
        _recorder.thread.join(timeout=2.0)
        _recorder.thread = None
    _recorder.active = False
    _recorder._stop_event.clear()

    if not _recorder.chunks:
        raise HTTPException(status_code=500, detail="No audio captured")

    audio = np.concatenate(_recorder.chunks, axis=0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = UPLOADS_DIR / f"recording_{ts}.wav"
    wavfile.write(str(dest), _RECORD_SAMPLE_RATE, audio)
    update_config(chatterbox_reference_audio=str(dest))
    return {"path": str(dest), "filename": dest.name}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_dashboard.py::test_stop_recording_saves_wav_and_updates_config tests/test_dashboard.py::test_stop_recording_when_idle_returns_409 -v
```

Expected: `2 passed`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/test_dashboard.py -v
```

Expected: `6 passed` (4 existing + 2 new)

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_dashboard.py
git commit -m "feat: add stop-recording endpoint, write WAV and update config"
```

---

## Task 3: Frontend — Record/Stop UI and level meter

**Files:**
- Modify: `dashboard/static/index.html`

No automated tests for this task — verify manually at the end.

- [ ] **Step 1: Add Record/Stop buttons, timer, and canvas to `#chatterbox-controls`**

In `dashboard/static/index.html`, locate the `<div id="cb-ref-status" class="ref-status"></div>` line (line 68). Insert the following block immediately after it (before the Exaggeration `<label>`):

```html
      <div style="display:flex;gap:6px;margin:4px 0;">
        <button id="cb-record-btn" onclick="startRecording()" style="width:auto;padding:6px 10px;">Record</button>
        <button id="cb-stop-btn" onclick="stopRecording()" style="display:none;width:auto;padding:6px 10px;">Stop</button>
        <span id="cb-timer" style="display:none;font-size:0.75rem;color:#4fc3f7;align-self:center;"></span>
      </div>
      <canvas id="cb-meter" width="120" height="10" style="display:none;margin-bottom:4px;border-radius:2px;background:#1a1a1a;"></canvas>
```

- [ ] **Step 2: Add module-level recorder state variables to the `<script>` block**

In `dashboard/static/index.html`, insert the following at the very top of the `<script>` block (before `const ws = ...`):

```javascript
  let _recTimerInterval = null;
  let _recTimerSeconds = 0;
  let _recAudioCtx = null;
  let _recMeterRaf = null;
  let _recStream = null;
```

- [ ] **Step 3: Add `startRecording()` function**

Add before the closing `</script>` tag:

```javascript
  async function startRecording() {
    const statusEl = document.getElementById('cb-ref-status');
    const res = await fetch('/api/start-recording', { method: 'POST' });
    if (!res.ok) {
      statusEl.textContent = 'Failed to start recording';
      return;
    }

    // Timer
    _recTimerSeconds = 0;
    const timerEl = document.getElementById('cb-timer');
    timerEl.textContent = 'Recording… 0:00';
    timerEl.style.display = '';
    _recTimerInterval = setInterval(() => {
      _recTimerSeconds++;
      const m = Math.floor(_recTimerSeconds / 60);
      const s = String(_recTimerSeconds % 60).padStart(2, '0');
      timerEl.textContent = `Recording… ${m}:${s}`;
    }, 1000);

    // Level meter (mic permission for visual only; silently skip if denied)
    try {
      _recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      _recAudioCtx = new AudioContext();
      const analyser = _recAudioCtx.createAnalyser();
      analyser.fftSize = 256;
      _recAudioCtx.createMediaStreamSource(_recStream).connect(analyser);
      const canvas = document.getElementById('cb-meter');
      canvas.style.display = '';
      const ctx2d = canvas.getContext('2d');
      const dataArr = new Uint8Array(analyser.frequencyBinCount);
      function drawMeter() {
        _recMeterRaf = requestAnimationFrame(drawMeter);
        analyser.getByteFrequencyData(dataArr);
        const level = dataArr.reduce((a, b) => a + b, 0) / dataArr.length / 255;
        ctx2d.clearRect(0, 0, canvas.width, canvas.height);
        ctx2d.fillStyle = '#1a1a1a';
        ctx2d.fillRect(0, 0, canvas.width, canvas.height);
        ctx2d.fillStyle = '#4caf50';
        ctx2d.fillRect(0, 0, canvas.width * level, canvas.height);
      }
      drawMeter();
    } catch (_) { /* mic denied — recording still proceeds server-side */ }

    document.getElementById('cb-record-btn').style.display = 'none';
    document.getElementById('cb-stop-btn').style.display = '';
  }
```

- [ ] **Step 4: Add `stopRecording()` function**

Add after `startRecording()`, before the closing `</script>` tag:

```javascript
  async function stopRecording() {
    // Tear down timer
    clearInterval(_recTimerInterval);
    _recTimerInterval = null;
    document.getElementById('cb-timer').style.display = 'none';

    // Tear down level meter
    if (_recMeterRaf) { cancelAnimationFrame(_recMeterRaf); _recMeterRaf = null; }
    if (_recStream) { _recStream.getTracks().forEach(t => t.stop()); _recStream = null; }
    if (_recAudioCtx) { _recAudioCtx.close(); _recAudioCtx = null; }
    document.getElementById('cb-meter').style.display = 'none';

    // Restore buttons
    document.getElementById('cb-record-btn').style.display = '';
    document.getElementById('cb-stop-btn').style.display = 'none';

    // Call backend
    const statusEl = document.getElementById('cb-ref-status');
    statusEl.textContent = 'Saving…';
    const res = await fetch('/api/stop-recording', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      statusEl.textContent = `Loaded: ${data.filename}`;
    } else {
      statusEl.textContent = 'Stop failed';
    }
  }
```

- [ ] **Step 5: Verify in the browser**

Start the server:
```bash
cd /home/alfcon/Projects/Plia-OS && python -m uvicorn core.main:app --reload
```

Open `http://localhost:8000` in a browser, switch the engine to **Chatterbox**, and verify:
- Record button and existing file upload both appear
- Clicking Record prompts for mic permission, starts the timer, shows the green level meter, hides Record, shows Stop
- Clicking Stop hides the meter and timer, updates the status line to `Loaded: recording_<timestamp>.wav`, restores the Record button
- Check that `uploads/recording_<timestamp>.wav` exists and is non-empty

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: add browser Record/Stop UI with live level meter for Chatterbox reference audio"
```
