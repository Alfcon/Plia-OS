# VRAM Broker + Studio Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a priority-based VRAM broker that evicts lighter TTS models when a heavy engine (Chatterbox/Dramabox) is requested, surfaces a Studio Mode status bar in the dashboard with a Done button, and exposes Chatterbox's `seed`, `temperature`, and `cfg_weight` parameters.

**Architecture:** `VRAMBroker` (new module-level singleton in `voice/vram_broker.py`) tracks registered models by priority tier (LIGHT=1, HEAVY=3). When a HEAVY model is requested it evicts LIGHT models first, then loads the heavy engine. `release()` unloads the heavy model and restores evicted ones. The dashboard polls `GET /api/vram/status` every 5 seconds and the top of the sidebar shows a compact/expandable status bar. Chatterbox's three new sampling parameters are wired into config, `_synthesise_chatterbox`, and the sidebar controls.

**Tech Stack:** Python dataclasses, torch.cuda (for VRAM query), FastAPI, vanilla JS (existing pattern), pytest + MagicMock.

**Important context:**
- STT (faster-whisper) is **already on CPU** (`device="cpu"`) — no STT eviction logic needed.
- Dramabox (8.52 GB) still exceeds the 7.62 GB card even after evicting Kokoro (0.4 GB). The broker evicts what it can; if load still fails the existing OOM fallback handles it.
- `tts_engine` config defaults to `"dramabox"` (changed in a previous session). The plan does not change this default.

---

## File Structure

| File | Change |
|---|---|
| `voice/vram_broker.py` | Create — VRAMBroker + ModelEntry + get_vram_broker() |
| `tests/test_vram_broker.py` | Create — broker unit tests |
| `core/config.py` | Modify — studio_pipeline_mode, chatterbox_seed/temperature/cfg_weight |
| `voice/tts.py` | Modify — register models with broker, new Chatterbox params |
| `tests/test_chatterbox_params.py` | Create — new Chatterbox param tests |
| `dashboard/server.py` | Modify — GET /api/vram/status, POST /api/vram/release |
| `dashboard/static/index.html` | Modify — VRAM status bar + Chatterbox sliders |

---

### Task 1: VRAMBroker core

**Files:**
- Create: `voice/vram_broker.py`
- Create: `tests/test_vram_broker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_vram_broker.py
import pytest
from unittest.mock import MagicMock, call
from voice.vram_broker import VRAMBroker, ModelEntry, get_vram_broker
import voice.vram_broker as broker_module


@pytest.fixture(autouse=True)
def reset_broker():
    broker_module._broker = None
    yield
    broker_module._broker = None


def _make_entry(name, priority, vram_gb=1.0):
    return ModelEntry(
        name=name,
        priority=priority,
        vram_gb=vram_gb,
        load_fn=MagicMock(),
        unload_fn=MagicMock(),
    )


def test_request_loads_model():
    b = VRAMBroker()
    e = _make_entry("kokoro", 1)
    b.register(e)
    b.request("kokoro")
    e.load_fn.assert_called_once()
    assert e.state == "gpu"


def test_request_noop_if_already_on_gpu():
    b = VRAMBroker()
    e = _make_entry("kokoro", 1)
    b.register(e)
    b.request("kokoro")
    b.request("kokoro")
    e.load_fn.assert_called_once()  # not twice


def test_request_evicts_lower_priority():
    b = VRAMBroker()
    light = _make_entry("kokoro", 1)
    heavy = _make_entry("dramabox", 3, vram_gb=8.5)
    b.register(light)
    b.register(heavy)
    b.request("kokoro")
    b.request("dramabox")
    light.unload_fn.assert_called_once()
    assert light.state == "unloaded"
    assert heavy.state == "gpu"


def test_request_does_not_evict_equal_priority():
    b = VRAMBroker()
    e1 = _make_entry("kokoro", 1)
    e2 = _make_entry("whisper", 1)
    b.register(e1)
    b.register(e2)
    b.request("kokoro")
    b.request("whisper")
    e1.unload_fn.assert_not_called()


def test_second_heavy_releases_first():
    b = VRAMBroker()
    h1 = _make_entry("chatterbox", 3)
    h2 = _make_entry("dramabox", 3)
    b.register(h1)
    b.register(h2)
    b.request("chatterbox")
    b.request("dramabox")
    h1.unload_fn.assert_called_once()
    assert h1.state == "unloaded"
    assert h2.state == "gpu"


def test_release_unloads_and_restores_evicted():
    b = VRAMBroker()
    light = _make_entry("kokoro", 1)
    heavy = _make_entry("dramabox", 3)
    b.register(light)
    b.register(heavy)
    b.request("kokoro")
    b.request("dramabox")   # evicts kokoro
    b.release("dramabox")
    light.load_fn.assert_called()  # restored
    assert light.state == "gpu"
    assert heavy.state == "unloaded"


def test_release_noop_if_unloaded():
    b = VRAMBroker()
    e = _make_entry("dramabox", 3)
    b.register(e)
    b.release("dramabox")   # never loaded — should not raise
    e.unload_fn.assert_not_called()


def test_status_reflects_state():
    b = VRAMBroker()
    e = _make_entry("kokoro", 1, vram_gb=0.4)
    b.register(e)
    b.request("kokoro")
    s = b.status()
    assert s["models"]["kokoro"]["state"] == "gpu"
    assert "vram_total_gb" in s
    assert "studio_mode" in s


def test_status_studio_mode_true_when_heavy_loaded():
    b = VRAMBroker()
    e = _make_entry("chatterbox", 3)
    b.register(e)
    b.request("chatterbox")
    s = b.status()
    assert s["studio_mode"] is True
    assert s["active_heavy"] == "chatterbox"


def test_get_vram_broker_returns_singleton():
    b1 = get_vram_broker()
    b2 = get_vram_broker()
    assert b1 is b2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_vram_broker.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'voice.vram_broker'`

