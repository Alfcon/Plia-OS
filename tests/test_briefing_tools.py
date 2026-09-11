from unittest.mock import patch, MagicMock
import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _mock_forecast_response(hi=22.0, lo=14.0, code=1, uv=4.0):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "daily": {
            "temperature_2m_max": [hi],
            "temperature_2m_min": [lo],
            "weathercode": [code],
            "uv_index_max": [uv],
        }
    }
    return resp


def _mock_cfg(topic="world news", location="Berlin"):
    cfg = MagicMock()
    cfg.briefing_news_topic = topic
    cfg.weather_location = location
    return cfg


NEWS_TEXT = (
    "[2026-06-20] AI breakthrough announced — TechNews\n  https://example.com/1\n\n"
    "[2026-06-20] Markets rise on jobs data — Finance Daily\n  https://example.com/2\n\n"
    "[2026-06-20] New climate report released — SciencePost\n  https://example.com/3"
)

REMINDERS = [
    {"id": 1, "message": "take meds", "fire_at": "2026-06-20T09:00:00+00:00", "is_timer": False},
    {"id": 2, "message": "call dentist", "fire_at": "2026-06-20T14:00:00+00:00", "is_timer": False},
    {"id": 3, "message": "timer done", "fire_at": "2026-06-20T08:00:00+00:00", "is_timer": True},
]

CALENDAR_EVENTS = [
    {"uid": "abc123", "title": "Team standup", "dtstart": "2026-06-20T09:30:00", "dtend": "2026-06-20T10:00:00"},
    {"uid": "def456", "title": "Lunch with Alice", "dtstart": "2026-06-20T12:00:00", "dtend": "2026-06-20T13:00:00"},
    {"uid": "ghi789", "title": "Tomorrow's meeting", "dtstart": "2026-06-21T10:00:00", "dtend": "2026-06-21T11:00:00"},
]


# ── test_briefing_all_sections ─────────────────────────────────────────────────

def test_briefing_all_sections():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = REMINDERS
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = CALENDAR_EVENTS

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg()):
        with patch("modules.briefing_tools._resolve_location", return_value=(52.5, 13.4, "Berlin")):
            with patch("httpx.get", return_value=_mock_forecast_response()):
                with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                    with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                        with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT):
                            with patch("modules.briefing_tools.datetime") as mock_dt:
                                mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                                mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                                mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                                result = bt.morning_briefing()

    assert "Weather" in result
    assert "Berlin" in result
    assert "Reminders" in result
    assert "take meds" in result
    assert "call dentist" in result
    assert "timer done" not in result  # timers excluded
    assert "Team standup" in result
    assert "Lunch with Alice" in result
    assert "Tomorrow's meeting" not in result  # different date filtered out
    assert "News" in result
    assert "AI breakthrough" in result


# ── test_briefing_no_reminders ────────────────────────────────────────────────

def test_briefing_no_reminders():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = []

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg()):
        with patch("modules.briefing_tools._resolve_location", return_value=(52.5, 13.4, "Berlin")):
            with patch("httpx.get", return_value=_mock_forecast_response()):
                with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                    with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                        with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT):
                            with patch("modules.briefing_tools.datetime") as mock_dt:
                                mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                                mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                                mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                                result = bt.morning_briefing()

    assert "Reminders" not in result
    assert "Calendar" not in result
    assert "Weather" in result
    assert "News" in result


# ── test_briefing_weather_error ───────────────────────────────────────────────

def test_briefing_weather_error():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = REMINDERS
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = CALENDAR_EVENTS

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg()):
        with patch("modules.briefing_tools._resolve_location", side_effect=ValueError("No location set")):
            with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                    with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT):
                        with patch("modules.briefing_tools.datetime") as mock_dt:
                            mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                            mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                            mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                            result = bt.morning_briefing()

    assert "Weather" not in result
    assert "Reminders" in result
    assert "News" in result


# ── test_briefing_news_uses_config_topic ──────────────────────────────────────

def test_briefing_news_uses_config_topic():
    import modules.briefing_tools as bt

    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    mock_cal = MagicMock()
    mock_cal.list_events_json.return_value = []

    with patch("modules.briefing_tools.get_config", return_value=_mock_cfg(topic="Linux")):
        with patch("modules.briefing_tools._resolve_location", side_effect=ValueError("no loc")):
            with patch("modules.briefing_tools.get_memory_store", return_value=mock_store):
                with patch("modules.briefing_tools.get_calendar_store", return_value=mock_cal):
                    with patch("modules.briefing_tools.fetch_news", return_value=NEWS_TEXT) as mock_news:
                        with patch("modules.briefing_tools.datetime") as mock_dt:
                            mock_dt.now.return_value.date.return_value = __import__("datetime").date(2026, 6, 20)
                            mock_dt.now.return_value.strftime.return_value = "Saturday, June 20"
                            mock_dt.fromisoformat = __import__("datetime").datetime.fromisoformat
                            bt.morning_briefing()

    mock_news.assert_called_once_with("Linux", max_items=3)


# ── test_briefing_all_fail ────────────────────────────────────────────────────

def test_briefing_all_fail():
    import modules.briefing_tools as bt

    with patch("modules.briefing_tools.get_config", side_effect=Exception("config error")):
        result = bt.morning_briefing()

    assert len(result) > 0  # non-empty fallback


# ── test_briefing_registered_as_tool ─────────────────────────────────────────

def test_briefing_registered_as_tool(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools

    if "modules.briefing_tools" in sys.modules:
        del sys.modules["modules.briefing_tools"]

    set_loading_module("briefing_tools")
    try:
        import modules.briefing_tools  # noqa: F401
    finally:
        set_loading_module("")

    tools = list_tools()
    assert "morning_briefing" in tools
