"""Tests for modules/email_tools.py."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


def _mock_fetch_response(
    from_addr: str = "alice@example.com",
    subject: str = "Hello",
    date: str = "Mon, 1 Jan 2024 12:00:00 +0000",
    flags: str = "",
) -> tuple:
    """Build a fake imaplib fetch response tuple."""
    headers = f"From: {from_addr}\r\nSubject: {subject}\r\nDate: {date}\r\n\r\n".encode()
    flags_part = (
        f"1 (FLAGS ({flags}) BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{{len(headers)}}}".encode()
    )
    return ("OK", [(flags_part, headers), b")"])


def _make_imap_mock(search_result: bytes = b"1 2 3", **fetch_kwargs):
    """Build an IMAP mock with preset search and fetch returns."""
    conn = MagicMock()
    conn.search.return_value = ("OK", [search_result])
    conn.fetch.return_value = _mock_fetch_response(**fetch_kwargs)
    return conn


@pytest.fixture
def imap_cfg():
    from core.config import update_config
    update_config(
        email_provider="imap",
        email_imap_host="mail.example.com",
        email_imap_port=993,
        email_smtp_host="smtp.example.com",
        email_smtp_port=587,
        email_username="user@example.com",
        email_password="secret",
    )


def _patch_imap(mock_conn):
    """Context manager that patches imap_connection to yield mock_conn."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.imap_connection", return_value=cm)


def _patch_smtp(mock_conn):
    """Context manager that patches smtp_connection to yield mock_conn."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.smtp_connection", return_value=cm)


# --- list_inbox ---

def test_list_inbox_not_configured():
    from modules.email_tools import list_inbox
    result = list_inbox()
    assert "not configured" in result.lower()


def test_list_inbox_returns_formatted_lines(imap_cfg):
    mock_conn = _make_imap_mock(b"1 2 3", from_addr="alice@example.com", subject="Invoice")
    with _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox(max_items=5)
    assert "alice@example.com" in result
    assert "Invoice" in result


def test_list_inbox_empty_inbox(imap_cfg):
    mock_conn = _make_imap_mock(b"")
    with _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "empty" in result.lower() or "no messages" in result.lower()


def test_list_inbox_spam_flag_shown(imap_cfg):
    mock_conn = _make_imap_mock(b"1", flags="\\Junk")
    with _patch_imap(mock_conn):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "SPAM" in result


def test_list_inbox_connection_error(imap_cfg):
    with patch("agents.email_client.imap_connection", side_effect=OSError("refused")):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "could not connect" in result.lower() or "refused" in result.lower()


# --- search_email ---

def test_search_email_not_configured():
    from modules.email_tools import search_email
    result = search_email("invoice")
    assert "not configured" in result.lower()


def test_search_email_uses_imap_text(imap_cfg):
    mock_conn = _make_imap_mock(b"1", from_addr="bob@example.com", subject="Invoice Q4")
    with _patch_imap(mock_conn):
        from modules.email_tools import search_email
        result = search_email("invoice")
    mock_conn.search.assert_called_with(None, 'TEXT "invoice"')
    assert "Invoice Q4" in result


def test_search_email_uses_xgmraw_for_gmail():
    from core.config import update_config
    update_config(email_provider="gmail", email_username="user@gmail.com")
    mock_conn = _make_imap_mock(b"")
    with _patch_imap(mock_conn):
        from modules.email_tools import search_email
        search_email("from:alice")
    mock_conn.search.assert_called_with(None, 'X-GM-RAW "from:alice"')


def test_search_email_no_results(imap_cfg):
    mock_conn = _make_imap_mock(b"")
    with _patch_imap(mock_conn):
        from modules.email_tools import search_email
        result = search_email("xyzzy_nonexistent")
    assert "no emails found" in result.lower() or "not found" in result.lower()


# --- send_email ---

def test_send_email_not_configured():
    from modules.email_tools import send_email
    result = send_email("bob@example.com", "Hi", "Body text")
    assert "not configured" in result.lower()


def test_send_email_calls_sendmail(imap_cfg):
    mock_conn = MagicMock()
    with _patch_smtp(mock_conn):
        from modules.email_tools import send_email
        result = send_email("bob@example.com", "Hello", "Hi there!")
    args = mock_conn.sendmail.call_args[0]
    assert args[0] == "user@example.com"
    assert args[1] == ["bob@example.com"]
    assert "Hi there!" in args[2]
    assert "bob@example.com" in result


def test_send_email_smtp_error(imap_cfg):
    import smtplib
    with patch("agents.email_client.smtp_connection", side_effect=smtplib.SMTPException("relay denied")):
        from modules.email_tools import send_email
        result = send_email("bob@example.com", "Hi", "Body")
    assert "failed to send" in result.lower() or "relay denied" in result.lower()


# --- supervisor routing ---

def test_supervisor_keywords_route_to_list_inbox():
    from core.supervisor import _direct_tool
    assert _direct_tool("check my email") == "list_inbox"
    assert _direct_tool("any new emails?") == "list_inbox"
    assert _direct_tool("read my inbox please") == "list_inbox"