- [ ] **Step 3: Create `voice/vram_broker.py`**

```python
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Callable, Literal

logger = logging.getLogger(__name__)


@dataclass
class ModelEntry:
    name: str
    priority: int          # 1 = LIGHT, 3 = HEAVY
    vram_gb: float
    load_fn: Callable[[], None]
    unload_fn: Callable[[], None]
    state: Literal["gpu", "unloaded"] = "unloaded"


class VRAMBroker:
    def __init__(self) -> None:
        self._models: dict[str, ModelEntry] = {}
        self._evicted: list[str] = []

    def register(self, entry: ModelEntry) -> None:
        self._models[entry.name] = entry

    def request(self, name: str) -> None:
        entry = self._models[name]
        if entry.state == "gpu":
            return

        # Release any active heavy model first
        if entry.priority == 3:
            for m in list(self._models.values()):
                if m.priority == 3 and m.state == "gpu" and m.name != name:
                    logger.info("Releasing active heavy model %r before loading %r", m.name, name)
                    m.unload_fn()
                    m.state = "unloaded"
            self._evicted = []

        # Evict lower-priority models to make room
        for m in sorted(self._models.values(), key=lambda x: x.priority):
            if m.priority < entry.priority and m.state == "gpu":
                logger.info("Evicting %r (priority %d) for %r", m.name, m.priority, name)
                m.unload_fn()
                m.state = "unloaded"
                self._evicted.append(m.name)

        _empty_cuda_cache()
        entry.load_fn()
        entry.state = "gpu"
        logger.info("Loaded %r on GPU", name)

    def release(self, name: str) -> None:
        entry = self._models.get(name)
        if entry is None or entry.state == "unloaded":
            return
        entry.unload_fn()
        entry.state = "unloaded"
        _empty_cuda_cache()
        logger.info("Released %r", name)

        # Restore evicted models in reverse order (highest priority first)
        for evicted_name in reversed(self._evicted):
            m = self._models.get(evicted_name)
            if m and m.state == "unloaded":
                logger.info("Restoring evicted model %r", evicted_name)
                m.load_fn()
                m.state = "gpu"
        self._evicted = []

    def status(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                total = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
                used = torch.cuda.memory_allocated(0) / 1024 ** 3
            else:
                total = used = 0.0
        except Exception:
            total = used = 0.0

        active_heavy = next(
            (m.name for m in self._models.values() if m.priority == 3 and m.state == "gpu"),
            None,
        )
        return {
            "studio_mode": active_heavy is not None,
            "active_heavy": active_heavy,
            "models": {
                m.name: {"state": m.state, "vram_gb": m.vram_gb if m.state == "gpu" else 0.0}
                for m in self._models.values()
            },
            "vram_used_gb": round(used, 2),
            "vram_total_gb": round(total, 2),
        }


def _empty_cuda_cache() -> None:
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


_broker: VRAMBroker | None = None


def get_vram_broker() -> VRAMBroker:
    global _broker
    if _broker is None:
        _broker = VRAMBroker()
    return _broker
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_vram_broker.py -v
```
Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add voice/vram_broker.py tests/test_vram_broker.py
git commit -m "feat: add VRAMBroker for priority-based GPU memory management"
```

---

### Task 2: Config fields

**Files:**
- Modify: `core/config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dramabox.py` (or create `tests/test_chatterbox_params.py`):

```python
# tests/test_chatterbox_params.py
import pytest
from core.config import reset_config, update_config, get_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def test_studio_pipeline_mode_default():
    assert get_config().studio_pipeline_mode == "cpu_stt"


