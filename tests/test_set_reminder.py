import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


def test_set_reminder_persists_to_store():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 42
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import set_reminder
        result = set_reminder("Take meds", 10)
    mock_store.add_reminder.assert_called_once()
    call_args = mock_store.add_reminder.call_args[0]
    assert call_args[0] == "Take meds"
    fire_at = datetime.fromisoformat(call_args[1])
    now = datetime.now(timezone.utc)
    delta = fire_at - now
    assert 9 * 60 < delta.total_seconds() < 11 * 60
    assert "10 minute" in result


def test_list_pending_reminders_empty():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import list_pending_reminders
        result = list_pending_reminders()
    assert "No pending" in result


def test_list_pending_reminders_shows_items():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 1, "message": "Take meds", "fire_at": "2026-06-15T10:00:00+00:00"},
        {"id": 2, "message": "Call John", "fire_at": "2026-06-15T14:00:00+00:00"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import list_pending_reminders
        result = list_pending_reminders()
    assert "Take meds" in result
    assert "Call John" in result
    assert "[1]" in result
    assert "[2]" in result


def test_delete_reminder_marks_done():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [{"id": 5, "message": "Walk dog", "fire_at": "2026-06-15T18:00:00+00:00"}]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import delete_reminder
        result = delete_reminder(5)
    mock_store.mark_reminder_done.assert_called_once_with(5)
    assert "5" in result


def test_delete_reminder_not_found():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import delete_reminder
        result = delete_reminder(99)
    mock_store.mark_reminder_done.assert_not_called()
    assert "No pending" in result


def test_set_reminder_returns_confirmation():
    mock_store = MagicMock()
    mock_store.add_reminder.return_value = 1
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.reminder_tools import set_reminder
        result = set_reminder("Water plants", 30)
    assert "Water plants" in result
    assert "30 minute" in result
