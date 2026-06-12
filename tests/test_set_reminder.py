import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


def test_set_reminder_persists_to_store():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 42
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_reminder
        result = set_reminder("Take meds", 10)
    mock_store.add_reminder.assert_called_once()
    call_args = mock_store.add_reminder.call_args[0]
    assert call_args[0] == "Take meds"
    fire_at = datetime.fromisoformat(call_args[1])
    now = datetime.now(timezone.utc)
    delta = fire_at - now
    assert 9 * 60 < delta.total_seconds() < 11 * 60
    assert "10 minute" in result


def test_set_reminder_returns_confirmation():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 1
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_reminder
        result = set_reminder("Water plants", 30)
    assert "Water plants" in result
    assert "30 minute" in result