def test_studio_pipeline_mode_accepted():
    update_config(studio_pipeline_mode="pause")
    assert get_config().studio_pipeline_mode == "pause"


def test_chatterbox_seed_default_is_none():
    assert get_config().chatterbox_seed is None


def test_chatterbox_temperature_default():
    assert get_config().chatterbox_temperature == 0.8


def test_chatterbox_cfg_weight_default():
    assert get_config().chatterbox_cfg_weight == 0.5


def test_chatterbox_new_fields_accepted():
    update_config(chatterbox_seed=42, chatterbox_temperature=1.2, chatterbox_cfg_weight=0.7)
    cfg = get_config()
    assert cfg.chatterbox_seed == 42
    assert cfg.chatterbox_temperature == 1.2
    assert cfg.chatterbox_cfg_weight == 0.7


def test_chatterbox_seed_accepts_none():
    update_config(chatterbox_seed=42)
    update_config(chatterbox_seed=None)
    assert get_config().chatterbox_seed is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_chatterbox_params.py -v 2>&1 | head -15
```
Expected: `AttributeError: 'PliaConfig' object has no attribute 'studio_pipeline_mode'`

- [ ] **Step 3: Add fields to `core/config.py`**

Current `core/config.py` ends TTS fields around line 28 with dramabox fields. Add after the last dramabox field:

```python
    # Studio mode
    studio_pipeline_mode: Literal["cpu_stt", "pause"] = "cpu_stt"

    # Chatterbox sampling
    chatterbox_seed: int | None = None
    chatterbox_temperature: float = 0.8
    chatterbox_cfg_weight: float = 0.5
```

The `Literal` import is already at the top of `core/config.py`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_chatterbox_params.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
.venv/bin/pytest --tb=short -q
```
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add core/config.py tests/test_chatterbox_params.py
git commit -m "feat: add studio_pipeline_mode and Chatterbox sampling config fields"
```

---

### Task 3: TTSService broker integration + Chatterbox params

**Files:**
- Modify: `voice/tts.py`
- Modify: `tests/test_chatterbox_params.py` (add TTSService tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chatterbox_params.py`:

```python
import random
import torch
import numpy as np
from unittest.mock import MagicMock, patch, call
import voice.tts as tts_module
from voice.tts import TTSService
import voice.vram_broker as broker_module


@pytest.fixture(autouse=True)
def reset_singletons():
    broker_module._broker = None
    original = getattr(tts_module, '_service', None)
    tts_module._service = None
    yield
    broker_module._broker = None
    tts_module._service = original


def _fake_kokoro_audio():
    mock = MagicMock()
    mock.return_value = iter([(None, None, np.zeros(24000, dtype=np.float32))])
    return mock


def test_kokoro_registered_with_broker():
    from voice.vram_broker import get_vram_broker
    with patch("voice.tts.KPipeline", _fake_kokoro_audio()):
        svc = TTSService()
        svc.load()
    broker = get_vram_broker()
    assert "kokoro" in broker._models
    assert broker._models["kokoro"].state == "gpu"


def test_chatterbox_registered_as_heavy():
    from voice.vram_broker import get_vram_broker
    mock_cb = MagicMock()
    update_config(tts_engine="chatterbox")
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _fake_kokoro_audio()):
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
    broker = get_vram_broker()
    assert "chatterbox" in broker._models
    assert broker._models["chatterbox"].priority == 3


def test_chatterbox_synthesise_passes_new_params():
    mock_cb = MagicMock()
    mock_cb.generate.return_value = torch.zeros(1, 24000)
    update_config(
        tts_engine="chatterbox",
        chatterbox_seed=99,
        chatterbox_temperature=1.5,
        chatterbox_cfg_weight=0.3,
        chatterbox_exaggeration=0.7,
    )
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _fake_kokoro_audio()), \
         patch("torch.manual_seed") as mock_seed:
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        svc.synthesise("hello")
    mock_seed.assert_called_with(99)
    mock_cb.generate.assert_called_once_with(
        "hello",
        audio_prompt_path=None,
        exaggeration=0.7,
        cfg_weight=0.3,
        temperature=1.5,
    )


def test_chatterbox_synthesise_randomises_seed_when_none():
    mock_cb = MagicMock()
    mock_cb.generate.return_value = torch.zeros(1, 24000)
    update_config(tts_engine="chatterbox", chatterbox_seed=None)
    with patch("voice.tts.ChatterboxTTS") as MockCB, \
         patch("voice.tts.KPipeline", _fake_kokoro_audio()), \
         patch("torch.manual_seed") as mock_seed:
        MockCB.from_pretrained.return_value = mock_cb
        svc = TTSService()
        svc.load()
        svc.synthesise("hello")
    # seed was set to some integer (random)
    mock_seed.assert_called_once()
    used_seed = mock_seed.call_args[0][0]
    assert isinstance(used_seed, int)
    assert 0 <= used_seed < 2**31
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_chatterbox_params.py::test_kokoro_registered_with_broker -v
```
Expected: FAIL — broker has no "kokoro" key.

