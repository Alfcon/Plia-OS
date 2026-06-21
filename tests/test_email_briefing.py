"""Tests for email section in morning briefing."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

_BRIEFING_ACCOUNT = {
    "name": "Gmail",
    "provider": "imap",
    "username": "user@example.com",
    "briefing_enabled": True,
}


def _patch_imap(mock_conn):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.imap_connection", return_value=cm)


def _patch_accounts(accounts):
    return patch("agents.email_store.list_accounts", return_value=accounts)


def test_email_section_no_accounts_returns_empty():
    """_email_section returns '' when no accounts configured."""
    with _patch_accounts([]):
        from modules.briefing_tools import _email_section
        assert _email_section() == ""


def test_email_section_none_briefing_enabled_returns_empty():
    """_email_section returns '' when no account has briefing_enabled."""
    accounts = [{**_BRIEFING_ACCOUNT, "briefing_enabled": False}]
    with _patch_accounts(accounts):
        from modules.briefing_tools import _email_section
        assert _email_section() == ""


def test_email_section_unread_count():
    """_email_section returns 'Email: Name: N unread.' for one account."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2 3"])
    with _patch_accounts([_BRIEFING_ACCOUNT]), _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert "Email:" in result
    assert "3 unread" in result
    mock_conn.search.assert_called_with(None, "UNSEEN")


def test_email_section_zero_unread_returns_empty():
    """_email_section returns '' when there are no unread messages."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])
    with _patch_accounts([_BRIEFING_ACCOUNT]), _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert result == ""


def test_email_section_connection_fails_returns_empty():
    """_email_section returns '' and does not crash when IMAP fails."""
    with _patch_accounts([_BRIEFING_ACCOUNT]), \
         patch("agents.email_client.imap_connection", side_effect=OSError("timeout")):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert result == ""


def test_email_section_multiple_accounts():
    """_email_section aggregates unread counts across multiple briefing-enabled accounts."""
    acc1 = {**_BRIEFING_ACCOUNT, "name": "Personal"}
    acc2 = {**_BRIEFING_ACCOUNT, "name": "Work"}
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2"])
    with _patch_accounts([acc1, acc2]), _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert "Personal" in result
    assert "Work" in result


def test_morning_briefing_includes_email_section():
    """morning_briefing() output includes email line when unread > 0."""
    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2"])

    with _patch_accounts([_BRIEFING_ACCOUNT]), \
         _patch_imap(mock_conn), \
         patch("modules.briefing_tools._weather_section", return_value="Weather: clear."), \
         patch("modules.briefing_tools._reminders_section", return_value=""), \
         patch("modules.briefing_tools._calendar_section", return_value=""), \
         patch("modules.briefing_tools._news_section", return_value=""):
        from modules.briefing_tools import morning_briefing
        result = morning_briefing()

    assert "Email:" in result
    assert "unread" in result
