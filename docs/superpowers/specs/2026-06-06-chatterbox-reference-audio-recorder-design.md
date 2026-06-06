# Chatterbox Reference Audio Recorder

**Date:** 2026-06-06  
**Status:** Approved

## Problem

Chatterbox TTS requires a short (5–10 s) reference audio file for voice cloning. The dashboard already supports uploading a pre-existing file, but users have no way to record one on the spot. They must prepare a file externally before they can use Chatterbox voice cloning.

## Goal

Add a Record button to the Chatterbox section of the dashboard that lets the user record their voice directly from the browser, with a live level meter for visual feedback, and automatically set the recording as the Chatterbox reference audio when stopped.

## Architecture

Two concerns are cleanly separated:

- **Backend** captures the audio from the system microphone and writes the WAV file.
- **Frontend** drives the backend via API calls and provides visual feedback via the browser's own mic access (level meter only — no audio data flows from browser to server).

## Backend (`dashboard/server.py`)

### New endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/start-recording` | POST | Starts system mic capture in a background thread. Returns 409 if already recording. |
| `/api/stop-recording` | POST | Stops capture, saves WAV, updates config, returns `{filename, path}`. Returns 409 if not recording. |

### Implementation details

- A module-level `_Recorder` object holds: `active: bool`, `thread: Thread | None`, `chunks: list[np.ndarray]`.
- `start-recording` creates a `sounddevice.InputStream` (16 kHz, mono, int16 — matching pipeline constants) in a daemon thread. Each callback appends the chunk to `_recorder.chunks`.
- `stop-recording` sets `_recorder.active = False`, joins the thread, concatenates chunks, writes to `uploads/recording_<timestamp>.wav` via `scipy.io.wavfile.write`, then calls `update_config(chatterbox_reference_audio=str(path))`.
- Returns the same `{filename, path}` shape as the existing `/api/upload-reference-audio` so the frontend can reuse the same status-update logic.

### Error handling

- `start-recording` returns HTTP 409 if `_recorder.active` is already `True`.
- `stop-recording` returns HTTP 409 if `_recorder.active` is `False`.
- If `sounddevice` raises on open (device unavailable), returns HTTP 500 with the error message.

## Frontend (`dashboard/static/index.html`)

### New UI elements (inside `#chatterbox-controls`, between the file upload and the exaggeration slider)

```
[ Record ]  [ Stop ]   Recording… 0:07
[=========---------]   ← canvas level meter (120×10 px)
```

- **Record button** — visible by default; hidden while recording.
- **Stop button** — hidden by default; visible while recording.
- **Timer** — `Recording… M:SS` updated by `setInterval` every second; hidden when not recording.
- **Level meter** — a `<canvas>` (120 × 10 px) with a green bar driven by `AnalyserNode.getByteFrequencyData`. Hidden when not recording.

### JS functions

**`startRecording()`**
1. `POST /api/start-recording` — if non-2xx, show error in `cb-ref-status` and abort.
2. `navigator.mediaDevices.getUserMedia({ audio: true })` — only for the level meter.
3. Wire `AudioContext` → `MediaStreamSource` → `AnalyserNode`; start `requestAnimationFrame` loop drawing the meter bar.
4. Start `setInterval` timer (1 s tick).
5. Swap button visibility.

**`stopRecording()`**
1. `POST /api/stop-recording` — on success, update `cb-ref-status` with `Loaded: <filename>`.
2. Stop timer interval and RAF loop.
3. Stop all mic tracks (`stream.getTracks().forEach(t => t.stop())`).
4. Close `AudioContext`.
5. Swap button visibility, hide meter and timer.

### Mic permission

The browser requests mic access only to power the level meter. If the user denies permission, the recording still proceeds server-side — only the visual meter is skipped (no error shown for the denial).

## Data flow

```
User clicks Record
  → browser calls POST /api/start-recording
  → backend opens sounddevice.InputStream (16 kHz mono int16)
  → browser requests getUserMedia for level meter only
  → meter animates, timer counts up

User clicks Stop
  → browser calls POST /api/stop-recording
  → backend: joins thread, saves uploads/recording_<ts>.wav, updates config
  → browser: tears down AudioContext, updates cb-ref-status with filename
```

## Testing

- Unit tests for `start-recording` / `stop-recording` endpoints (mock `sounddevice`, verify WAV write and config update).
- Test 409 responses for double-start and stop-when-idle.
- Existing upload endpoint tests remain unchanged.
- Manual verification: record 5 s, confirm WAV appears in `uploads/`, confirm Chatterbox uses it on next synthesis.

## Out of scope

- Playback of the recorded clip in the browser.
- Automatic stop after a max duration.
- Format conversion (WAV is written directly; Chatterbox accepts WAV).
