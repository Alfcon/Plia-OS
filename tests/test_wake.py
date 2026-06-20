import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from voice.wake import WakeWordDetector, _resolve_model_path


def test_detect_returns_true_when_score_above_threshold():
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.9}

    with patch("voice.wake.Model", return_value=mock_model):
        det = WakeWordDetector()
        det.load()
        assert det.detect(np.zeros(1280, dtype=np.int16)) is True


def test_detect_returns_false_when_score_below_threshold():
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.1}

    with patch("voice.wake.Model", return_value=mock_model):
        det = WakeWordDetector()
        det.load()
        assert det.detect(np.zeros(1280, dtype=np.int16)) is False


def test_detect_before_load_raises():
    det = WakeWordDetector()
    with pytest.raises(RuntimeError, match="load\\(\\)"):
        det.detect(np.zeros(1280, dtype=np.int16))


def test_resolve_model_path_normalizes_spaces():
    fake_paths = ["/venv/openwakeword/resources/models/hey_jarvis_v0.1.onnx"]
    with patch("voice.wake.get_pretrained_model_paths", return_value=fake_paths):
        assert _resolve_model_path("hey jarvis") == fake_paths[0]
        assert _resolve_model_path("Hey Jarvis") == fake_paths[0]


def test_reset_calls_model_reset():
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.0}

    with patch("voice.wake.Model", return_value=mock_model):
        det = WakeWordDetector()
        det.load()
        det.reset()

    mock_model.reset.assert_called_once()
