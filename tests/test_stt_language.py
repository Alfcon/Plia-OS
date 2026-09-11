from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
import numpy as np


def _make_stt(language_setting: str):
    from core.config import update_config
    update_config(stt_language=language_setting)
    from voice.stt import STTService
    svc = STTService()
    # inject mock model
    mock_model = MagicMock()
    mock_seg = MagicMock()
    mock_seg.text = "hello"
    mock_model.transcribe.return_value = ([mock_seg], MagicMock(language="en"))
    svc._model = mock_model
    return svc, mock_model


@pytest.mark.asyncio
async def test_explicit_language_passed():
    svc, mock_model = _make_stt("fr")
    audio = np.zeros(16000, dtype=np.float32)
    svc.transcribe(audio)
    _, kwargs = mock_model.transcribe.call_args
    assert kwargs["language"] == "fr"


@pytest.mark.asyncio
async def test_empty_language_passes_none():
    svc, mock_model = _make_stt("")
    audio = np.zeros(16000, dtype=np.float32)
    svc.transcribe(audio)
    _, kwargs = mock_model.transcribe.call_args
    assert kwargs["language"] is None


@pytest.mark.asyncio
async def test_auto_language_passes_none():
    svc, mock_model = _make_stt("auto")
    audio = np.zeros(16000, dtype=np.float32)
    svc.transcribe(audio)
    _, kwargs = mock_model.transcribe.call_args
    assert kwargs["language"] is None


@pytest.mark.asyncio
async def test_english_language_passed():
    svc, mock_model = _make_stt("en")
    audio = np.zeros(16000, dtype=np.float32)
    svc.transcribe(audio)
    _, kwargs = mock_model.transcribe.call_args
    assert kwargs["language"] == "en"
