"""Tests for agents/email_client.py connection helpers."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


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
        email_password="secret123",
    )


def test_imap_connection_generic_login(imap_cfg):
    """Generic IMAP opens SSL connection and calls LOGIN."""
    mock_conn = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=mock_conn) as mock_cls:
        from agents.email_client import imap_connection
        with imap_connection() as conn:
            assert conn is mock_conn
        mock_cls.assert_called_once_with("mail.example.com", 993)
        mock_conn.login.assert_called_once_with("user@example.com", "secret123")
        mock_conn.logout.assert_called_once()


def test_imap_connection_logout_on_exception(imap_cfg):
    """IMAP connection always calls logout even if body raises."""
    mock_conn = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=mock_conn):
        from agents.email_client import imap_connection
        with pytest.raises(ValueError):
            with imap_connection():
                raise ValueError("oops")
        mock_conn.logout.assert_called_once()


def test_smtp_connection_generic_login(imap_cfg):
    """Generic SMTP opens connection, STARTTLS, then LOGIN."""
    mock_conn = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_conn) as mock_cls:
        from agents.email_client import smtp_connection
        with smtp_connection() as conn:
            assert conn is mock_conn
        mock_cls.assert_called_once_with("smtp.example.com", 587)
        assert mock_conn.ehlo.call_count == 2
        mock_conn.starttls.assert_called_once()
        mock_conn.login.assert_called_once_with("user@example.com", "secret123")
        mock_conn.quit.assert_called_once()


def test_imap_connection_gmail_uses_xoauth2():
    """Gmail IMAP uses XOAUTH2 instead of LOGIN."""
    from core.config import update_config
    update_config(email_provider="gmail", email_username="user@gmail.com")

    mock_creds = MagicMock()
    mock_creds.token = "fake_access_token"
    mock_creds.valid = True

    mock_conn = MagicMock()
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("imaplib.IMAP4_SSL", return_value=mock_conn):
        from agents.email_client import imap_connection
        with imap_connection() as conn:
            assert conn is mock_conn
        mock_conn.authenticate.assert_called_once()
        call_args = mock_conn.authenticate.call_args
        assert call_args[0][0] == "XOAUTH2"
        callback = mock_conn.authenticate.call_args[0][1]
        assert isinstance(callback(None), bytes)
        mock_conn.login.assert_not_called()


def test_imap_connection_gmail_raises_if_no_credentials():
    """Gmail IMAP raises RuntimeError when not authorized."""
    from core.config import update_config
    update_config(email_provider="gmail", email_username="user@gmail.com")

    with patch("agents.email_client.get_gmail_credentials", return_value=None):
        from agents.email_client import imap_connection
        with pytest.raises(RuntimeError, match="not authorized"):
            with imap_connection():
                pass


def test_smtp_connection_gmail_uses_xoauth2():
    """Gmail SMTP uses XOAUTH2 AUTH command instead of LOGIN."""
    from core.config import update_config
    update_config(email_provider="gmail", email_username="user@gmail.com")

    mock_creds = MagicMock()
    mock_creds.token = "fake_access_token"
    mock_creds.valid = True

    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (235, b"2.7.0 Accepted")
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("smtplib.SMTP", return_value=mock_conn):
        from agents.email_client import smtp_connection
        with smtp_connection() as conn:
            assert conn is mock_conn
        mock_conn.docmd.assert_called_once()
        assert mock_conn.docmd.call_args[0][0] == "AUTH"
        assert mock_conn.docmd.call_args[0][1].startswith("XOAUTH2 ")
        mock_conn.login.assert_not_called()


def test_smtp_connection_gmail_raises_if_no_credentials():
    """Gmail SMTP raises RuntimeError when not authorized."""
    from core.config import update_config
    update_config(email_provider="gmail", email_username="user@gmail.com")

    with patch("agents.email_client.get_gmail_credentials", return_value=None):
        from agents.email_client import smtp_connection
        with pytest.raises(RuntimeError, match="not authorized"):
            with smtp_connection():
                pass


def test_smtp_connection_gmail_raises_on_auth_failure():
    """Gmail SMTP raises SMTPAuthenticationError when AUTH returns non-235."""
    import smtplib
    from core.config import update_config
    update_config(email_provider="gmail", email_username="user@gmail.com")

    mock_creds = MagicMock()
    mock_creds.token = "fake_token"
    mock_creds.valid = True

    mock_conn = MagicMock()
    mock_conn.docmd.return_value = (535, b"5.7.8 Bad credentials")

    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("smtplib.SMTP", return_value=mock_conn):
        from agents.email_client import smtp_connection
        with pytest.raises(smtplib.SMTPAuthenticationError):
            with smtp_connection():
                pass


def test_is_connected_false_when_no_token():
    """is_connected() returns False when gmail_token.json absent."""
    from core.config import update_config
    update_config(email_provider="gmail")
    with patch("agents.email_client.get_gmail_credentials", return_value=None):
        from agents.email_client import is_connected
        assert is_connected() is False


def test_is_connected_true_when_credentials_valid():
    """is_connected() returns True when credentials load successfully."""
    from core.config import update_config
    update_config(email_provider="gmail")
    mock_creds = MagicMock()
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds):
        from agents.email_client import is_connected
        assert is_connected() is True
