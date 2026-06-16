from unittest.mock import patch, MagicMock


def test_add_calendar_event_success():
    mock_store = MagicMock()
    mock_store.add_event.return_value = "abcd1234-5678-0000-0000-000000000000"
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        from modules.example_module import add_calendar_event
        result = add_calendar_event("Team standup", "2026-06-20", "10:00", 30)
    mock_store.add_event.assert_called_once_with("Team standup", "2026-06-20", "10:00", 30)
    assert "Team standup" in result
    assert "abcd1234" in result


def test_add_calendar_event_invalid_date():
    mock_store = MagicMock()
    mock_store.add_event.side_effect = ValueError("Invalid date/time: 'bad bad'")
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        from modules.example_module import add_calendar_event
        result = add_calendar_event("Meeting", "bad", "bad", 60)
    assert "Invalid" in result


def test_list_calendar_events_returns_formatted():
    mock_store = MagicMock()
    mock_store.list_events.return_value = [
        "2026-06-20 10:00: Team standup (uid: abcd1234)",
        "2026-06-21 14:00: Doctor (uid: ef567890)",
    ]
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        from modules.example_module import list_calendar_events
        result = list_calendar_events()
    assert "Team standup" in result
    assert "Doctor" in result


def test_list_calendar_events_empty():
    mock_store = MagicMock()
    mock_store.list_events.return_value = ["No events found"]
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        from modules.example_module import list_calendar_events
        result = list_calendar_events()
    assert "No events" in result


def test_delete_calendar_event_found():
    mock_store = MagicMock()
    mock_store.delete_event.return_value = True
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        from modules.example_module import delete_calendar_event
        result = delete_calendar_event("abcd1234")
    mock_store.delete_event.assert_called_once_with("abcd1234")
    assert "deleted" in result


def test_delete_calendar_event_not_found():
    mock_store = MagicMock()
    mock_store.delete_event.return_value = False
    with patch("agents.calendar_store.get_calendar_store", return_value=mock_store):
        from modules.example_module import delete_calendar_event
        result = delete_calendar_event("zzzzzzzz")
    assert "No event" in result