- [ ] **Step 3: Update `voice/tts.py`**

Add import at top:
```python
import random
from voice.vram_broker import get_vram_broker, ModelEntry
```

Replace the `TTSService` class with the updated version. The key changes are:
1. `_load_kokoro` registers + requests via broker
2. `_load_chatterbox` registers + requests via broker
3. `_load_dramabox` registers + requests via broker
4. `_synthesise_chatterbox` uses new params + seed

Full updated `voice/tts.py`:

```python
import logging
import random
import numpy as np
from core.config import get_config, update_config
from voice.vram_broker import get_vram_broker, ModelEntry

logger = logging.getLogger(__name__)

try:
    from kokoro import KPipeline
except ImportError:
    KPipeline = None  # type: ignore[assignment,misc]

try:
    from chatterbox.tts import ChatterboxTTS
except ImportError:
    ChatterboxTTS = None  # type: ignore[assignment,misc]

try:
    from voice.dramabox.wrapper import DramaboxTTS
except Exception:
    DramaboxTTS = None  # type: ignore[assignment,misc]

_service: "TTSService | None" = None


def get_tts_service() -> "TTSService | None":
    return _service


class TTSService:
    def __init__(self) -> None:
        self._kokoro = None
        self._chatterbox = None
        self._dramabox = None
        self._loaded = False

    def load(self) -> None:
        global _service
        config = get_config()
        if config.tts_engine == "dramabox":
            self._load_dramabox(config)
        if config.tts_engine == "chatterbox":
            self._load_chatterbox(config)
        if get_config().tts_engine == "kokoro":
            self._load_kokoro(get_config())
        self._loaded = True
        _service = self

    def _load_kokoro(self, config) -> None:
        broker = get_vram_broker()
        lang_code = config.kokoro_voice[0] if config.kokoro_voice else "a"

        def _do_load():
            self._kokoro = KPipeline(lang_code=lang_code)
            self._kokoro_lang = lang_code

        def _do_unload():
            self._kokoro = None

        broker.register(ModelEntry(
            name="kokoro", priority=1, vram_gb=0.4,
            load_fn=_do_load, unload_fn=_do_unload,
        ))
        broker.request("kokoro")

    def _ensure_kokoro(self) -> None:
        if self._kokoro is None:
            self._load_kokoro(get_config())

    def _load_chatterbox(self, config) -> None:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            cb_instance = ChatterboxTTS.from_pretrained(device=device)
        except Exception:
            logger.warning("Chatterbox failed to load; Kokoro will be used", exc_info=True)
            update_config(tts_engine="kokoro")
            return

        broker = get_vram_broker()

        def _do_load():
            self._chatterbox = cb_instance

        def _do_unload():
            self._chatterbox = None

        broker.register(ModelEntry(
            name="chatterbox", priority=3, vram_gb=2.0,
            load_fn=_do_load, unload_fn=_do_unload,
        ))
        broker.request("chatterbox")

    def _load_dramabox(self, config) -> None:
        if DramaboxTTS is None:
            logger.warning("Dramabox not available (missing deps); using Kokoro")
            update_config(tts_engine="kokoro")
            return
        try:
            db_instance = DramaboxTTS()
            db_instance.load()
        except Exception:
            logger.warning("Dramabox failed to load; Kokoro will be used", exc_info=True)
            self._dramabox = None
            update_config(tts_engine="kokoro")
            return

        broker = get_vram_broker()

        def _do_load():
            self._dramabox = db_instance

        def _do_unload():
            self._dramabox = None

        broker.register(ModelEntry(
            name="dramabox", priority=3, vram_gb=8.52,
            load_fn=_do_load, unload_fn=_do_unload,
        ))
        broker.request("dramabox")

    def synthesise(self, text: str) -> np.ndarray:
        if not self._loaded:
            raise RuntimeError("Call load() before synthesise()")
        config = get_config()
        if config.tts_engine == "dramabox":
            if self._dramabox is None:
                logger.info("Loading Dramabox on demand...")
                self._load_dramabox(config)
            if self._dramabox is not None:
                return self._synthesise_dramabox(text)
        if config.tts_engine == "chatterbox":
            if self._chatterbox is None:
                logger.info("Loading Chatterbox on demand...")
                self._load_chatterbox(config)
            if self._chatterbox is not None:
                return self._synthesise_chatterbox(text)
        return self._synthesise_kokoro(text)

    def _synthesise_kokoro(self, text: str) -> np.ndarray:
        config = get_config()
        lang_code = config.kokoro_voice[0] if config.kokoro_voice else "a"
        if lang_code != getattr(self, "_kokoro_lang", None):
            logger.info("Reloading Kokoro for lang_code=%r", lang_code)
            self._load_kokoro(config)
        chunks = [
            audio
            for _, _, audio in self._kokoro(
                text, voice=config.kokoro_voice, speed=config.kokoro_speed
            )
            if audio is not None
        ]
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

    def _synthesise_chatterbox(self, text: str) -> np.ndarray:
        try:
            import torch
            config = get_config()
            seed = config.chatterbox_seed
            if seed is None:
                seed = random.randint(0, 2**31 - 1)
            torch.manual_seed(seed)
            wav = self._chatterbox.generate(
                text,
                audio_prompt_path=config.chatterbox_reference_audio,
                exaggeration=config.chatterbox_exaggeration,
                cfg_weight=config.chatterbox_cfg_weight,
                temperature=config.chatterbox_temperature,
            )
            return wav.squeeze().numpy()
        except Exception:
            logger.warning("Chatterbox synthesis failed; falling back to Kokoro", exc_info=True)
            self._ensure_kokoro()
            return self._synthesise_kokoro(text)

    def _synthesise_dramabox(self, text: str) -> np.ndarray:
        try:
            import torchaudio
            waveform, sr = self._dramabox.synthesise(text)  # (C, T) tensor, sr=48000
            resampled = torchaudio.functional.resample(waveform, sr, 24000)
            if resampled.dim() > 1:
                resampled = resampled.mean(dim=0)
            return resampled.numpy().astype(np.float32)
        except Exception:
            logger.warning("Dramabox synthesis failed; falling back to Kokoro", exc_info=True)
            self._ensure_kokoro()
            return self._synthesise_kokoro(text)
```

