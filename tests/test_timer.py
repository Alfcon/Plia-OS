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
