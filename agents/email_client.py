from __future__ import annotations
import base64
import contextlib
import imaplib
import logging
import smtplib
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://mail.google.com/"]
_TOKEN_FILENAME = "gmail_token.json"


def _token_path() -> Path:
    from core.config import get_config
    return Path(get_config().memory_dir) / _TOKEN_FILENAME


def get_gmail_credentials():
    """Return valid OAuth2 Credentials or None if not authorized / not installed."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    path = _token_path()
    if not path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(path), _SCOPES)
    except Exception:
        logger.exception("Failed to load Gmail token from %s", path)
        return None
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            path.write_text(creds.to_json())
        except Exception:
            logger.exception("Failed to refresh Gmail token")
            return None
    return creds if creds.valid else None


def build_auth_url(credentials_file: str, redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(credentials_file, scopes=_SCOPES, redirect_uri=redirect_uri)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return auth_url


def exchange_code(credentials_file: str, redirect_uri: str, code: str) -> None:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(credentials_file, scopes=_SCOPES, redirect_uri=redirect_uri)
    flow.fetch_token(code=code)
    path = _token_path()
    path.write_text(flow.credentials.to_json())
    logger.info("Gmail token saved to %s", path)


def is_connected() -> bool:
    return get_gmail_credentials() is not None


@contextlib.contextmanager
def imap_connection() -> Iterator[imaplib.IMAP4_SSL]:
    """Yield an authenticated IMAP4_SSL connection. Always calls logout on exit."""
    from core.config import get_config
    cfg = get_config()
    conn = None
    try:
        if cfg.email_provider == "gmail":
            creds = get_gmail_credentials()
            if creds is None:
                raise RuntimeError("Gmail not authorized — connect via Settings → Email")
            auth_string = f"user={cfg.email_username}\x01auth=Bearer {creds.token}\x01\x01"
            conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            conn.authenticate("XOAUTH2", lambda x: auth_string.encode())
        else:
            conn = imaplib.IMAP4_SSL(cfg.email_imap_host, cfg.email_imap_port)
            conn.login(cfg.email_username, cfg.email_password)
        yield conn
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


@contextlib.contextmanager
def smtp_connection() -> Iterator[smtplib.SMTP]:
    """Yield an authenticated SMTP connection. Always calls quit on exit."""
    from core.config import get_config
    cfg = get_config()
    conn = None
    try:
        if cfg.email_provider == "gmail":
            creds = get_gmail_credentials()
            if creds is None:
                raise RuntimeError("Gmail not authorized — connect via Settings → Email")
            auth_bytes = base64.b64encode(
                f"user={cfg.email_username}\x01auth=Bearer {creds.token}\x01\x01".encode()
            )
            conn = smtplib.SMTP("smtp.gmail.com", 587)
            conn.ehlo()
            conn.starttls()
            conn.ehlo()
            code, msg = conn.docmd("AUTH", f"XOAUTH2 {auth_bytes.decode()}")
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, msg)
        else:
            conn = smtplib.SMTP(cfg.email_smtp_host, cfg.email_smtp_port)
            conn.ehlo()
            conn.starttls()
            conn.ehlo()
            conn.login(cfg.email_username, cfg.email_password)
        yield conn
    finally:
        if conn is not None:
            try:
                conn.quit()
            except Exception:
                pass
