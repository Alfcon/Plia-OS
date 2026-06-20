# NOTE: OpenWakeWord ships built-in models (e.g. "hey_jarvis", "alexa").
# To use "hey plia", train a custom model via openwakeword's training scripts
# and set wake_word_model to the path of the exported .onnx file in config.
import numpy as np
from core.config import get_config

try:
    from openwakeword.model import Model
    from openwakeword import get_pretrained_model_paths
except ImportError:  # pragma: no cover – optional at import time
    Model = None  # type: ignore[assignment,misc]
    get_pretrained_model_paths = None  # type: ignore[assignment]


def _resolve_model_path(name: str) -> str:
    """Return a file path for a named pretrained model or pass through if already a path."""
    import os
    if os.path.exists(name):
        return name
    if get_pretrained_model_paths is not None:
        normalized = name.lower().replace(" ", "_")
        matches = [p for p in get_pretrained_model_paths() if normalized in p.lower()]
        if matches:
            return matches[0]
    raise ValueError(f"Wake word model {name!r} not found. Available: {get_pretrained_model_paths()}")


class WakeWordDetector:
    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        config = get_config()
        model_path = _resolve_model_path(config.wake_word_model)
        self._model = Model(wakeword_model_paths=[model_path])  # type: ignore[misc]

    def detect(self, chunk: np.ndarray) -> bool:
        if self._model is None:
            raise RuntimeError("Call load() before detect()")
        config = get_config()
        predictions = self._model.predict(chunk)
        return bool(any(v >= config.wake_word_threshold for v in predictions.values()))

    def reset(self) -> None:
        if self._model is not None:
            self._model.reset()