- [ ] **Step 4: Run new tests**

```bash
.venv/bin/pytest tests/test_chatterbox_params.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```
Expected: all tests pass. (The existing `test_dramabox.py` tests may need the `reset_singletons` fixture to also reset `broker_module._broker = None` — if any fail with broker state bleed-through, add `import voice.vram_broker as broker_module; broker_module._broker = None` to the `reset_tts_singleton` fixture in `test_dramabox.py`.)

- [ ] **Step 6: Commit**

```bash
git add voice/tts.py tests/test_chatterbox_params.py
git commit -m "feat: integrate TTSService with VRAMBroker and add Chatterbox seed/temperature/cfg_weight"
```

---

### Task 4: VRAM API endpoints

**Files:**
- Modify: `dashboard/server.py`
- Modify: `tests/test_vram_broker.py` (add endpoint tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vram_broker.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from unittest.mock import patch, MagicMock
from dashboard.server import router
from core.config import reset_config as _reset_config


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture(autouse=True)
def reset_cfg():
    yield
    _reset_config()


async def test_vram_status_returns_dict(app):
    mock_broker = MagicMock()
    mock_broker.status.return_value = {
        "studio_mode": False, "active_heavy": None,
        "models": {}, "vram_used_gb": 0.5, "vram_total_gb": 7.6,
    }
    with patch("dashboard.server.get_vram_broker", return_value=mock_broker):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/vram/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "studio_mode" in data
    assert "vram_total_gb" in data


async def test_vram_release_calls_broker_and_reverts_config(app):
    mock_broker = MagicMock()
    mock_broker.status.return_value = {
        "studio_mode": False, "active_heavy": None,
        "models": {}, "vram_used_gb": 0.0, "vram_total_gb": 7.6,
    }
    with patch("dashboard.server.get_vram_broker", return_value=mock_broker):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/vram/release", json={"name": "dramabox"})
    assert resp.status_code == 200
    mock_broker.release.assert_called_once_with("dramabox")


async def test_vram_release_unknown_name_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/vram/release", json={})
    assert resp.status_code == 422


async def test_vram_release_reverts_tts_engine_to_kokoro(app):
    from core.config import update_config, get_config
    update_config(tts_engine="dramabox")
    mock_broker = MagicMock()
    mock_broker.status.return_value = {
        "studio_mode": False, "active_heavy": None,
        "models": {}, "vram_used_gb": 0.0, "vram_total_gb": 7.6,
    }
    with patch("dashboard.server.get_vram_broker", return_value=mock_broker):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/vram/release", json={"name": "dramabox"})
    assert get_config().tts_engine == "kokoro"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_vram_broker.py::test_vram_status_returns_dict -v
```
Expected: FAIL — route not found.

- [ ] **Step 3: Update `dashboard/server.py`**

Add import at top (with existing imports):
```python
from voice.vram_broker import get_vram_broker
```

Add two new endpoints after the existing `/api/generate-dramabox` endpoint:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_vram_broker.py -v
```
Expected: all tests PASS (both broker unit tests and endpoint tests).

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add dashboard/server.py tests/test_vram_broker.py
git commit -m "feat: add GET /api/vram/status and POST /api/vram/release endpoints"
```

---

### Task 5: Dashboard UI — VRAM status bar

**Files:**
- Modify: `dashboard/static/index.html`

No automated tests for UI — verify manually by opening http://localhost:8000 after the server starts.

- [ ] **Step 1: Add CSS for the status bar**

Inside the `<style>` block in `index.html`, append before the closing `</style>`:

```css
    #vram-bar { padding: 8px 10px; border-bottom: 1px solid #333; font-size: 0.75rem; cursor: pointer; }
    #vram-bar .vram-row { display: flex; align-items: center; gap: 8px; }
    #vram-bar .vram-track { flex: 1; height: 5px; background: #333; border-radius: 3px; overflow: hidden; }
    #vram-bar .vram-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
    #vram-bar .vram-fill.normal { background: #4ade80; }
    #vram-bar .vram-fill.studio { background: #7c3aed; }
    #vram-bar-detail { display: none; margin-top: 8px; padding-top: 8px; border-top: 1px solid #222; }
    #vram-bar.studio-mode { border-color: #7c3aed; }
    #vram-bar-detail .model-row { display: flex; justify-content: space-between; padding: 2px 0; color: #aaa; }
    #vram-bar-detail .model-row .model-name { color: #ccc; }
    #vram-done-btn { width: 100%; margin-top: 8px; background: #7f1d1d; color: #fca5a5; border: 1px solid #991b1b; }
    #vram-done-btn:hover { background: #991b1b; }
    #vram-pipeline-toggle { display: flex; gap: 4px; margin-top: 6px; font-size: 0.7rem; }
    #vram-pipeline-toggle button { width: auto; padding: 3px 8px; font-size: 0.7rem; }
    #vram-pipeline-toggle button.active { background: #1e3a5f; }
```

- [ ] **Step 2: Add VRAM status bar HTML**

In `index.html`, find the opening `<aside>` tag (line 31). Insert the VRAM bar as the very first child of `<aside>`, before the `<!-- Status -->` section:

```html
  <!-- VRAM Status Bar -->
  <div id="vram-bar" onclick="toggleVramDetail()">
    <div class="vram-row">
      <span id="vram-dot" style="font-size:0.9rem;">●</span>
      <span id="vram-label" style="color:#888;">VRAM</span>
      <div class="vram-track">
        <div id="vram-fill" class="vram-fill normal" style="width:0%"></div>
      </div>
      <span id="vram-text" style="color:#555;">— GB</span>
      <span id="vram-chevron" style="color:#555;">▼</span>
    </div>
    <div id="vram-bar-detail">
      <div id="vram-model-list"></div>
      <div id="vram-pipeline-toggle" style="display:none">
        <span style="color:#888;align-self:center;">Pipeline:</span>
        <button id="vram-pl-active" class="active" onclick="setStudioPipeline('cpu_stt',event)">Active</button>
        <button id="vram-pl-pause" onclick="setStudioPipeline('pause',event)">Pause</button>
      </div>
      <button id="vram-done-btn" style="display:none" onclick="releaseStudioModel(event)">✓ Done</button>
    </div>
  </div>
```

- [ ] **Step 3: Add VRAM JavaScript**

Find the `<script>` tag in `index.html` and add these functions (before the closing `</script>`):

```javascript
// --- VRAM Status Bar ---
let _vramDetailOpen = false;
let _vramPollInterval = null;
let _activeHeavyModel = null;

function toggleVramDetail() {
  _vramDetailOpen = !_vramDetailOpen;
  document.getElementById('vram-bar-detail').style.display = _vramDetailOpen ? 'block' : 'none';
  document.getElementById('vram-chevron').textContent = _vramDetailOpen ? '▲' : '▼';
}

function updateVramBar(data) {
  const fill = document.getElementById('vram-fill');
  const dot = document.getElementById('vram-dot');
  const label = document.getElementById('vram-label');
  const text = document.getElementById('vram-text');
  const bar = document.getElementById('vram-bar');
  const doneBtn = document.getElementById('vram-done-btn');
  const pipelineToggle = document.getElementById('vram-pipeline-toggle');

  const total = data.vram_total_gb || 0;
  const used = data.vram_used_gb || 0;
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;

  fill.style.width = pct + '%';
  text.textContent = total > 0 ? `${used.toFixed(1)} / ${total.toFixed(1)} GB` : '— GB';

  _activeHeavyModel = data.active_heavy || null;

  if (data.studio_mode) {
    fill.className = 'vram-fill studio';
    dot.style.color = '#f59e0b';
    label.textContent = 'STUDIO';
    label.style.color = '#a78bfa';
    bar.classList.add('studio-mode');
    doneBtn.style.display = 'block';
    doneBtn.textContent = `✓ Done — Release ${(_activeHeavyModel || 'engine').charAt(0).toUpperCase() + (_activeHeavyModel || 'engine').slice(1)}`;
    pipelineToggle.style.display = 'flex';
    if (!_vramDetailOpen) {
      _vramDetailOpen = true;
      document.getElementById('vram-bar-detail').style.display = 'block';
      document.getElementById('vram-chevron').textContent = '▲';
    }
  } else {
    fill.className = 'vram-fill normal';
    dot.style.color = '#4ade80';
    label.textContent = 'VRAM';
    label.style.color = '#888';
    bar.classList.remove('studio-mode');
    doneBtn.style.display = 'none';
    pipelineToggle.style.display = 'none';
  }

  // Update model list
  const list = document.getElementById('vram-model-list');
  list.innerHTML = '';
  for (const [name, info] of Object.entries(data.models || {})) {
    const row = document.createElement('div');
    row.className = 'model-row';
    const stateColor = info.state === 'gpu' ? '#4ade80' : info.state === 'cpu' ? '#f59e0b' : '#555';
    row.innerHTML = `<span class="model-name" style="color:${stateColor}">● ${name}</span>` +
                    `<span>${info.state === 'gpu' ? info.vram_gb.toFixed(2) + ' GB GPU' : info.state}</span>`;
    list.appendChild(row);
  }
}

async function pollVramStatus() {
  try {
    const r = await fetch('/api/vram/status');
    if (r.ok) updateVramBar(await r.json());
  } catch (_) {}
}

function startVramPolling() {
  pollVramStatus();
  _vramPollInterval = setInterval(pollVramStatus, 5000);
}

async function releaseStudioModel(e) {
  e.stopPropagation();
  if (!_activeHeavyModel) return;
  const btn = document.getElementById('vram-done-btn');
  btn.disabled = true;
  btn.textContent = 'Releasing…';
  try {
    await fetch('/api/vram/release', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: _activeHeavyModel}),
    });
    await pollVramStatus();
    // Also reload config so engine select updates
    const cfg = await fetch('/api/config').then(r => r.json());
    document.getElementById('tts-engine').value = cfg.tts_engine || 'kokoro';
    onEngineChange();
  } finally {
    btn.disabled = false;
  }
}

