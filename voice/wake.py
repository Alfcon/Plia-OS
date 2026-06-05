# NOTE: OpenWakeWord ships built-in models (e.g. "hey_jarvis", "alexa").
# To use "hey plia", train a custom model via openwakeword's training scripts
# and set wake_word_model to the path of the exported .onnx file in config.
import numpy as np
from core.config import get_config

try:
    from openwakeword.model import Model
except ImportError:  # pragma: no cover – optional at import time
    Model = None  # type: ignore[assignment,misc]


class WakeWordDetector:
    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        config = get_config()
        self._model = Model(  # type: ignore[misc]
            wakeword_models=[config.wake_word_model],
            inference_framework="onnx",
        )

    def detect(self, chunk: np.ndarray) -> bool:
        if self._model is None:
            raise RuntimeError("Call load() before detect()")
        config = get_config()
        predictions = self._model.predict(chunk)
        return bool(any(v >= config.wake_word_threshold for v in predictions.values()))

    def reset(self) -> None:
        if self._model is not None:
            self._model.reset()
