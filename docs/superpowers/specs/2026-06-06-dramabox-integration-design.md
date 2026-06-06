# Dramabox TTS Integration Design

**Date:** 2026-06-06
**Status:** Approved

## Overview

Integrate ResembleAI's Dramabox TTS (Gemma 3 12B + LTX-2.3 DiT) as a 4th engine in Plia-OS. Dramabox produces highly expressive, voice-cloned speech and supports arbitrary-length generation via chunked diffusion. It serves two roles simultaneously:

1. **Live voice pipeline engine** — synthesises responses in the armed → speaking cycle
2. **On-demand dashboard clip generator** — generates long-form audio clips from the dashboard

## Architecture

### Hardware fit

- GPU: RTX 4060 Mobile (8 GB VRAM)
- RAM: 32 GB system
- Gemma 3 12B (4-bit) loads with `device_map="auto"` → lands on CPU RAM (~23 GB used)
- DiT transformer (`dramabox-dit-v1.safetensors`) + VAE (`dramabox-audio-components.safetensors`) load on GPU (~5–6 GB VRAM combined)
- Both roles share the single loaded `TTSServer` instance — load once, serve both

## Section 1 — Vendoring Strategy

### File layout

```
voice/dramabox/
  __init__.py
  wrapper.py              ← DramaboxTTS integration class
  src/                    ← vendored from ResembleAI/Dramabox HF space
    inference_server.py   ← TTSServer (warm model server)
    model_downloader.py   ← HF download helpers
    text_chunker.py       ← quote-aware sentence chunker
    audio_conditioning.py ← AudioConditionByReferenceLatent
    duration_estimator.py ← estimate_speech_duration
    preprocess.py         ← audio preprocessing utilities
    super_resolution.py   ← REUSEUpsampler (voice-ref denoising)
  ltx2/                   ← vendored LTX-2.3 framework
    ltx_core/             ← DiT components, VAE, patchifier, schedulers
    ltx_pipelines/        ← denoiser, sampler, media I/O, PromptEncoder, AudioDecoder

scripts/
  vendor_dramabox.py      ← one-shot vendoring script
```

Files excluded from vendoring: `train.py`, `validate.py` (training-only, not needed for inference).

### Vendoring script

`scripts/vendor_dramabox.py` does the following at runtime:
1. `huggingface_hub.snapshot_download("ResembleAI/Dramabox")` → local snapshot
2. Copies `snapshot/src/` → `voice/dramabox/src/` (excluding train.py, validate.py)
3. Copies `snapshot/ltx2/` → `voice/dramabox/ltx2/`
4. Writes `voice/dramabox/__init__.py` and `voice/dramabox/ltx2/__init__.py` if absent

### Path patches in `inference_server.py`

The original file resolves `APP_DIR = Path(__file__).parent.parent` and then uses:
- `sys.path.insert(0, str(APP_DIR / "ltx2"))`
- `MODELS = APP_DIR / "models"`

After vendoring, `__file__` is `voice/dramabox/src/inference_server.py`, so `APP_DIR` becomes `voice/dramabox/` — `ltx2/` is correctly adjacent. No source edits needed for the path walk; only the `MODELS` default path is overridden by `TTSServer.__init__` parameters which `wrapper.py` always supplies explicitly.

### New dependencies (`pyproject.toml`, extras group `[dramabox]`)

```
accelerate>=0.25.0
bitsandbytes>=0.45.0
peft>=0.7.0
av>=12.0.0
einops>=0.7.0
sentencepiece>=0.1.99
resemble-perth @ git+https://github.com/resemble-ai/Perth.git@master
```

These are optional so Plia-OS remains importable without them (Dramabox fails gracefully if not installed, following the Chatterbox pattern).

## Section 2 — Backend Architecture

### Config changes (`core/config.py`)

```python
tts_engine: Literal["kokoro", "chatterbox", "dramabox"] = "kokoro"
dramabox_voice_ref: str | None = None
dramabox_cfg_scale: float = 2.5
dramabox_stg_scale: float = 1.5
dramabox_seed: int = 42
dramabox_duration_multiplier: float = 1.1
```

