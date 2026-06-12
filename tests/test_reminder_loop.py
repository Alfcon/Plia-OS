import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_check_reminders_fires_overdue():
    mock_store = MagicMock()
    mock_store.get_pending.return_value = [
        {"id": 1, "message": "Water plants", "fire_at": "2026-01-01T00:00:00+00:00"}
    ]
    fired = []

    async def mock_emit(event_type, data):
        fired.append((event_type, data))

    with patch("core.reminder_loop.get_memory_store", return_value=mock_store), \
         patch("core.reminder_loop.events.emit", side_effect=mock_emit):
        from core.reminder_loop import _check_reminders
        await _check_reminders()

    assert len(fired) == 1
    assert fired[0][0] == "reminder_fired"
    assert fired[0][1]["message"] == "Water plants"
    assert fired[0][1]["id"] == 1
    mock_store.mark_reminder_done.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_check_reminders_no_fire_when_empty():
    mock_store = MagicMock()
    mock_store.get_pending.return_value = []
    fired = []

    async def mock_emit(event_type, data):
        fired.append((event_type, data))

    with patch("core.reminder_loop.get_memory_store", return_value=mock_store), \
         patch("core.reminder_loop.events.emit", side_effect=mock_emit):
        from core.reminder_loop import _check_reminders
        await _check_reminders()

    assert fired == []
    mock_store.mark_reminder_done.assert_not_called()


@pytest.mark.asyncio
async def test_check_reminders_fires_multiple():
    mock_store = MagicMock()
    mock_store.get_pending.return_value = [
        {"id": 1, "message": "First",  "fire_at": "2026-01-01T00:00:00+00:00"},
        {"id": 2, "message": "Second", "fire_at": "2026-01-01T00:00:01+00:00"},
    ]
    fired = []

    async def mock_emit(event_type, data):
        fired.append((event_type, data))

    with patch("core.reminder_loop.get_memory_store", return_value=mock_store), \
         patch("core.reminder_loop.events.emit", side_effect=mock_emit):
        from core.reminder_loop import _check_reminders
        await _check_reminders()

    assert len(fired) == 2
    assert mock_store.mark_reminder_done.call_count == 2
