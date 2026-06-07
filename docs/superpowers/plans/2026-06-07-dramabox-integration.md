# Dramabox TTS Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate ResembleAI's Dramabox TTS as a 4th engine in Plia-OS, available both as a live voice pipeline engine and an on-demand dashboard clip generator.

**Architecture:** Vendor the Dramabox HF Space `src/` and `ltx2/` trees into `voice/dramabox/`. A `DramaboxTTS` wrapper class in `voice/dramabox/wrapper.py` owns model loading (TTSServer) and exposes `synthesise()` for the live pipeline and `generate_to_file()` for the dashboard. TTSService in `voice/tts.py` dispatches to it when `tts_engine == "dramabox"`, and a module-level singleton lets the dashboard API endpoint share the already-loaded server.

**Tech Stack:** PyTorch/torchaudio, safetensors, bitsandbytes (4-bit Gemma), accelerate, LTX-2.3 DiT transformer, resemble-perth watermarking, FastAPI StaticFiles.

---

## File Map

| File | Action |
|------|--------|
| `scripts/vendor_dramabox.py` | Create — downloads HF space, copies src/ and ltx2/ |
| `voice/dramabox/__init__.py` | Create — package marker |
| `voice/dramabox/wrapper.py` | Create — DramaboxTTS class |
| `voice/dramabox/src/` | Populated by vendor script (committed) |
| `voice/dramabox/ltx2/` | Populated by vendor script (committed) |
| `core/config.py` | Modify — 6 new fields, expand Literal |
| `voice/tts.py` | Modify — singleton, _load_dramabox, _synthesise_dramabox |
| `dashboard/server.py` | Modify — target param on upload/record, POST /api/generate-dramabox |
| `core/main.py` | Modify — mount /uploads StaticFiles |
| `dashboard/static/index.html` | Modify — Dramabox engine option, controls, clip generator |
| `pyproject.toml` | Modify — [dramabox] optional deps |
| `tests/test_dramabox.py` | Create — all new unit tests |

---

## Task 1: Vendoring script and directory scaffold

**Files:**
- Create: `scripts/vendor_dramabox.py`
- Create: `voice/dramabox/__init__.py`

- [ ] **Step 1: Create `voice/dramabox/__init__.py`**

```python
```
(empty file — just a package marker)

- [ ] **Step 2: Create `scripts/vendor_dramabox.py`**

```python
#!/usr/bin/env python3
"""
Download the ResembleAI/Dramabox HF Space and copy src/ and ltx2/ into
voice/dramabox/. Run once to vendor the inference code.

    python scripts/vendor_dramabox.py
"""
import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "ResembleAI/Dramabox"
EXCLUDE_FILES = {"train.py", "validate.py"}

ROOT = Path(__file__).parent.parent
DEST_BASE = ROOT / "voice" / "dramabox"


def _copy_tree(src: Path, dst: Path, exclude: set[str] = frozenset()) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in src.rglob("*"):
        if item.name in exclude:
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            count += 1
    return count


def main() -> None:
    print(f"Downloading {REPO_ID} snapshot...")
    snapshot = Path(
        snapshot_download(
            repo_id=REPO_ID,
            repo_type="space",
            token=None,
            ignore_patterns=["*.safetensors", "*.pt", "*.bin", "*.mp3", "*.wav"],
        )
    )
    print(f"Snapshot at: {snapshot}")

    for tree in ("src", "ltx2"):
        src = snapshot / tree
        dst = DEST_BASE / tree
        if not src.is_dir():
            print(f"  WARNING: {tree}/ not found in snapshot, skipping")
            continue
        n = _copy_tree(src, dst, exclude=EXCLUDE_FILES)
        init = dst / "__init__.py"
        if not init.exists():
            init.write_text("")
        print(f"  Copied {n} files → {dst}")

    print("Done. Commit voice/dramabox/src/ and voice/dramabox/ltx2/ to git.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the vendoring script**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python scripts/vendor_dramabox.py
```

Expected: prints "Done." and creates `voice/dramabox/src/` and `voice/dramabox/ltx2/`.

- [ ] **Step 4: Verify key files are present**

```bash
ls voice/dramabox/src/
# expect: inference_server.py model_downloader.py text_chunker.py
#         audio_conditioning.py duration_estimator.py preprocess.py
#         super_resolution.py __init__.py

ls voice/dramabox/ltx2/
# expect: ltx_core/ ltx_pipelines/ __init__.py (or similar)
```

