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