async function setStudioPipeline(mode, e) {
  e.stopPropagation();
  await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({studio_pipeline_mode: mode}),
  });
  document.getElementById('vram-pl-active').classList.toggle('active', mode === 'cpu_stt');
  document.getElementById('vram-pl-pause').classList.toggle('active', mode === 'pause');
}
```

- [ ] **Step 4: Wire `startVramPolling()` into page init**

Find the existing page load / WebSocket setup in the `<script>` block (look for `window.onload` or where the WebSocket is created and config is initially loaded). Call `startVramPolling()` there:

```javascript
// Add inside existing init / window.onload block:
startVramPolling();
```

Also add handling for `vram_status` WebSocket events in the `ws.onmessage` handler:

```javascript
// Inside ws.onmessage, add a case:
} else if (d.type === 'vram_status') {
  updateVramBar(d);
}
```

- [ ] **Step 5: Verify manually**

Start the server:
```bash
.venv/bin/python -m core.main 2>&1 &
```
Open http://localhost:8000. Verify:
- VRAM bar appears at the top of the sidebar
- Shows green dot and GB reading (or `— GB` if no CUDA)
- Clicking the bar toggles detail view

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: add VRAM status bar to dashboard sidebar"
```

---

### Task 6: Dashboard UI — Chatterbox sliders

