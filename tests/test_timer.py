from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


def test_set_timer_minutes_only():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(minutes=5)
    mock_store.add_reminder.assert_called_once()
    fire_at = datetime.fromisoformat(mock_store.add_reminder.call_args[0][1])
    delta = fire_at - datetime.now(timezone.utc)
    assert 4 * 60 < delta.total_seconds() < 6 * 60
    assert "5 minutes" in result
    assert "Timer done!" in mock_store.add_reminder.call_args[0][0]


def test_set_timer_seconds_only():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(seconds=30)
    fire_at = datetime.fromisoformat(mock_store.add_reminder.call_args[0][1])
    delta = fire_at - datetime.now(timezone.utc)
    assert 25 < delta.total_seconds() < 35
    assert "30 seconds" in result


def test_set_timer_minutes_and_seconds():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(minutes=1, seconds=30)
    fire_at = datetime.fromisoformat(mock_store.add_reminder.call_args[0][1])
    delta = fire_at - datetime.now(timezone.utc)
    assert 85 < delta.total_seconds() < 95
    assert "1 minute" in result
    assert "30 seconds" in result


def test_set_timer_with_label():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(minutes=3, label="pasta")
    message = mock_store.add_reminder.call_args[0][0]
    assert "pasta" in message
    assert "pasta" in result


def test_set_timer_zero_duration_returns_error():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(minutes=0, seconds=0)
    mock_store.add_reminder.assert_not_called()
    assert "second" in result.lower()


def test_set_timer_singular_minute():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(minutes=1)
    assert "1 minute" in result
    assert "minutes" not in result


def test_set_timer_singular_second():
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import set_timer
        result = set_timer(seconds=1)
    assert "1 second" in result
    assert "seconds" not in result


def test_list_timers_empty():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import list_timers
        result = list_timers()
    assert "No active" in result


def test_list_timers_shows_remaining_time():
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(minutes=3, seconds=30)).isoformat()
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 7, "message": "Timer done: pasta!", "fire_at": future},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import list_timers
        result = list_timers()
    assert "pasta" in result
    assert "[7]" in result
    assert "remaining" in result
    assert "3m" in result


def test_cancel_timer_by_label():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 3, "message": "Timer done: pasta!", "fire_at": "2099-01-01T00:03:00+00:00"},
        {"id": 4, "message": "Timer done: eggs!", "fire_at": "2099-01-01T00:05:00+00:00"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import cancel_timer
        result = cancel_timer(label="pasta")
    mock_store.mark_reminder_done.assert_called_once_with(3)
    assert "pasta" in result


def test_cancel_timer_no_label_cancels_most_recent():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 3, "message": "Timer done!", "fire_at": "2099-01-01T00:03:00+00:00"},
        {"id": 7, "message": "Timer done: tea!", "fire_at": "2099-01-01T00:01:00+00:00"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import cancel_timer
        result = cancel_timer()
    mock_store.mark_reminder_done.assert_called_once_with(7)


def test_cancel_timer_no_timers():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import cancel_timer
        result = cancel_timer()
    mock_store.mark_reminder_done.assert_not_called()
    assert "No active" in result


def test_cancel_timer_label_not_found():
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 3, "message": "Timer done: pasta!", "fire_at": "2099-01-01T00:03:00+00:00"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import cancel_timer
        result = cancel_timer(label="coffee")
    mock_store.mark_reminder_done.assert_not_called()
    assert "coffee" in result


def test_list_timers_excludes_non_timer_reminders():
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 1, "message": "Call John", "fire_at": future},
        {"id": 2, "message": "Timer done!", "fire_at": future},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        from modules.example_module import list_timers
        result = list_timers()
    assert "Call John" not in result
    assert "[2]" in result
