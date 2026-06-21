"""Tests for agents/email_client.py connection helpers."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

_IMAP_ACCOUNT = {
    "name": "Work",
    "provider": "imap",
    "username": "user@example.com",
    "password": "secret123",
    "imap_host": "mail.example.com",
    "imap_port": 993,
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
}

_GMAIL_ACCOUNT = {
    "name": "Gmail",
    "provider": "gmail",
    "username": "user@gmail.com",
    "gmail_credentials_file": "/fake/credentials.json",
}


def test_imap_connection_generic_login():
    """Generic IMAP opens SSL connection and calls LOGIN."""
    mock_conn = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=mock_conn) as mock_cls:
        from agents.email_client import imap_connection
        with imap_connection(_IMAP_ACCOUNT) as conn:
            assert conn is mock_conn
    mock_cls.assert_called_once_with("mail.example.com", 993)
    mock_conn.login.assert_called_once_with("user@example.com", "secret123")
    mock_conn.logout.assert_called_once()


def test_imap_connection_logout_on_exception():
    """IMAP connection always calls logout even if body raises."""
    mock_conn = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
        from agents.email_client import imap_connection
        with pytest.raises(ValueError):
            with imap_connection(_IMAP_ACCOUNT):
                raise ValueError("oops")
    mock_conn.logout.assert_called_once()


def test_smtp_connection_generic_login():
    """Generic SMTP opens connection, STARTTLS, then LOGIN."""
    mock_conn = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_conn) as mock_cls:
        from agents.email_client import smtp_connection
        with smtp_connection(_IMAP_ACCOUNT) as conn:
            assert conn is mock_conn
    mock_cls.assert_called_once_with("smtp.example.com", 587)
    assert mock_conn.ehlo.call_count == 2
    mock_conn.starttls.assert_called_once()
    mock_conn.login.assert_called_once_with("user@example.com", "secret123")
    mock_conn.quit.assert_called_once()


def test_imap_connection_gmail_uses_xoauth2():
    """Gmail IMAP uses XOAUTH2 instead of LOGIN."""
    mock_creds = MagicMock()
    mock_creds.token = "fake_access_token"
    mock_creds.valid = True

    mock_conn = MagicMock()
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("imaplib.IMAP4_SSL", return_value=mock_conn):
        from agents.email_client import imap_connection
        with imap_connection(_GMAIL_ACCOUNT) as conn:
            assert conn is mock_conn
    mock_conn.authenticate.assert_called_once()
    assert mock_conn.authenticate.call_args[0][0] == "XOAUTH2"
    callback = mock_conn.authenticate.call_args[0][1]
    assert isinstance(callback(None), bytes)
    mock_conn.login.assert_not_called()


def test_imap_connection_gmail_raises_if_no_credentials():
    """Gmail IMAP raises RuntimeError when not authorized."""
    with patch("agents.email_client.get_gmail_credentials", return_value=None):
        from agents.email_client import imap_connection
        with pytest.raises(RuntimeError, match="not authorized"):
            with imap_connection(_GMAIL_ACCOUNT):
                pass


def test_smtp_connection_gmail_uses_xoauth2():
    """Gmail SMTP uses XOAUTH2 AUTH command instead of LOGIN."""
    mock_creds = MagicMock()
    mock_creds.token = "fake_access_token"
    mock_creds.valid = True

    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"2.7.0 Accepted")
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("smtplib.SMTP", return_value=mock_conn):
        from agents.email_client import smtp_connection
        with smtp_connection(_GMAIL_ACCOUNT) as conn:
            assert conn is mock_conn
    mock_conn.docmd.assert_called_once()
    assert mock_conn.docmd.call_args[0][0] == "AUTH"
    assert mock_conn.docmd.call_args[0][1].startswith("XOAUTH2 ")
    mock_conn.login.assert_not_called()


def test_smtp_connection_gmail_raises_if_no_credentials():
    """Gmail SMTP raises RuntimeError when not authorized."""
    with patch("agents.email_client.get_gmail_credentials", return_value=None):
        from agents.email_client import smtp_connection
        with pytest.raises(RuntimeError, match="not authorized"):
            with smtp_connection(_GMAIL_ACCOUNT):
                pass


def test_smtp_connection_gmail_raises_on_auth_failure():
    """Gmail SMTP raises SMTPAuthenticationError when AUTH returns non-235."""
    import smtplib
    mock_creds = MagicMock()
    mock_creds.token = "fake_token"
    mock_creds.valid = True

    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (535, b"5.7.8 Bad credentials")

    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("smtplib.SMTP", return_value=mock_conn):
        from agents.email_client import smtp_connection
        with pytest.raises(smtplib.SMTPAuthenticationError):
            with smtp_connection(_GMAIL_ACCOUNT):
                pass


def test_is_connected_false_when_no_token():
    """is_connected() returns False when no valid Gmail token."""
    with patch("agents.email_client.get_gmail_credentials", return_value=None):
        from agents.email_client import is_connected
        assert is_connected(_GMAIL_ACCOUNT) is False


def test_is_connected_true_when_credentials_valid():
    """is_connected() returns True when credentials load successfully."""
    mock_creds = MagicMock()
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds):
        from agents.email_client import is_connected
        assert is_connected(_GMAIL_ACCOUNT) is True


def test_is_connected_imap_true_when_username_set():
    """is_connected() returns True for IMAP account with username."""
    from agents.email_client import is_connected
    assert is_connected(_IMAP_ACCOUNT) is True


def test_token_path_uses_client_dir(tmp_path):
    """Token file placed under ~/.email_client/, not ~/.plia/."""
    import agents.email_store as es
    import agents.email_client as ec
    original = es._CLIENT_DIR
    try:
        es._CLIENT_DIR = tmp_path / "email_client"
        path = ec._token_path("My Gmail")
        assert str(path).startswith(str(tmp_path / "email_client"))
        assert "My_Gmail_gmail_token.json" in str(path)
    finally:
        es._CLIENT_DIR = original
