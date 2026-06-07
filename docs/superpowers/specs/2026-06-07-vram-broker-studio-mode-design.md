# VRAM Broker + Studio Mode Design

**Date:** 2026-06-07
**Status:** Approved

## Overview

Introduce a priority-based VRAM broker so Plia-OS can load heavyweight TTS engines (Dramabox at 8.5 GB, Chatterbox at ~2 GB) on a 7.62 GB GPU that also hosts Whisper STT and Kokoro. When a heavy engine is requested the broker evicts lower-priority models to GPU or CPU as needed, shows a persistent "Studio Mode" status bar with a Done button, and restores the previous allocation when the user is finished.

Scope: applies to both on-demand clip generation and live engine switching.

Additionally, expose Chatterbox's `seed`, `temperature`, and `cfg_weight` sampling parameters in the dashboard controls panel (matching the pattern already in place for Dramabox).

---

## Hardware Context

- GPU: RTX 4060 Mobile — 7.62 GB VRAM
- Dramabox DiT + VAE: 6.58 + 1.94 = **8.52 GB** → must evict STT + Kokoro from GPU
- Chatterbox: ~2 GB → likely fits alongside STT; broker evicts only if needed
- Gemma 3 12B (4-bit): ~23 GB CPU RAM — never on GPU, unaffected
- Whisper STT (base): ~0.8 GB GPU → has CPU fallback (slower but functional)
- Kokoro: ~0.4 GB GPU → fully unloads, reloads quickly

---

## Priority Tiers

| Priority | Tier | Models |
|---|---|---|
| 3 — HEAVY | studio | Dramabox, Chatterbox |
| 2 — STANDARD | normal | Whisper STT |
| 1 — LIGHT | normal | Kokoro |

When a HEAVY model is requested the broker evicts LIGHT models entirely and demotes STANDARD models to CPU fallback (if `can_cpu_fallback=True`). When a second HEAVY model is requested while one is already active, the first is released before loading the second.

---

## Section 1 — `voice/vram_broker.py` (new)

### Class: `VRAMBroker`

Module-level singleton exposed via `get_vram_broker() -> VRAMBroker`.

```python
@dataclass
class ModelEntry:
    name: str
    priority: int          # 1=LIGHT, 2=STANDARD, 3=HEAVY
    vram_gb: float
    load_fn: Callable      # loads model to GPU
    unload_fn: Callable    # unloads model, frees VRAM
    cpu_fallback_fn: Callable | None  # reloads on CPU; None = fully unloads
    state: Literal["gpu", "cpu", "unloaded"]
```

#### `VRAMBroker.register(entry: ModelEntry) -> None`
Register a model. Idempotent — re-registering replaces the entry. Called once per model during TTSService/pipeline load.

#### `VRAMBroker.request(name: str) -> None`
Ensure `name` is loaded on GPU. Algorithm:
1. If already on GPU: no-op.
2. If a HEAVY model is already active and `name` is also HEAVY: call `release()` on the active HEAVY model first.
3. Evict all models with `priority < entry.priority` in ascending priority order:
   - If model has `cpu_fallback_fn` and config says `studio_pipeline_mode == "cpu_stt"`: call `cpu_fallback_fn` (move to CPU).
   - Otherwise: call `unload_fn` (fully unload).
4. Call `entry.load_fn()`.
5. Run `torch.cuda.empty_cache()`.
6. Broadcast `vram_status` event via event bus.

#### `VRAMBroker.release(name: str) -> None`
Explicit release of a named model:
1. Call `entry.unload_fn()`.
2. Run `torch.cuda.empty_cache()`.
3. Reload all previously evicted models (call `load_fn()` for each, in descending priority order).
4. Broadcast `vram_status` event.

#### `VRAMBroker.status() -> dict`
Returns:
```json
{
  "studio_mode": true,
  "active_heavy": "dramabox",
  "models": {
    "dramabox": {"state": "gpu", "vram_gb": 8.52},
    "stt":      {"state": "cpu", "vram_gb": 0},
    "kokoro":   {"state": "unloaded", "vram_gb": 0}
  },
  "vram_used_gb": 8.52,
  "vram_total_gb": 7.62    // read from torch.cuda.get_device_properties(0).total_memory at runtime
}
```

---

## Section 2 — `core/config.py` changes

New fields:

```python
# Studio mode
studio_pipeline_mode: Literal["cpu_stt", "pause"] = "cpu_stt"

# Chatterbox sampling (new)
chatterbox_seed: int | None = None          # None = random each generation
chatterbox_temperature: float = 0.8
chatterbox_cfg_weight: float = 0.5
```

`chatterbox_seed = None` means a fresh `torch.manual_seed(random.randint(...))` is called before each `generate()` call, matching Chatterbox playground behaviour. A fixed integer gives reproducible output.

---

## Section 3 — `voice/tts.py` changes

Each `_load_*` method registers its model with the broker and requests allocation:

```python
# in _load_kokoro:
broker.register(ModelEntry(
    name="kokoro", priority=1, vram_gb=0.4,
    load_fn=self._do_load_kokoro,
    unload_fn=self._do_unload_kokoro,
    cpu_fallback_fn=None,
    state="unloaded",
))
broker.request("kokoro")

# in _load_chatterbox:
broker.register(ModelEntry(
    name="chatterbox", priority=3, vram_gb=2.0,
    load_fn=self._do_load_chatterbox,
    unload_fn=self._do_unload_chatterbox,
    cpu_fallback_fn=None,
    state="unloaded",
))
broker.request("chatterbox")

# in _load_dramabox:
broker.register(ModelEntry(
    name="dramabox", priority=3, vram_gb=8.52,
    load_fn=self._do_load_dramabox,
    unload_fn=self._do_unload_dramabox,
    cpu_fallback_fn=None,
    state="unloaded",
))
broker.request("dramabox")
```

