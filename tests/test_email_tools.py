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


def _make_msg(from_addr="alice@example.com", subject="Hello",
              text="Email body text.", flags=()):
    msg = MagicMock()
    msg.from_ = from_addr
    msg.subject = subject
    msg.text = text
    msg.html = None
    msg.flags = flags
    return msg


def _patch_imap(messages):
    mock_mb = MagicMock()
    mock_mb.fetch.return_value = messages
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_mb)
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


def _patch_summarize(summaries):
    return patch("modules.email_tools._summarize_batch", return_value=summaries)


# --- list_inbox ---

def test_list_inbox_not_configured():
    with patch("agents.email_store.get_default_account", return_value=None):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "not configured" in result.lower() or "no email accounts" in result.lower()


def test_list_inbox_returns_formatted_lines():
    msgs = [_make_msg(from_addr="alice@example.com", subject="Invoice")]
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(msgs), _patch_summarize(["Invoice summary."]):
        from modules.email_tools import list_inbox
        result = list_inbox(max_items=5)
    assert "alice@example.com" in result
    assert "Invoice" in result
    assert "Invoice summary." in result
    assert "From:      |" in result
    assert "Date Sent: |" in result
    assert "Subject:   |" in result
    assert "Body:      |" in result


def test_list_inbox_empty_inbox():
    with _patch_default(_IMAP_ACCOUNT), _patch_imap([]):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "empty" in result.lower() or "no messages" in result.lower()


def test_list_inbox_spam_flag_shown():
    msgs = [_make_msg(flags=("\\Junk",))]
    with _patch_default(_IMAP_ACCOUNT), _patch_imap(msgs), _patch_summarize(["Spam."]):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "SPAM" in result or "Junk" in result or "Spam" in result


def test_list_inbox_connection_error():
    with _patch_default(_IMAP_ACCOUNT), \
         patch("agents.email_client.imap_connection", side_effect=OSError("refused")):
        from modules.email_tools import list_inbox
        result = list_inbox()
    assert "could not connect" in result.lower() or "refused" in result.lower()


def test_list_inbox_named_account():
    msgs = [_make_msg(from_addr="boss@work.com", subject="Meeting")]
    with _patch_get(_IMAP_ACCOUNT), _patch_imap(msgs), _patch_summarize(["Meeting summary."]):
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
    msgs = [_make_msg(from_addr="bob@example.com", subject="Invoice Q4")]
    mock_mb = MagicMock()
    mock_mb.fetch.return_value = msgs
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_mb)
    cm.__exit__ = MagicMock(return_value=False)
    with _patch_default(_IMAP_ACCOUNT), \
         patch("agents.email_client.imap_connection", return_value=cm), \
         _patch_summarize(["Invoice summary."]):
        from modules.email_tools import search_email
        result = search_email("invoice")
    criteria = mock_mb.fetch.call_args[0][0]
    assert 'TEXT "invoice"' in criteria
    assert "Invoice Q4" in result


def test_search_email_uses_xgmraw_for_gmail():
    mock_mb = MagicMock()
    mock_mb.fetch.return_value = []
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_mb)
    cm.__exit__ = MagicMock(return_value=False)
    with _patch_default(_GMAIL_ACCOUNT), \
         patch("agents.email_client.imap_connection", return_value=cm):
        from modules.email_tools import search_email
        search_email("from:alice")
    criteria = mock_mb.fetch.call_args[0][0]
    assert "X-GM-RAW" in criteria
    assert "from:alice" in criteria


def test_search_email_no_results():
    with _patch_default(_IMAP_ACCOUNT), _patch_imap([]):
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


def test_supervisor_keywords_route_send_email_to_respond():
    from core.supervisor import _keyword_route
    assert _keyword_route("send email to bob@example.com") == "respond"
    assert _keyword_route("send an email to my boss") == "respond"
    assert _keyword_route("email to alice about the meeting") == "respond"
    assert _keyword_route("compose an email to support") == "respond"


def test_extract_email_search_query():
    from core.supervisor import _extract_email_search
    assert _extract_email_search("search my email for the Steam gift") == "the Steam gift"
    assert _extract_email_search("search email for invoices") == "invoices"
    assert _extract_email_search("find emails about Amazon") == "Amazon"
    assert _extract_email_search("find my inbox for Steam") == "Steam"
    assert _extract_email_search("check my email") is None


# --- _parse_from ---

def test_parse_from_with_display_name():
    from modules.email_tools import _parse_from
    result = _parse_from("Alice Smith <alice@example.com>")
    assert result == "Alice Smith - alice@example.com"


def test_parse_from_addr_only():
    from modules.email_tools import _parse_from
    result = _parse_from("alice@example.com")
    assert "alice@example.com" in result