`dramabox_voice_ref` is separate from `chatterbox_reference_audio` — the two engines have independent reference audio configs (different speakers, different styles).

### `voice/dramabox/wrapper.py` — `DramaboxTTS` class

```python
class DramaboxTTS:
    def __init__(self) -> None:
        self._server = None  # TTSServer, lazy-loaded

    def load(self) -> None:
        """Eagerly load all models. Called by TTSService.load() when engine == 'dramabox'."""
        self._load()

    def _load(self) -> None:
        from voice.dramabox.src.inference_server import TTSServer
        from voice.dramabox.src.model_downloader import get_model_path, get_gemma_path
        transformer = get_model_path("transformer")
        audio_components = get_model_path("audio_components")
        gemma_root = get_gemma_path()
        self._server = TTSServer(
            checkpoint=transformer,
            full_checkpoint=audio_components,
            gemma_root=gemma_root,
            device="cuda",
            dtype="bf16",
            compile_model=False,   # torch.compile disabled — RTX 4060 Mobile benefits limited
            bnb_4bit=True,
        )

    def synthesise(self, text: str) -> tuple[torch.Tensor, int]:
        """For live pipeline: returns (waveform_tensor, sample_rate)."""
        config = get_config()
        waveform, sr = self._server.generate(
            prompt=text,
            voice_ref=config.dramabox_voice_ref,
            cfg_scale=config.dramabox_cfg_scale,
            stg_scale=config.dramabox_stg_scale,
            seed=config.dramabox_seed,
            duration_multiplier=config.dramabox_duration_multiplier,
        )
        return waveform.cpu().float(), sr

    def generate_to_file(self, prompt: str, dest: str,
                         progress_callback=None) -> str:
        """For on-demand generation: writes WAV to dest, returns path."""
        config = get_config()
        self._server.generate_to_file(
            prompt=prompt,
            output=dest,
            voice_ref=config.dramabox_voice_ref,
            cfg_scale=config.dramabox_cfg_scale,
            stg_scale=config.dramabox_stg_scale,
            seed=config.dramabox_seed,
            duration_multiplier=config.dramabox_duration_multiplier,
            watermark=True,
            progress_callback=progress_callback,
        )
        return dest
```

### `voice/tts.py` changes

- Add `from voice.dramabox.wrapper import DramaboxTTS` (try/except ImportError, sets to None)
- Add `self._dramabox: DramaboxTTS | None = None` to `TTSService.__init__`
- Add `_load_dramabox(self, config)` — mirrors `_load_chatterbox`: instantiates `DramaboxTTS`, calls `load()`, falls back to kokoro on failure
- `load()` dispatches to `_load_dramabox()` when `config.tts_engine == "dramabox"`
- `synthesise()` dispatches to `_synthesise_dramabox()` when engine is `"dramabox"`
- `_synthesise_dramabox(self, text) → np.ndarray`:
  - calls `self._dramabox.synthesise(text)` → (tensor, sr) where sr = 48000
  - resamples to 24000 Hz with `torchaudio.functional.resample(waveform, sr, 24000)` so `pipeline.py`'s `sd.play(..., samplerate=24000)` plays at the correct rate without changing the TTSService interface
  - returns mono float32 numpy array

### New API endpoints (`dashboard/server.py`)

#### `POST /api/generate-dramabox`

Body: `{ "prompt": str, "seed": int | null }`

- Validates that `tts_engine == "dramabox"` and `_dramabox` is loaded; 409 if not
- Generates a timestamped output path: `uploads/dramabox_{ts}.wav`
- Runs `dramabox.generate_to_file(prompt, dest, progress_callback=...)` in `asyncio.to_thread()`
- Progress callback calls `asyncio.run_coroutine_threadsafe(_broadcast({type: "dramabox_progress", ...}), loop)`
- Returns `{"path": str, "filename": str}` on success

Progress event payload sent over WebSocket:
```json
{"type": "dramabox_progress", "chunk": 1, "total": 3, "est_duration_s": 18.5}
```