`_do_unload_*` methods set `self._kokoro = None` / `self._chatterbox = None` / `self._dramabox = None`. The broker calls `torch.cuda.empty_cache()` after all evictions complete — unload functions do not call it themselves.

**Chatterbox `_synthesise_chatterbox` updated** to pass new config fields:

```python
import random, torch
config = get_config()
seed = config.chatterbox_seed
if seed is None:
    seed = random.randint(0, 2**31)
torch.manual_seed(seed)
wav = self._chatterbox.generate(
    text,
    cfg_weight=config.chatterbox_cfg_weight,
    temperature=config.chatterbox_temperature,
    exaggeration=config.chatterbox_exaggeration,
)
```

---

## Section 4 — `voice/pipeline.py` changes

STT registration with broker:

```python
broker.register(ModelEntry(
    name="stt", priority=2, vram_gb=0.8,
    load_fn=self._do_load_stt_gpu,
    unload_fn=self._do_unload_stt,
    cpu_fallback_fn=self._do_load_stt_cpu,
    state="unloaded",
))
broker.request("stt")
```

`_do_load_stt_cpu`: reloads `WhisperModel(..., device="cpu", compute_type="int8")`.

When `studio_pipeline_mode == "pause"`: broker's `request()` skips the `cpu_fallback_fn` and fully unloads STT. The pipeline's `_transcribe()` method checks if STT is loaded and returns empty string if not (pipeline stays silent but doesn't crash).

---

## Section 5 — `dashboard/server.py` changes

Two new endpoints:

```python
GET  /api/vram/status   → broker.status()
POST /api/vram/release  → body: {"name": "dramabox"|"chatterbox"}
                        → broker.release(name), broadcast vram_status
```

Broker broadcasts `vram_status` events via the existing `_broadcast()` mechanism whenever allocations change (on `request()` and `release()`).

---

## Section 6 — `dashboard/static/index.html` changes

### Top VRAM status bar

Always visible above the engine selector. Two states:

**Compact (normal mode):**
```
● VRAM  [████░░░░░░░░░░░░]  1.2 / 7.6 GB   ▼ details
```

**Expanded (studio mode — auto-expands when heavy model loads):**
```
● STUDIO MODE  [████████████████░]  7.1 / 7.6 GB   ▲ collapse

  🟣 Dramabox DiT   6.58 GB GPU    🟣 Dramabox VAE  1.94 GB GPU
  🟡 Whisper STT    CPU fallback   ⚫ Kokoro TTS     unloaded
  🔵 Gemma 12B      CPU RAM

  Pipeline: [CPU STT on] [Pause]        [✓ Done — Release Dramabox]
```

Status bar listens for `vram_status` WebSocket events and updates live. Clicking the bar header toggles compact/expanded. In studio mode it auto-expands on entry and the Done button calls `POST /api/vram/release`.

### Chatterbox controls — new sliders

Inside `#chatterbox-controls`, below existing Exaggeration slider:

- **CFG Weight** — range 0.0–1.0, step 0.05, default 0.50
- **Temperature** — range 0.1–2.0, step 0.05, default 0.80
- **Seed** — number input + 🎲 Random button (sets field to `""` → backend treats as `null`)

Apply button sends `chatterbox_cfg_weight`, `chatterbox_temperature`, `chatterbox_seed` (or `null`) to `POST /api/config`.

---

## Error Handling

- **OOM during broker request**: caught in `load_fn`, logged, engine falls back to Kokoro. Dashboard shows warning via `vram_status` event with `error` field.
- **Release while generating**: `POST /api/vram/release` returns 409 if a synthesis is actively running. Frontend disables Done button during generation.
- **STT unavailable on CPU**: if both `cpu_fallback_fn` fails and pipeline mode is `cpu_stt`, STT silently returns empty transcript (pipeline stays alive, just deaf).
- **Pipeline mode `pause`**: wake word engine continues listening but STT returns empty → Plia doesn't respond. Visual indicator in status bar: "Listening paused".

---

## Testing

- `test_vram_broker.py`:
  - `test_request_evicts_lower_priority`: HEAVY request causes LIGHT model to unload
  - `test_request_cpu_fallback`: STANDARD model moves to CPU when cpu_fallback_fn provided
  - `test_release_restores_evicted`: release reloads previously evicted models in order
  - `test_second_heavy_releases_first`: requesting second HEAVY model releases first
  - `test_status_returns_correct_state`: status dict reflects current allocations
- `test_chatterbox_params.py`:
  - `test_new_config_fields_accepted`
  - `test_seed_none_randomises`
  - `test_fixed_seed_passes_to_generate`
  - `test_cfg_weight_temperature_pass_to_generate`
- Endpoint tests in `test_dashboard.py`:
  - `test_vram_status_endpoint`
  - `test_vram_release_endpoint_calls_broker`
  - `test_vram_release_returns_409_while_generating`

---

## Out of Scope

- Post-processing pitch shift or time stretch (no native support in any engine)
- Automatic idle-timeout eviction (user controls release explicitly via Done)
- Concurrent heavy model sessions
- VRAM allocation for wake word model (already CPU-only via onnxruntime)
