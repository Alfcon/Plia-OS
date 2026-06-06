import logging
import numpy as np
from core.config import get_config, update_config

logger = logging.getLogger(__name__)

try:
    from kokoro import KPipeline
except ImportError:  # pragma: no cover
    KPipeline = None  # type: ignore[assignment,misc]

try:
    from chatterbox.tts import ChatterboxTTS
except ImportError:  # pragma: no cover
    ChatterboxTTS = None  # type: ignore[assignment,misc]


class TTSService:
    def __init__(self) -> None:
        self._kokoro = None
        self._chatterbox = None
        self._loaded = False

    def load(self) -> None:
        config = get_config()
        if config.tts_engine == "chatterbox":
            self._load_chatterbox(config)
        # Load kokoro when it is the primary engine (either originally, or after
        # chatterbox failed to load and the engine was reset to "kokoro").
        if get_config().tts_engine == "kokoro":
            self._load_kokoro(get_config())
        self._loaded = True

    def _load_kokoro(self, config) -> None:
        self._kokoro = KPipeline(lang_code="a")

    def _ensure_kokoro(self) -> None:
        """Lazily initialise Kokoro for use as a fallback during synthesis."""
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

    def synthesise(self, text: str) -> np.ndarray:
        if not self._loaded:
            raise RuntimeError("Call load() before synthesise()")
        config = get_config()
        if config.tts_engine == "chatterbox":
            if self._chatterbox is None:
                logger.info("Loading Chatterbox on demand...")
                self._load_chatterbox(config)
            if self._chatterbox is not None:
                return self._synthesise_chatterbox(text)
        return self._synthesise_kokoro(text)

    def _synthesise_kokoro(self, text: str) -> np.ndarray:
        config = get_config()
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