**Files:**
- Modify: `dashboard/static/index.html`

- [ ] **Step 1: Add Chatterbox slider HTML**

In `index.html`, find the `#chatterbox-controls` section. Currently it ends with the Exaggeration slider and then the Apply button. Add the new sliders between Exaggeration and Apply:

Find this block (around line 76–79):
```html
      <label>Exaggeration
        <input type="range" id="cb-exag" min="0" max="1" step="0.05" value="0.5" />
      </label>
```

After it, insert:
```html
      <label>CFG Weight <span style="font-size:0.7rem;color:#555;">— voice ref strength</span>
        <input type="range" id="cb-cfg" min="0" max="1" step="0.05" value="0.5" />
      </label>
      <label>Temperature <span style="font-size:0.7rem;color:#555;">— sampling creativity</span>
        <input type="range" id="cb-temp" min="0.1" max="2.0" step="0.05" value="0.8" />
      </label>
      <label>Seed <span style="font-size:0.7rem;color:#555;">— blank = random each time</span></label>
      <div style="display:flex;gap:6px;margin-bottom:6px;">
        <input type="number" id="cb-seed" placeholder="random" style="flex:1;" />
        <button onclick="randomiseCbSeed()" style="width:auto;padding:6px 8px;">🎲</button>
      </div>
```

