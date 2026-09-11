import pytest
from unittest.mock import MagicMock, patch
from voice.pipeline import VoicePipeline


def _pipeline():
    p = VoicePipeline()
    p._wake = MagicMock()
    p._stt = MagicMock()
    p._tts = MagicMock()
    return p


def test_load_restores_recent_history():
    history = [
        {"role": "user",      "content": "Hello",       "ts": "2026-01-01T00:00:00+00:00"},
        {"role": "assistant", "content": "Hi there!",   "ts": "2026-01-01T00:00:01+00:00"},
    ]
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=history):
        p.load()
    assert p._conversation[0]["role"] == "system"
    assert p._conversation[1] == {"role": "user",      "content": "Hello"}
    assert p._conversation[2] == {"role": "assistant", "content": "Hi there!"}
    assert len(p._conversation) == 3


def test_load_empty_history():
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=[]):
        p.load()
    assert len(p._conversation) == 1
    assert p._conversation[0]["role"] == "system"


def test_load_skips_system_messages_in_history():
    history = [
        {"role": "system",    "content": "Old prompt",  "ts": "2026-01-01T00:00:00+00:00"},
        {"role": "user",      "content": "Remember me", "ts": "2026-01-01T00:00:01+00:00"},
    ]
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=history):
        p.load()
    roles = [m["role"] for m in p._conversation]
    assert roles.count("system") == 1
    assert roles == ["system", "user"]


def test_load_calls_get_recent_with_preload_limit():
    from voice.pipeline import _HISTORY_PRELOAD
    p = _pipeline()
    with patch("agents.chat_history.get_recent", return_value=[]) as mock_get:
        p.load()
    mock_get.assert_called_once_with(_HISTORY_PRELOAD)
