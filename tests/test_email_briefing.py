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


def _patch_imap(n_messages):
    """Patch imap_connection to yield a mailbox whose fetch() returns n_messages mocks."""
    mock_mb = MagicMock()
    mock_mb.fetch.return_value = [MagicMock() for _ in range(n_messages)]
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_mb)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.imap_connection", return_value=cm)


def _patch_accounts(accounts):
    return patch("agents.email_store.list_accounts", return_value=accounts)


def test_email_section_no_accounts_returns_empty():
    with _patch_accounts([]):
        from modules.briefing_tools import _email_section
        assert _email_section() == ""


def test_email_section_none_briefing_enabled_returns_empty():
    accounts = [{**_BRIEFING_ACCOUNT, "briefing_enabled": False}]
    with _patch_accounts(accounts):
        from modules.briefing_tools import _email_section
        assert _email_section() == ""


def test_email_section_unread_count():
    with _patch_accounts([_BRIEFING_ACCOUNT]), _patch_imap(3):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert "Email:" in result
    assert "3 unread" in result


def test_email_section_zero_unread_returns_empty():
    with _patch_accounts([_BRIEFING_ACCOUNT]), _patch_imap(0):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert result == ""


def test_email_section_connection_fails_returns_empty():
    with _patch_accounts([_BRIEFING_ACCOUNT]), \
         patch("agents.email_client.imap_connection", side_effect=OSError("timeout")):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert result == ""


def test_email_section_multiple_accounts():
    acc1 = {**_BRIEFING_ACCOUNT, "name": "Personal"}
    acc2 = {**_BRIEFING_ACCOUNT, "name": "Work"}
    with _patch_accounts([acc1, acc2]), _patch_imap(2):
        from modules.briefing_tools import _email_section
        result = _email_section()
    assert "Personal" in result
    assert "Work" in result


def test_morning_briefing_includes_email_section():
    with _patch_accounts([_BRIEFING_ACCOUNT]), \
         _patch_imap(2), \
         patch("modules.briefing_tools._weather_section", return_value="Weather: clear."), \
         patch("modules.briefing_tools._reminders_section", return_value=""), \
         patch("modules.briefing_tools._calendar_section", return_value=""), \
         patch("modules.briefing_tools._news_section", return_value=""):
        from modules.briefing_tools import morning_briefing
        result = morning_briefing()

    assert "Email:" in result
    assert "unread" in result