- [ ] **Step 2: Update `applyVoiceConfig()` JS function**

Find the existing `applyVoiceConfig()` function in the `<script>` block. It currently sends `chatterbox_exaggeration` to `/api/config`. Add the three new fields:

```javascript
// Inside applyVoiceConfig(), in the chatterbox branch, add:
const cbSeedRaw = document.getElementById('cb-seed').value.trim();
const cbSeed = cbSeedRaw === '' ? null : parseInt(cbSeedRaw, 10);

// Include in the fetch body for chatterbox:
chatterbox_cfg_weight: parseFloat(document.getElementById('cb-cfg').value),
chatterbox_temperature: parseFloat(document.getElementById('cb-temp').value),
chatterbox_seed: cbSeed,
```

- [ ] **Step 3: Add `randomiseCbSeed()` JS function**

```javascript
function randomiseCbSeed() {
  document.getElementById('cb-seed').value = Math.floor(Math.random() * 2147483647);
}
```

- [ ] **Step 4: Update config loader to populate new fields**

Find the section in the script that loads config on page init and populates the Chatterbox inputs (look for where `cb-exag` is set). Add:

```javascript
// After setting cb-exag value:
if (cfg.chatterbox_cfg_weight !== undefined)
  document.getElementById('cb-cfg').value = cfg.chatterbox_cfg_weight;
if (cfg.chatterbox_temperature !== undefined)
  document.getElementById('cb-temp').value = cfg.chatterbox_temperature;
if (cfg.chatterbox_seed !== null && cfg.chatterbox_seed !== undefined)
  document.getElementById('cb-seed').value = cfg.chatterbox_seed;
```

- [ ] **Step 5: Verify manually**

Open http://localhost:8000, switch engine to Chatterbox. Verify:
- CFG Weight, Temperature sliders appear
- Seed number input + 🎲 button appear
- Apply button sends the new values (check Network tab)

- [ ] **Step 6: Run full test suite**

```bash
.venv/bin/pytest --tb=short -q
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: add Chatterbox CFG weight, temperature, and seed controls to dashboard"
```

---

## Self-Review

**Spec coverage:**
- ✅ VRAMBroker with priority tiers → Task 1
- ✅ `studio_pipeline_mode`, Chatterbox new config fields → Task 2
- ✅ TTSService broker integration + Chatterbox params → Task 3
- ✅ GET /api/vram/status, POST /api/vram/release → Task 4
- ✅ Top status bar, studio mode expand, Done button, pipeline toggle → Task 5
- ✅ Chatterbox CFG/Temp/Seed sliders → Task 6
- ✅ `status()` reads `torch.cuda.get_device_properties(0).total_memory` at runtime → VRAMBroker.status()
- ✅ `_do_unload_*` do not call `empty_cache` (broker handles it) → Task 3
- ✅ vram_status WebSocket event → Task 4 (`_broadcast`) + Task 5 (`ws.onmessage`)

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:**
- `ModelEntry` defined in Task 1, imported and used in Task 3 — matches.
- `get_vram_broker()` defined in Task 1, imported in Tasks 3 and 4 — matches.
- `broker.release(name)` called with string in Task 4 — matches Task 1 signature.
- `updateVramBar(data)` called from `pollVramStatus` and `ws.onmessage` — both pass the same JSON shape from `/api/vram/status`.
