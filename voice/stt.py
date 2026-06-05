import numpy as np
from core.config import get_config

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover – optional at import time
    WhisperModel = None  # type: ignore[assignment,misc]


class STTService:
    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        config = get_config()
        self._model = WhisperModel(  # type: ignore[misc]
            config.stt_model_size,
            device="cpu",
            compute_type="int8",
        )

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("Call load() before transcribe()")
        config = get_config()
        segments, _ = self._model.transcribe(audio, language=config.stt_language)
        return " ".join(seg.text.strip() for seg in segments).strip()
