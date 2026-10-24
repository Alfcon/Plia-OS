import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_is_connected_false_when_no_token_file(tmp_path):
    from agents.google_calendar import is_connected
    with patch("agents.google_calendar._token_path", return_value=tmp_path / "gcal_token.json"):
        assert is_connected() is False


def test_list_events_returns_empty_when_not_connected(tmp_path):
    from agents.google_calendar import list_events
    with patch("agents.google_calendar._token_path", return_value=tmp_path / "gcal_token.json"):
        result = list_events()
    assert result == []


def test_list_events_returns_structured_dicts():
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_service = MagicMock()
    mock_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "google-event-1",
                "summary": "Weekly sync",
                "start": {"dateTime": "2026-06-15T10:00:00+00:00"},
                "end": {"dateTime": "2026-06-15T11:00:00+00:00"},
            }
        ]
    }
    with patch("agents.google_calendar.get_credentials", return_value=mock_creds), \
         patch("googleapiclient.discovery.build", return_value=mock_service):
        from agents.google_calendar import list_events
        result = list_events()
    assert len(result) == 1
    assert result[0]["title"] == "Weekly sync"
    assert result[0]["uid"] == "google-event-1"
    assert result[0]["source"] == "google"
    assert result[0]["dtstart"] == "2026-06-15T10:00:00+00:00"


def test_list_events_handles_all_day_events():
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_service = MagicMock()
    mock_service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "allday-1",
                "summary": "Company holiday",
                "start": {"date": "2026-06-20"},
                "end": {"date": "2026-06-21"},
            }
        ]
    }
    with patch("agents.google_calendar.get_credentials", return_value=mock_creds), \
         patch("googleapiclient.discovery.build", return_value=mock_service):
        from agents.google_calendar import list_events
        result = list_events()
    assert result[0]["dtstart"] == "2026-06-20"


def test_create_event_raises_when_not_connected():
    with patch("agents.google_calendar.get_credentials", return_value=None):
        from agents.google_calendar import create_event
        with pytest.raises(RuntimeError, match="not authorized"):
            create_event("Test", "2026-06-15T10:00:00+00:00", "2026-06-15T11:00:00+00:00")


def test_create_event_calls_api_and_returns_id():
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_service = MagicMock()
    mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "new-gcal-id"}
    with patch("agents.google_calendar.get_credentials", return_value=mock_creds), \
         patch("googleapiclient.discovery.build", return_value=mock_service):
        from agents.google_calendar import create_event
        uid = create_event("Dentist", "2026-06-20T14:00:00+00:00", "2026-06-20T14:30:00+00:00")
    assert uid == "new-gcal-id"


def test_delete_event_raises_when_not_connected():
    with patch("agents.google_calendar.get_credentials", return_value=None):
        from agents.google_calendar import delete_event
        with pytest.raises(RuntimeError, match="not authorized"):
            delete_event("some-uid")