#### Access to `_dramabox` from the endpoint

`voice/tts.py` exposes a module-level singleton: after `TTSService.load()` completes, it registers itself in `_service: TTSService | None = None` at module level, exposed via `get_tts_service() -> TTSService | None`. `dashboard/server.py` imports and calls this accessor. If the pipeline hasn't loaded yet (e.g. running dashboard-only), returns `None` → endpoint returns 409 with `"Dramabox not loaded"`.

## Section 3 — Dashboard UI

### Engine selector

```html
<option value="dramabox">Dramabox</option>
```

Added after the Chatterbox option. `onEngineChange()` hides/shows `#dramabox-controls` the same way it handles Kokoro and Chatterbox panels.

### `#dramabox-controls` panel

```
[ Reference Voice (5–10 sec WAV/MP3) ]   ← file input, same upload endpoint
[ Current: filename.wav ]                 ← ref status line
[ Record ][ Stop ][ 0:00 ]               ← same Record/Stop mechanism, writes dramabox_voice_ref
[ ████████░░░░ ] (level meter canvas)

[ CFG Scale    ] [====●====] 2.5   (range 1.0–5.0, step 0.1)
[ STG Scale    ] [===●=====] 1.5   (range 0.0–3.0, step 0.1)
[ Seed         ] [___42____]       (number input)

[ Apply ]
```

- Reference audio upload calls `POST /api/upload-reference-audio` then `POST /api/config {dramabox_voice_ref: path}` — same upload endpoint, different config key
- Record/Stop writes to `dramabox_voice_ref` config key (not `chatterbox_reference_audio`)
- Apply sends `dramabox_cfg_scale`, `dramabox_stg_scale`, `dramabox_seed` to `POST /api/config`

### Generate Clip section (below controls, inside `#dramabox-controls`)

```
[ Generate Clip                         ]   ← section label
[ Prompt:                               ]
[ ______________________________________]
[ ______________________________________]
[ ______________________________________]

[ Generate ]

Generating… chunk 1 / 3 (est. 18s)         ← progress line, hidden until generating
[ ▶ 0:00 ─────────────── 1:23 ] [⬇ Download]  ← audio player + link, hidden until done
```

- Generate button: disables on click, POSTs to `/api/generate-dramabox`
- Progress updates arrive via existing WebSocket as `dramabox_progress` events → update progress line
- On completion (200 response from POST), show `<audio controls src="/uploads/filename.wav">` and a download anchor
- Output files are served statically — mount `uploads/` via `StaticFiles` in `main.py` at `/uploads` (FastAPI `app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")`); the audio `src` and download `href` use `/uploads/{filename}`

## Error handling

- Dramabox import fails (deps not installed): `_load_dramabox` logs warning, calls `update_config(tts_engine="kokoro")`, falls back to Kokoro — same pattern as Chatterbox
- `generate_to_file` raises mid-generation: endpoint returns HTTP 500, frontend shows error message, re-enables Generate button
- Voice ref missing during live synthesis: `generate()` proceeds without `voice_ref` (Dramabox works without a reference, produces generic voice)
- VRAM OOM: caught in `_load_dramabox`, falls back to Kokoro with a warning

## Testing

- Unit tests mock `TTSServer` (same mock-InputStream pattern used for Chatterbox)
- `test_dramabox_load_failure_falls_back_to_kokoro`: confirms engine resets on import error
- `test_generate_dramabox_endpoint_returns_path`: mocks `generate_to_file`, confirms 200 + JSON
- `test_generate_dramabox_while_not_loaded_returns_409`: confirms guard
- `test_dramabox_config_fields_accepted`: confirms all new fields pass `update_config` validation
- No live model tests (too slow/hardware-dependent); Dramabox synthesis tested manually

## Out of scope

- Streaming audio output during generation (Dramabox generates the full clip then saves — no streaming API)
- Multiple concurrent Dramabox generations (the `TTSServer` is not thread-safe during `generate()`)
- Fine-tuning or model training
- Automatic voice reference selection
