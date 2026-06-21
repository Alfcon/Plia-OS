from __future__ import annotations
import base64
import contextlib
import logging
import smtplib
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

_SCOPES = ["https://mail.google.com/"]


def _client_dir() -> Path:
    from agents.email_store import client_dir
    return client_dir()


def _token_path(account_name: str) -> Path:
    safe = account_name.replace(" ", "_").replace("/", "_")
    return _client_dir() / f"{safe}_gmail_token.json"


def get_gmail_credentials(account: dict):
    """Return valid OAuth2 Credentials for the account, or None."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    path = _token_path(account["name"])
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
            logger.exception("Failed to refresh Gmail token for %s", account["name"])
            return None
    return creds if creds.valid else None


def build_auth_url(account: dict, redirect_uri: str) -> tuple[str, str, str]:
    """Return (auth_url, state, code_verifier). Verifier may be empty if PKCE not used."""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        account["gmail_credentials_file"], scopes=_SCOPES, redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    verifier = getattr(flow, "code_verifier", None) or ""
    return auth_url, state, verifier


def exchange_code(account: dict, redirect_uri: str, code: str, code_verifier: str = "") -> None:
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(
        account["gmail_credentials_file"], scopes=_SCOPES, redirect_uri=redirect_uri
    )
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    path = _token_path(account["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(flow.credentials.to_json())
    logger.info("Gmail token saved to %s", path)


def is_connected(account: dict) -> bool:
    if account.get("provider") == "gmail":
        return get_gmail_credentials(account) is not None
    return bool(account.get("username"))


@contextlib.contextmanager
def imap_connection(account: dict):
    """Yield an authenticated imap_tools MailBox. Handles Gmail XOAUTH2 and generic IMAP."""
    from imap_tools import MailBox
    if account.get("provider") == "gmail":
        creds = get_gmail_credentials(account)
        if creds is None:
            raise RuntimeError(
                f"Gmail not authorized for '{account['name']}' — connect via Settings → Email"
            )
        with MailBox("imap.gmail.com", 993).xoauth2(account["username"], creds.token) as mb:
            yield mb
    else:
        with MailBox(account["imap_host"], account.get("imap_port", 993)).login(
            account["username"], account["password"]
        ) as mb:
            yield mb


@contextlib.contextmanager
def smtp_connection(account: dict) -> Iterator[smtplib.SMTP]:
    """Yield an authenticated SMTP connection. Always calls quit on exit."""
    conn = None
    try:
        if account.get("provider") == "gmail":
            creds = get_gmail_credentials(account)
            if creds is None:
                raise RuntimeError(
                    f"Gmail not authorized for '{account['name']}' — connect via Settings → Email"
                )
            auth_bytes = base64.b64encode(
                f"user={account['username']}\x01auth=Bearer {creds.token}\x01\x01".encode()
            )
            conn = smtplib.SMTP("smtp.gmail.com", 587)
            conn.ehlo()
            conn.starttls()
            conn.ehlo()
            code, msg = conn.docmd("AUTH", f"XOAUTH2 {auth_bytes.decode()}")
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, msg)
        else:
            conn = smtplib.SMTP(account["smtp_host"], account.get("smtp_port", 587))
            conn.ehlo()
            conn.starttls()
            conn.ehlo()
            conn.login(account["username"], account["password"])
        yield conn
    finally:
        if conn is not None:
            try:
                conn.quit()
            except Exception:
                pass