- [ ] **Step 5: Commit scaffold**

```bash
git add voice/dramabox/ scripts/vendor_dramabox.py
git commit -m "feat: vendor Dramabox src/ and ltx2/ from ResembleAI/Dramabox space"
```

---

## Task 2: Config fields

**Files:**
- Modify: `core/config.py`
- Test: `tests/test_dramabox.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dramabox.py`:

```python
import pytest
from core.config import reset_config, update_config, get_config


@pytest.fixture(autouse=True)
def clean_config():
    reset_config()
    yield
    reset_config()


def test_dramabox_config_fields_accepted():
    update_config(
        tts_engine="dramabox",
        dramabox_voice_ref="/tmp/ref.wav",
        dramabox_cfg_scale=3.0,
        dramabox_stg_scale=2.0,
        dramabox_seed=123,
        dramabox_duration_multiplier=1.2,
    )
    cfg = get_config()
    assert cfg.tts_engine == "dramabox"
    assert cfg.dramabox_voice_ref == "/tmp/ref.wav"
    assert cfg.dramabox_cfg_scale == 3.0
    assert cfg.dramabox_stg_scale == 2.0
    assert cfg.dramabox_seed == 123
    assert cfg.dramabox_duration_multiplier == 1.2


def test_dramabox_config_defaults():
    cfg = get_config()
    assert cfg.dramabox_voice_ref is None
    assert cfg.dramabox_cfg_scale == 2.5
    assert cfg.dramabox_stg_scale == 1.5
    assert cfg.dramabox_seed == 42
    assert cfg.dramabox_duration_multiplier == 1.1


def test_unknown_config_key_raises():
    with pytest.raises(ValueError, match="Unknown config key"):
        update_config(dramabox_nonexistent="x")
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_dramabox.py -v
```

Expected: FAIL — `ValueError: Unknown config key: 'tts_engine'` (or similar) because "dramabox" is not in the Literal, and the new fields don't exist yet.

- [ ] **Step 3: Update `core/config.py`**

Replace the existing TTS block:

```python
    # TTS
    tts_engine: Literal["kokoro", "chatterbox"] = "kokoro"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    chatterbox_reference_audio: str | None = None
    chatterbox_exaggeration: float = 0.5
```

With:

```python
    # TTS
    tts_engine: Literal["kokoro", "chatterbox", "dramabox"] = "kokoro"
    kokoro_voice: str = "af_heart"
    kokoro_speed: float = 1.0
    chatterbox_reference_audio: str | None = None
    chatterbox_exaggeration: float = 0.5
    dramabox_voice_ref: str | None = None
    dramabox_cfg_scale: float = 2.5
    dramabox_stg_scale: float = 1.5
    dramabox_seed: int = 42
    dramabox_duration_multiplier: float = 1.1
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_dramabox.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add core/config.py tests/test_dramabox.py
git commit -m "feat: add Dramabox config fields and expand tts_engine Literal"
```

---

## Task 3: DramaboxTTS wrapper

**Files:**
- Create: `voice/dramabox/wrapper.py`
- Test: `tests/test_dramabox.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_dramabox.py`:

