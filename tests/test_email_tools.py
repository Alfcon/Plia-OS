"""Tests for modules/email_tools.py."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

_IMAP_ACCOUNT = {
    "name": "Work",
    "provider": "imap",
    "username": "user@example.com",
    "password": "secret",
    "imap_host": "mail.example.com",
    "imap_port": 993,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "briefing_enabled": False,
}

_GMAIL_ACCOUNT = {
    "name": "Gmail",
    "provider": "gmail",
    "username": "user@gmail.com",
    "gmail_credentials_file": "/fake/creds.json",
    "briefing_enabled": False,
}


def _mock_fetch_response(
    from_addr: str = "alice@example.com",
    subject: str = "Hello",
    date: str = "Mon, 1 Jan 2024 12:00:00 +0000",
    flags: str = "",
) -> tuple:
    headers = f"From: {from_addr}\r\nSubject: {subject}\r\nDate: {date}\r\n\r\n".encode()
    flags_part = (
        f"1 (FLAGS ({flags}) BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{{len(headers)}}}".encode()
    )
    return ("OK", [(flags_part, headers), b")"])


def _make_imap_mock(search_result: bytes = b"1 2 3", **fetch_kwargs):
    conn = MagicMock()
    conn.search.return_value = ("OK", [search_result])
    conn.fetch.return_value = _mock_fetch_response(**fetch_kwargs)
    return conn


def _patch_imap(mock_conn):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.imap_connection", return_value=cm)


def _patch_smtp(mock_conn):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.smtp_connection", return_value=cm)


def _patch_default(account):
    return patch("agents.email_store.get_default_account", return_value=account)


def _patch_get(account):
    return patch("agents.email_store.get_account", return_value=account)


# --- list_inbox ---

def test_list_inbox_not_configured():
    with patch("agents.email_store.get_default_account", return_value=None):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "not configured" in result.lower() or "no email accounts" in result.lower()


def test_list_inbox_returns_formatted_lines():
    mock_conn = _make_imap_mock(b"1 2 3", from_addr="alice@example.com", subject="Invoice")
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox(max_items=5)
    assert "alice@example.com" in result
    assert "Invoice" in result


def test_list_inbox_empty_inbox():
    mock_conn = _make_imap_mock(b"")
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "empty" in result.lower() or "no messages" in result.lower()


def test_list_inbox_spam_flag_shown():
    mock_conn = _make_imap_mock(b"1", flags="\\Junk")
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "SPAM" in result


def test_list_inbox_connection_error():
    with _patch_default(_IMAP_ACCOUNT), \
         patch("agents.email_client.imap_connection", side_effect=OSError("refused")):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "could not connect" in result.lower() or "refused" in result.lower()


def test_list_inbox_named_account():
    """list_inbox(account='Work') uses get_account, not get_default_account."""
    mock_conn = _make_imap_mock(b"1", from_addr="boss@work.com", subject="Meeting")
    with _patch_get(_IMAP_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox(account="Work")
    assert "boss@work.com" in result


# --- search_email ---

def test_search_email_not_configured():
    with patch("agents.email_store.get_default_account", return_value=None):
        from modules.email_tools import search_email
        result = search_email("invoice")
    assert "not configured" in result.lower() or "no email accounts" in result.lower()


def test_search_email_uses_imap_text():
    mock_conn = _make_imap_mock(b"1", from_addr="bob@example.com", subject="Invoice Q4")
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import search_email
        result = search_email("invoice")
    mock_conn.search.assert_called_with(None, 'TEXT "invoice"')
    assert "Invoice Q4" in result


def test_search_email_uses_xgmraw_for_gmail():
    mock_conn = _make_imap_mock(b"")
    with _patch_default(_GMAIL_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import search_email
        search_email("from:alice")
    mock_conn.search.assert_called_with(None, 'X-GM-RAW "from:alice"')


def test_search_email_no_results():
    mock_conn = _make_imap_mock(b"")
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(mock_conn):
        from modules.email_tools import search_email
        result = search_email("xyzzy_nonexistent")
    assert "no emails found" in result.lower() or "not found" in result.lower()


# --- send_email ---

def test_send_email_not_configured():
    with patch("agents.email_store.get_default_account", return_value=None):
        from modules.email_tools import send_email
        result = send_email("bob@example.com", "Hi", "Body text")
    assert "not configured" in result.lower() or "no email accounts" in result.lower()


def test_send_email_calls_sendmail():
    mock_conn = MagicMock()
    with _patch_default(_IMAP_ACCOUNT), _patch_smtp(mock_conn):
        from modules.email_tools import send_email
        result = send_email("bob@example.com", "Hello", "Hi there!")
    args = mock_conn.sendmail.call_args[0]
    assert args[0] == "user@example.com"
    assert args[1] == ["bob@example.com"]
    assert "Hi there!" in args[2]
    assert "bob@example.com" in result


def test_send_email_smtp_error():
    import smtplib
    with _patch_default(_IMAP_ACCOUNT), \
         patch("agents.email_client.smtp_connection", side_effect=smtplib.SMTPException("relay denied")):
        from modules.email_tools import send_email
        result = send_email("bob@example.com", "Hi", "Body")
    assert "failed to send" in result.lower() or "relay denied" in result.lower()


def test_send_email_uses_named_account():
    """send_email(account='Work') uses get_account."""
    mock_conn = MagicMock()
    with _patch_get(_IMAP_ACCOUNT), _patch_smtp(mock_conn):
        from modules.email_tools import send_email
        result = send_email("bob@example.com", "Hi", "Hello", account="Work")
    assert "bob@example.com" in result


# --- supervisor routing ---

def test_supervisor_keywords_route_to_list_inbox():
    from core.supervisor import _direct_tool
    assert _direct_tool("check my email") == "list_inbox"
    assert _direct_tool("any new emails?") == "list_inbox"
    assert _direct_tool("read my inbox please") == "list_inbox"
