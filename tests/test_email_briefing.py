"""Tests for email section in morning briefing."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


def _patch_imap(mock_conn):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.imap_connection", return_value=cm)


def test_email_section_disabled_returns_empty():
    """_email_section returns '' when email_briefing_enabled is False."""
    from core.config import update_config
    update_config(email_briefing_enabled=False)
    from modules.briefing_tools import _email_section
    assert _email_section() == ""


def test_email_section_no_provider_returns_empty():
    """_email_section returns '' when email_provider is empty."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="")
    from modules.briefing_tools import _email_section
    assert _email_section() == ""


def test_email_section_unread_count():
    """_email_section returns 'Email: N unread.' when UNSEEN search returns messages."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="imap")

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2 3"])

    with _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()

    assert result == "Email: 3 unread."
    mock_conn.search.assert_called_with(None, "UNSEEN")


def test_email_section_zero_unread_returns_empty():
    """_email_section returns '' when there are no unread messages."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="imap")

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])

    with _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()

    assert result == ""


def test_email_section_connection_fails_returns_empty():
    """_email_section returns '' and does not crash when IMAP fails."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="imap")

    with patch("agents.email_client.imap_connection", side_effect=OSError("timeout")):
        from modules.briefing_tools import _email_section
        result = _email_section()

    assert result == ""


def test_morning_briefing_includes_email_section():
    """morning_briefing() output includes email line when unread > 0."""
    from core.config import update_config
    update_config(
        email_briefing_enabled=True,
        email_provider="imap",
        weather_location="",
    )

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2"])

    # Patch all external calls so briefing can run without network
    with _patch_imap(mock_conn), \
         patch("modules.briefing_tools._weather_section", return_value="Weather: clear."), \
         patch("modules.briefing_tools._reminders_section", return_value=""), \
         patch("modules.briefing_tools._calendar_section", return_value=""), \
         patch("modules.briefing_tools._news_section", return_value=""):
        from modules.briefing_tools import morning_briefing
        result = morning_briefing()

    assert "Email: 2 unread." in result