```python
import torch
import numpy as np
from unittest.mock import MagicMock, patch


def _make_mock_server():
    """Mock TTSServer: synthesise returns (1-ch float32 tensor at 48kHz, 48000)."""
    mock = MagicMock()
    mock.generate.return_value = (torch.zeros(1, 48000), 48000)
    mock.generate_to_file.return_value = "/tmp/out.wav"
    return mock


def test_dramabox_wrapper_synthesise_returns_tensor_and_sr():
    from voice.dramabox.wrapper import DramaboxTTS
    mock_server = _make_mock_server()
    db = DramaboxTTS()
    db._server = mock_server

    update_config(dramabox_voice_ref=None, dramabox_cfg_scale=2.5,
                  dramabox_stg_scale=1.5, dramabox_seed=42,
                  dramabox_duration_multiplier=1.1)
    waveform, sr = db.synthesise("hello")

    assert isinstance(waveform, torch.Tensor)
    assert sr == 48000
    mock_server.generate.assert_called_once_with(
        prompt="hello",
        voice_ref=None,
        cfg_scale=2.5,
        stg_scale=1.5,
        seed=42,
        duration_multiplier=1.1,
    )


def test_dramabox_wrapper_generate_to_file_calls_server():
    from voice.dramabox.wrapper import DramaboxTTS
    mock_server = _make_mock_server()
    db = DramaboxTTS()
    db._server = mock_server

    update_config(dramabox_voice_ref="/ref.wav", dramabox_cfg_scale=2.5,
                  dramabox_stg_scale=1.5, dramabox_seed=42,
                  dramabox_duration_multiplier=1.1)
    result = db.generate_to_file("hello", "/tmp/out.wav")

    assert result == "/tmp/out.wav"
    mock_server.generate_to_file.assert_called_once_with(
        prompt="hello",
        output="/tmp/out.wav",
        voice_ref="/ref.wav",
        cfg_scale=2.5,
        stg_scale=1.5,
        seed=42,
        duration_multiplier=1.1,
        watermark=True,
        progress_callback=None,
    )
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_dramabox.py::test_dramabox_wrapper_synthesise_returns_tensor_and_sr -v
```

