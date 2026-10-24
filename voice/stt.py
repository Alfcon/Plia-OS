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
        lang = config.stt_language
        language: str | None = lang if lang and lang.lower() != "auto" else None
        segments, _ = self._model.transcribe(
            audio,
            language=language,
            # Silero VAD strips non-speech before Whisper runs, so near-silence
            # cannot be hallucinated into stock phrases ("Yes.", "Thank you.").
            vad_filter=True,
            # Default True lets earlier text seed the next decode — a known
            # hallucination amplifier.
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe_file(self, path: str) -> str:
        if self._model is None:
            raise RuntimeError("Call load() before transcribe_file()")
        config = get_config()
        lang = config.stt_language
        language: str | None = lang if lang and lang.lower() != "auto" else None
        segments, _ = self._model.transcribe(
            path,
            language=language,
            # Whisper defaults kept deliberately: this method serves video/audio
            # summarization (agents/video_summarize.py), not the wake-word
            # pipeline. vad_filter can drop quiet dialog under background music,
            # and condition_on_previous_text=False hurts long-form coherence.
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


_stt_service: STTService | None = None


def get_stt_service() -> STTService:
    """Lazy singleton — loads the Whisper model on first call."""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
        _stt_service.load()
    return _stt_service
