import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from voice.stt import STTService


def _make_segment(text):
    seg = MagicMock()
    seg.text = text
    return seg


def test_transcribe_returns_joined_text():
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        iter([_make_segment(" Hello "), _make_segment(" world ")]),
        MagicMock(),
    )
    with patch("voice.stt.WhisperModel", return_value=mock_model):
        svc = STTService()
        svc.load()
        result = svc.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == "Hello world"


def test_transcribe_empty_segments_returns_empty():
    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter([]), MagicMock())
    with patch("voice.stt.WhisperModel", return_value=mock_model):
        svc = STTService()
        svc.load()
        result = svc.transcribe(np.zeros(16000, dtype=np.float32))

    assert result == ""


def test_transcribe_before_load_raises():
    svc = STTService()
    with pytest.raises(RuntimeError, match="load\\(\\)"):
        svc.transcribe(np.zeros(16000, dtype=np.float32))