Expected: FAIL — `ModuleNotFoundError` or `ImportError` (wrapper doesn't exist yet).

- [ ] **Step 3: Create `voice/dramabox/wrapper.py`**

```python
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).parent


class DramaboxTTS:
    def __init__(self) -> None:
        self._server = None

    @staticmethod
    def _setup_paths() -> None:
        for p in [str(_HERE / "ltx2"), str(_HERE / "src")]:
            if p not in sys.path:
                sys.path.insert(0, p)

    def load(self) -> None:
        self._setup_paths()
        from inference_server import TTSServer
        from model_downloader import get_model_path, get_gemma_path

        transformer = get_model_path("transformer")
        audio_components = get_model_path("audio_components")
        gemma_root = get_gemma_path()
        self._server = TTSServer(
            checkpoint=transformer,
            full_checkpoint=audio_components,
            gemma_root=gemma_root,
            device="cuda",
            dtype="bf16",
            compile_model=False,
            bnb_4bit=True,
        )

    def synthesise(self, text: str):
        from core.config import get_config
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
        from core.config import get_config
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

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_dramabox.py::test_dramabox_wrapper_synthesise_returns_tensor_and_sr tests/test_dramabox.py::test_dramabox_wrapper_generate_to_file_calls_server -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add voice/dramabox/wrapper.py tests/test_dramabox.py
git commit -m "feat: add DramaboxTTS wrapper class"
```

---

## Task 4: TTSService integration

**Files:**
- Modify: `voice/tts.py`
- Test: `tests/test_dramabox.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_dramabox.py`:

```python
import voice.tts as tts_module
from voice.tts import TTSService


@pytest.fixture(autouse=True)
def reset_tts_singleton():
    original = getattr(tts_module, '_service', None)
    if hasattr(tts_module, '_service'):
        tts_module._service = None
    yield
    if hasattr(tts_module, '_service'):
        tts_module._service = original


def test_dramabox_synthesise_resamples_to_24k():
    fake_wav = torch.zeros(1, 48000)  # 48 kHz, 1 channel
    mock_db = MagicMock()
    mock_db.synthesise.return_value = (fake_wav, 48000)

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS", return_value=mock_db):
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello dramabox")

    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    assert result.shape == (24000,)   # 48000 downsampled to 24000


def test_dramabox_load_failure_falls_back_to_kokoro():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS") as MockDB, \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        MockDB.return_value.load.side_effect = RuntimeError("CUDA OOM")
        svc = TTSService()
        svc.load()

    assert get_config().tts_engine == "kokoro"


def test_get_tts_service_returns_none_before_load():
    from voice.tts import get_tts_service
    assert get_tts_service() is None


def test_get_tts_service_returns_instance_after_load():
    from voice.tts import get_tts_service
    with patch("voice.tts.KPipeline"):
        svc = TTSService()
        svc.load()
    assert get_tts_service() is svc


def test_dramabox_synthesis_fallback_to_kokoro_on_error():
    fake_audio = np.zeros(24000, dtype=np.float32)
    mock_kokoro = MagicMock()
    mock_kokoro.return_value = iter([(None, None, fake_audio)])

    mock_db = MagicMock()
    mock_db.synthesise.side_effect = RuntimeError("inference failed")

    update_config(tts_engine="dramabox")
    with patch("voice.tts.DramaboxTTS", return_value=mock_db), \
         patch("voice.tts.KPipeline", return_value=mock_kokoro):
        svc = TTSService()
        svc.load()
        result = svc.synthesise("hello")

    assert isinstance(result, np.ndarray)
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_dramabox.py::test_dramabox_synthesise_resamples_to_24k -v
```

Expected: FAIL — AttributeError or ImportError (DramaboxTTS not in tts.py yet).

- [ ] **Step 3: Replace `voice/tts.py` entirely**

```python
import logging
import numpy as np
from core.config import get_config, update_config

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
        lang_code = config.kokoro_voice[0] if config.kokoro_voice else "a"
        self._kokoro = KPipeline(lang_code=lang_code)
        self._kokoro_lang = lang_code

    def _ensure_kokoro(self) -> None:
        if self._kokoro is None:
            self._load_kokoro(get_config())

    def _load_chatterbox(self, config) -> None:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._chatterbox = ChatterboxTTS.from_pretrained(device=device)
        except Exception:
            logger.warning("Chatterbox failed to load; Kokoro will be used", exc_info=True)
            update_config(tts_engine="kokoro")

    def _load_dramabox(self, config) -> None:
        if DramaboxTTS is None:
            logger.warning("Dramabox not available (missing deps); using Kokoro")
            update_config(tts_engine="kokoro")
            return
        try:
            self._dramabox = DramaboxTTS()
            self._dramabox.load()
        except Exception:
            logger.warning("Dramabox failed to load; Kokoro will be used", exc_info=True)
            self._dramabox = None
            update_config(tts_engine="kokoro")

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
            config = get_config()
            wav = self._chatterbox.generate(
                text,
                audio_prompt_path=config.chatterbox_reference_audio,
                exaggeration=config.chatterbox_exaggeration,
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

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_dramabox.py -v
```

Expected: all Dramabox tests PASSED.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass (including existing TTS and dashboard tests).

- [ ] **Step 6: Commit**

```bash
git add voice/tts.py tests/test_dramabox.py
git commit -m "feat: integrate DramaboxTTS into TTSService with 48→24kHz resampling"
```

---

## Task 5: Dashboard API endpoints and static file serving

**Files:**
- Modify: `dashboard/server.py`
- Modify: `core/main.py`
- Test: `tests/test_dramabox.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_dramabox.py`:

```python
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from dashboard.server import router
from dashboard import server as dashboard_server
from core.config import reset_config as _reset_config
import asyncio


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture(autouse=True)
def reset_cfg_dashboard():
    yield
    _reset_config()


async def test_generate_dramabox_not_loaded_returns_409(app):
    with patch("dashboard.server.get_tts_service", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/generate-dramabox", json={"prompt": "hello"}
            )
    assert resp.status_code == 409


async def test_generate_dramabox_empty_prompt_returns_422(app):
    mock_svc = MagicMock()
    mock_svc._dramabox = MagicMock()
    with patch("dashboard.server.get_tts_service", return_value=mock_svc):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/generate-dramabox", json={"prompt": "   "}
            )
    assert resp.status_code == 422


async def test_generate_dramabox_returns_filename(app, tmp_path):
    mock_svc = MagicMock()
    mock_svc._dramabox = MagicMock()
    mock_svc._dramabox.generate_to_file.return_value = str(tmp_path / "out.wav")

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("dashboard.server.get_tts_service", return_value=mock_svc), \
         patch("dashboard.server.UPLOADS_DIR", tmp_path), \
         patch("asyncio.to_thread", side_effect=_fake_to_thread):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/generate-dramabox", json={"prompt": "hello world"}
            )

    assert resp.status_code == 200
    data = resp.json()
    assert "filename" in data
    assert data["filename"].startswith("dramabox_")
    assert data["filename"].endswith(".wav")


async def test_upload_reference_audio_dramabox_target(app, tmp_path):
    import io
    fake_wav = b"RIFF" + b"\x00" * 40
    with patch.object(dashboard_server, "UPLOADS_DIR", tmp_path):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/upload-reference-audio?target=dramabox",
                files={"file": ("ref.wav", io.BytesIO(fake_wav), "audio/wav")},
            )
    assert resp.status_code == 200
    from core.config import get_config
    assert get_config().dramabox_voice_ref is not None
    assert get_config().chatterbox_reference_audio is None


async def test_stop_recording_dramabox_target(app, tmp_path):
    chunk = np.zeros((1600, 1), dtype=np.int16)
    dashboard_server._recorder.active = True
    dashboard_server._recorder.chunks = [chunk]
    dashboard_server._recorder.thread = None

    with patch.object(dashboard_server, "UPLOADS_DIR", tmp_path):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/stop-recording?target=dramabox")

    assert resp.status_code == 200
    from core.config import get_config
    assert get_config().dramabox_voice_ref is not None
    assert get_config().chatterbox_reference_audio is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/test_dramabox.py::test_generate_dramabox_not_loaded_returns_409 -v
```

Expected: FAIL — route not found (404) or import error.

- [ ] **Step 3: Update `dashboard/server.py`**

Add the following imports at the top (after existing imports):

```python
import asyncio
```

(Note: `asyncio` is already imported via standard library — verify it's present; if not, add it.)

Modify the `upload_reference_audio` endpoint signature to accept a `target` query param:

```python
@router.post("/api/upload-reference-audio")
async def upload_reference_audio(file: UploadFile = File(...), target: str = "chatterbox"):
    safe_name = Path(file.filename or "upload").name or "upload"
    dest = UPLOADS_DIR / safe_name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    if target == "dramabox":
        update_config(dramabox_voice_ref=str(dest))
    else:
        update_config(chatterbox_reference_audio=str(dest))
    return {"path": str(dest), "filename": file.filename}
```

Modify the `stop_recording` endpoint signature to accept a `target` query param:

```python
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
```

Add the `get_tts_service` import and the new endpoint after the existing `stop_recording` endpoint:

```python
@router.post("/api/generate-dramabox")
async def generate_dramabox(body: dict):
    from voice.tts import get_tts_service
    svc = get_tts_service()
    if svc is None or svc._dramabox is None:
        raise HTTPException(status_code=409, detail="Dramabox not loaded")
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
```

- [ ] **Step 4: Update `core/main.py` — mount uploads directory**

In the `create_app()` function, after the existing `/static` mount, add:

```python
    from dashboard.server import UPLOADS_DIR
    app.mount(
        "/uploads",
        StaticFiles(directory=UPLOADS_DIR),
        name="uploads",
    )
```

The full `create_app` function becomes:

```python
def create_app() -> FastAPI:
    load_modules()
    setup_event_forwarding()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipeline_task = asyncio.create_task(_start_pipeline())
        yield
        pipeline_task.cancel()
        try:
            await pipeline_task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="Plia-OS", lifespan=lifespan)
    app.include_router(dashboard_router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent.parent / "dashboard" / "static"),
        name="static",
    )
    from dashboard.server import UPLOADS_DIR
    app.mount(
        "/uploads",
        StaticFiles(directory=UPLOADS_DIR),
        name="uploads",
    )
    return app
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/test_dramabox.py -v
```

Expected: all new endpoint tests PASSED.

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass (existing stop-recording test still passes — default target is "chatterbox").

- [ ] **Step 7: Commit**

```bash
git add dashboard/server.py core/main.py tests/test_dramabox.py
git commit -m "feat: add /api/generate-dramabox endpoint, target param on upload/record, mount /uploads"
```

---

## Task 6: Dashboard UI

**Files:**
- Modify: `dashboard/static/index.html`

- [ ] **Step 1: Add "Dramabox" to the engine select**

In `index.html`, find the `<select id="tts-engine">` element and add the Dramabox option:

```html
    <label>Engine
      <select id="tts-engine" onchange="onEngineChange()">
        <option value="kokoro">Kokoro</option>
        <option value="chatterbox">Chatterbox</option>
        <option value="dramabox">Dramabox</option>
      </select>
    </label>
```

- [ ] **Step 2: Add the Dramabox controls panel**

After the closing `</div>` of `#chatterbox-controls` (line 78), add:

```html
    <!-- Dramabox-specific -->
    <div id="dramabox-controls" style="display:none">
      <label>Reference Voice (5–10 sec WAV/MP3)
        <input type="file" id="db-ref-file" accept="audio/*" onchange="uploadDbReferenceAudio()" />
      </label>
      <div id="db-ref-status" class="ref-status"></div>
      <div style="display:flex;gap:6px;margin:4px 0;">
        <button id="db-record-btn" onclick="startDbRecording()" style="width:auto;padding:6px 10px;">Record</button>
        <button id="db-stop-btn" onclick="stopDbRecording()" style="display:none;width:auto;padding:6px 10px;">Stop</button>
        <span id="db-timer" style="display:none;font-size:0.75rem;color:#4fc3f7;align-self:center;"></span>
      </div>
      <canvas id="db-meter" width="120" height="10" style="display:none;margin-bottom:4px;border-radius:2px;background:#1a1a1a;"></canvas>
      <label>CFG Scale
        <input type="range" id="db-cfg" min="1.0" max="5.0" step="0.1" value="2.5" />
      </label>
      <label>STG Scale
        <input type="range" id="db-stg" min="0.0" max="3.0" step="0.1" value="1.5" />
      </label>
      <label>Seed
        <input type="number" id="db-seed" value="42" min="0" style="width:100%" />
      </label>

      <hr style="border-color:#333;margin:8px 0;" />
      <h2>Generate Clip</h2>
      <label>Prompt
        <textarea id="db-prompt" rows="4"
          style="width:100%;background:#1a1a1a;color:#e0e0e0;border:1px solid #333;border-radius:4px;padding:4px 6px;font-family:monospace;resize:vertical;"
          placeholder='A woman speaks warmly, "Welcome to Plia."'></textarea>
      </label>
      <button id="db-generate-btn" onclick="generateDramaboxClip()">Generate</button>
      <div id="db-progress" style="display:none;font-size:0.75rem;color:#4fc3f7;margin:4px 0;"></div>
      <div id="db-result" style="display:none;margin-top:6px;">
        <audio id="db-audio" controls style="width:100%;margin-bottom:4px;"></audio>
        <a id="db-download" download style="font-size:0.75rem;color:#4fc3f7;">Download</a>
      </div>
    </div>
```

- [ ] **Step 3: Update `onEngineChange()` in the `<script>` block**

Replace the existing `onEngineChange` function:

```javascript
  function onEngineChange() {
    const engine = document.getElementById('tts-engine').value;
    document.getElementById('kokoro-controls').style.display = engine === 'kokoro' ? '' : 'none';
    document.getElementById('chatterbox-controls').style.display = engine === 'chatterbox' ? '' : 'none';
    document.getElementById('dramabox-controls').style.display = engine === 'dramabox' ? '' : 'none';
  }
```

- [ ] **Step 4: Update `applyVoiceConfig()` to include Dramabox params**

Replace the existing `applyVoiceConfig` function:

```javascript
  function applyVoiceConfig() {
    const payload = {
      tts_engine: document.getElementById('tts-engine').value,
      kokoro_voice: document.getElementById('kokoro-voice').value,
      kokoro_speed: parseFloat(document.getElementById('kokoro-speed').value),
      chatterbox_exaggeration: parseFloat(document.getElementById('cb-exag').value),
      dramabox_cfg_scale: parseFloat(document.getElementById('db-cfg').value),
      dramabox_stg_scale: parseFloat(document.getElementById('db-stg').value),
      dramabox_seed: parseInt(document.getElementById('db-seed').value, 10),
    };
    fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
  }
```

- [ ] **Step 5: Update config loader to populate Dramabox controls**

In the existing `fetch('/api/config').then(cfg => {...})` block, add after the chatterbox lines:

```javascript
      document.getElementById('db-cfg').value = cfg.dramabox_cfg_scale;
      document.getElementById('db-stg').value = cfg.dramabox_stg_scale;
      document.getElementById('db-seed').value = cfg.dramabox_seed;
      if (cfg.dramabox_voice_ref) {
        const name = cfg.dramabox_voice_ref.split('/').pop();
        document.getElementById('db-ref-status').textContent = `Current: ${name}`;
      }
```

- [ ] **Step 6: Add Dramabox recording state vars**

In the `<script>` block, alongside the existing `_rec*` vars, add:

```javascript
  let _dbRecTimerInterval = null;
  let _dbRecTimerSeconds = 0;
  let _dbRecAudioCtx = null;
  let _dbRecMeterRaf = null;
  let _dbRecStream = null;
```

- [ ] **Step 7: Add Dramabox reference audio upload function**

```javascript
  async function uploadDbReferenceAudio() {
    const fileInput = document.getElementById('db-ref-file');
    const file = fileInput.files[0];
    if (!file) return;
    const status = document.getElementById('db-ref-status');
    status.textContent = 'Uploading…';
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/upload-reference-audio?target=dramabox', { method: 'POST', body: form });
    if (res.ok) {
      const data = await res.json();
      status.textContent = `Loaded: ${data.filename}`;
    } else {
      status.textContent = 'Upload failed';
    }
  }
```

- [ ] **Step 8: Add Dramabox Record/Stop functions**

```javascript
  async function startDbRecording() {
    document.getElementById('db-record-btn').disabled = true;
    const statusEl = document.getElementById('db-ref-status');
    const res = await fetch('/api/start-recording', { method: 'POST' });
    if (!res.ok) {
      document.getElementById('db-record-btn').disabled = false;
      statusEl.textContent = 'Failed to start recording';
      return;
    }
    _dbRecTimerSeconds = 0;
    const timerEl = document.getElementById('db-timer');
    timerEl.textContent = 'Recording… 0:00';
    timerEl.style.display = '';
    _dbRecTimerInterval = setInterval(() => {
      _dbRecTimerSeconds++;
      const m = Math.floor(_dbRecTimerSeconds / 60);
      const s = String(_dbRecTimerSeconds % 60).padStart(2, '0');
      timerEl.textContent = `Recording… ${m}:${s}`;
    }, 1000);
    try {
      _dbRecStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      _dbRecAudioCtx = new AudioContext();
      const analyser = _dbRecAudioCtx.createAnalyser();
      analyser.fftSize = 256;
      _dbRecAudioCtx.createMediaStreamSource(_dbRecStream).connect(analyser);
      const canvas = document.getElementById('db-meter');
      canvas.style.display = '';
      const ctx2d = canvas.getContext('2d');
      const dataArr = new Uint8Array(analyser.frequencyBinCount);
      const drawMeter = () => {
        _dbRecMeterRaf = requestAnimationFrame(drawMeter);
        analyser.getByteFrequencyData(dataArr);
        const level = dataArr.reduce((a, b) => a + b, 0) / dataArr.length / 255;
        ctx2d.fillStyle = '#1a1a1a';
        ctx2d.fillRect(0, 0, canvas.width, canvas.height);
        ctx2d.fillStyle = '#4caf50';
        ctx2d.fillRect(0, 0, canvas.width * level, canvas.height);
      };
      drawMeter();
    } catch (_) {}
    document.getElementById('db-record-btn').style.display = 'none';
    document.getElementById('db-stop-btn').style.display = '';
  }

  async function stopDbRecording() {
    clearInterval(_dbRecTimerInterval);
    _dbRecTimerInterval = null;
    document.getElementById('db-timer').style.display = 'none';
    if (_dbRecMeterRaf) { cancelAnimationFrame(_dbRecMeterRaf); _dbRecMeterRaf = null; }
    if (_dbRecStream) { _dbRecStream.getTracks().forEach(t => t.stop()); _dbRecStream = null; }
    if (_dbRecAudioCtx) { _dbRecAudioCtx.close().catch(() => {}); _dbRecAudioCtx = null; }
    document.getElementById('db-meter').style.display = 'none';
    document.getElementById('db-stop-btn').disabled = true;
    const statusEl = document.getElementById('db-ref-status');
    statusEl.textContent = 'Saving…';
    const res = await fetch('/api/stop-recording?target=dramabox', { method: 'POST' });
    document.getElementById('db-record-btn').style.display = '';
    document.getElementById('db-stop-btn').style.display = 'none';
    document.getElementById('db-stop-btn').disabled = false;
    if (res.ok) {
      const data = await res.json();
      statusEl.textContent = `Loaded: ${data.filename}`;
    } else {
      statusEl.textContent = 'Stop failed';
    }
  }
```

- [ ] **Step 9: Add the Generate Clip function**

```javascript
  async function generateDramaboxClip() {
    const prompt = document.getElementById('db-prompt').value.trim();
    if (!prompt) return;
    const btn = document.getElementById('db-generate-btn');
    const progressEl = document.getElementById('db-progress');
    const resultEl = document.getElementById('db-result');
    btn.disabled = true;
    progressEl.textContent = 'Generating…';
    progressEl.style.display = '';
    resultEl.style.display = 'none';

    const payload = {
      prompt,
      seed: parseInt(document.getElementById('db-seed').value, 10),
    };
    const res = await fetch('/api/generate-dramabox', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });

    btn.disabled = false;
    if (res.ok) {
      const data = await res.json();
      progressEl.style.display = 'none';
      const audioEl = document.getElementById('db-audio');
      audioEl.src = `/uploads/${data.filename}`;
      document.getElementById('db-download').href = `/uploads/${data.filename}`;
      document.getElementById('db-download').textContent = `Download ${data.filename}`;
      resultEl.style.display = '';
    } else {
      progressEl.textContent = 'Generation failed — check server logs';
    }
  }
```

- [ ] **Step 10: Wire WebSocket `dramabox_progress` events**

In the existing `ws.onmessage` handler, add inside the if-chain:

```javascript
    if (msg.type === 'dramabox_progress') {
      const el = document.getElementById('db-progress');
      if (el) el.textContent = `Generating… chunk ${msg.chunk} / ${msg.total} (est. ${msg.est_duration_s}s)`;
    }
```

- [ ] **Step 11: Update the `beforeunload` handler to also stop Dramabox recording**

Replace:

```javascript
  window.addEventListener('beforeunload', () => {
    if (_recTimerInterval) fetch('/api/stop-recording', { method: 'POST', keepalive: true });
  });
```

With:

```javascript
  window.addEventListener('beforeunload', () => {
    if (_recTimerInterval || _dbRecTimerInterval) {
      fetch('/api/stop-recording', { method: 'POST', keepalive: true });
    }
  });
```

- [ ] **Step 12: Start the server and manually verify**

```bash
.venv/bin/python -m uvicorn core.main:create_app --factory --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` and confirm:
- Engine dropdown shows "Kokoro / Chatterbox / Dramabox"
- Selecting Dramabox shows the controls panel with CFG/STG/Seed sliders and Generate Clip section
- Switching between engines shows/hides the correct panel
- Apply button sends config including Dramabox fields (check browser Network tab)

- [ ] **Step 13: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat: add Dramabox engine UI with voice ref recorder and clip generator"
```

---

## Task 7: Optional dependencies in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the `[dramabox]` extras group**

In `pyproject.toml`, after the existing `[project.optional-dependencies]` dev block, add:

```toml
dramabox = [
    "accelerate>=0.25.0",
    "bitsandbytes>=0.45.0",
    "peft>=0.7.0",
    "av>=12.0.0",
    "einops>=0.7.0",
    "sentencepiece>=0.1.99",
    "resemble-perth @ git+https://github.com/resemble-ai/Perth.git@master",
]
```

The full section becomes:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
]
dramabox = [
    "accelerate>=0.25.0",
    "bitsandbytes>=0.45.0",
    "peft>=0.7.0",
    "av>=12.0.0",
    "einops>=0.7.0",
    "sentencepiece>=0.1.99",
    "resemble-perth @ git+https://github.com/resemble-ai/Perth.git@master",
]
```

- [ ] **Step 2: Install the extras into the venv**

```bash
.venv/bin/pip install -e ".[dramabox]"
```

Expected: packages install without error. Note: `bitsandbytes` requires CUDA-capable GPU and matching CUDA version — if it fails, install `bitsandbytes-cpu` as a fallback (`pip install bitsandbytes-cpu`).

- [ ] **Step 3: Run full test suite to confirm nothing broke**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add [dramabox] optional dependency group to pyproject.toml"
```

---

## Final verification

- [ ] Run the complete test suite one last time:

```bash
.venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] Start the server and confirm the Dramabox panel loads without JS errors (open browser devtools console):

```bash
.venv/bin/python -m uvicorn core.main:create_app --factory --host 0.0.0.0 --port 8000
```

- [ ] Confirm `GET /api/config` returns the new Dramabox fields (default values):

```bash
curl -s http://localhost:8000/api/config | python3 -m json.tool | grep dramabox
```

Expected output:
```json
"dramabox_cfg_scale": 2.5,
"dramabox_duration_multiplier": 1.1,
"dramabox_seed": 42,
"dramabox_stg_scale": 1.5,
"dramabox_voice_ref": null,
```
