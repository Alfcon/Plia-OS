import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from voice.wake import WakeWordDetector


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


def test_reset_calls_model_reset():
    mock_model = MagicMock()
    mock_model.predict.return_value = {"hey_jarvis": 0.0}

    with patch("voice.wake.Model", return_value=mock_model):
        det = WakeWordDetector()
        det.load()
        det.reset()

    mock_model.reset.assert_called_once()
