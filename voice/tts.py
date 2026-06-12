import logging
import random
import threading
import time
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
        self._chatterbox_load_lock = threading.Lock()
        self._dramabox_load_lock = threading.Lock()
        self._chatterbox_failed_at: float | None = None
        self._dramabox_failed_at: float | None = None

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

        def _do_load():
            current_lang = get_config().kokoro_voice[0] if get_config().kokoro_voice else "a"
            self._kokoro = KPipeline(lang_code=current_lang)
            self._kokoro_lang = current_lang

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

    _LOAD_COOLDOWN_S = 60.0

    def _ensure_chatterbox(self, config=None) -> None:
        with self._chatterbox_load_lock:
            if self._chatterbox is not None:
                return
            if self._chatterbox_failed_at is not None:
                if time.monotonic() - self._chatterbox_failed_at < self._LOAD_COOLDOWN_S:
                    return
            self._load_chatterbox(config or get_config())
            if self._chatterbox is None:
                self._chatterbox_failed_at = time.monotonic()
            else:
                self._chatterbox_failed_at = None

    def _ensure_dramabox(self, config=None) -> None:
        with self._dramabox_load_lock:
            if self._dramabox is not None:
                return
            if self._dramabox_failed_at is not None:
                if time.monotonic() - self._dramabox_failed_at < self._LOAD_COOLDOWN_S:
                    return
            self._load_dramabox(config or get_config())
            if self._dramabox is None:
                self._dramabox_failed_at = time.monotonic()
            else:
                self._dramabox_failed_at = None

    def _load_chatterbox(self, config) -> None:
        broker = get_vram_broker()

        def _do_load():
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._chatterbox = ChatterboxTTS.from_pretrained(device=device)
            except Exception:
                logger.warning("Chatterbox failed to load; Kokoro will be used", exc_info=True)
                update_config(tts_engine="kokoro")

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

        broker = get_vram_broker()

        def _do_load():
            try:
                db = DramaboxTTS()
                db.load()
                self._dramabox = db
            except Exception:
                logger.warning("Dramabox failed to load; Kokoro will be used", exc_info=True)
                update_config(tts_engine="kokoro")

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
                self._ensure_dramabox(config)
            if self._dramabox is not None:
                return self._synthesise_dramabox(text)
        if config.tts_engine == "chatterbox":
            if self._chatterbox is None:
                logger.info("Loading Chatterbox on demand...")
                self._ensure_chatterbox(config)
            if self._chatterbox is not None:
                return self._synthesise_chatterbox(text)
        return self._synthesise_kokoro(text)

    def _synthesise_kokoro(self, text: str) -> np.ndarray:
        self._ensure_kokoro()
        config = get_config()
        lang_code = config.kokoro_voice[0] if config.kokoro_voice else "a"
        if self._kokoro is None or lang_code != getattr(self, "_kokoro_lang", None):
            logger.info("Reloading Kokoro for lang_code=%r", lang_code)
            # Reload in-place: broker already holds the GPU slot
            self._kokoro = KPipeline(lang_code=lang_code)
            self._kokoro_lang = lang_code
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
            torch.cuda.manual_seed_all(seed)
            wav = self._chatterbox.generate(
                text,
                audio_prompt_path=config.chatterbox_reference_audio,
                exaggeration=config.chatterbox_exaggeration,
                cfg_weight=config.chatterbox_cfg_weight,
                temperature=config.chatterbox_temperature,
            )
            return wav.squeeze().numpy()
        except Exception:
            logger.warning("Chatterbox synthesis failed; releasing and falling back to Kokoro", exc_info=True)
            get_vram_broker().release("chatterbox")
            try:
                if self._kokoro is None:
                    self._load_kokoro(get_config())
                return self._synthesise_kokoro(text)
            except Exception:
                logger.warning("Kokoro fallback also failed after Chatterbox failure", exc_info=True)
                return np.zeros(0, dtype=np.float32)

    def _synthesise_dramabox(self, text: str) -> np.ndarray:
        try:
            import torchaudio
            waveform, sr = self._dramabox.synthesise(text)  # (C, T) tensor, sr=48000
            resampled = torchaudio.functional.resample(waveform, sr, 24000)
            if resampled.dim() > 1:
                resampled = resampled.mean(dim=0)
            return resampled.numpy().astype(np.float32)
        except Exception:
            logger.warning("Dramabox synthesis failed; releasing and falling back to Kokoro", exc_info=True)
            get_vram_broker().release("dramabox")
            if self._kokoro is None:
                self._load_kokoro(get_config())
            return self._synthesise_kokoro(text)
