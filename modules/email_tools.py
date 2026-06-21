from __future__ import annotations
import email as _email_lib
import logging
import smtplib
from email.mime.text import MIMEText

from core.config import get_config
from core.registry import tool

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "Email not configured. Set email_provider in Settings → Email."


def _fmt(value: str | None, limit: int = 80) -> str:
    return (value or "Unknown")[:limit]


def _fetch_headers(conn, nums: list[bytes], max_items: int) -> list[str]:
    """Fetch FROM/SUBJECT/DATE/FLAGS for the last max_items message numbers."""
    recent = nums[-max_items:][::-1]
    lines = []
    for i, num in enumerate(recent, 1):
        _, data = conn.fetch(num, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if not data or data[0] is None:
            continue
        raw = data[0]
        if not isinstance(raw, tuple):
            continue
        flags_str = raw[0].decode(errors="replace")
        msg = _email_lib.message_from_bytes(raw[1])
        from_ = _fmt(msg.get("From"))
        subject = msg.get("Subject") or "(no subject)"
        date = msg.get("Date") or ""
        is_spam = "\\Junk" in flags_str or "\\Spam" in flags_str
        spam_tag = " [SPAM]" if is_spam else ""
        lines.append(f"[{i}] From: {from_} | Subject: {subject} | Date: {date}{spam_tag}")
    return lines


@tool("List recent inbox emails. Returns sender, subject, date, and whether each is spam.")
def list_inbox(max_items: int = 10) -> str:
    cfg = get_config()
    if not cfg.email_provider:
        return _NOT_CONFIGURED
    try:
        from agents.email_client import imap_connection
        with imap_connection() as conn:
            conn.select("INBOX", readonly=True)
            _, data = conn.search(None, "ALL")
            nums = data[0].split() if data[0] else []
            if not nums:
                return "Inbox is empty."
            lines = _fetch_headers(conn, nums, max_items)
        return "\n".join(lines) if lines else "No messages found."
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"


@tool(
    "Search emails by query. Gmail supports full search syntax "
    "(from:, subject:, is:unread, etc.). Generic IMAP uses keyword search."
)
def search_email(query: str, max_items: int = 10) -> str:
    cfg = get_config()
    if not cfg.email_provider:
        return _NOT_CONFIGURED
    try:
        from agents.email_client import imap_connection
        with imap_connection() as conn:
            conn.select("INBOX", readonly=True)
            if cfg.email_provider == "gmail":
                _, data = conn.search(None, f'X-GM-RAW "{query}"')
            else:
                _, data = conn.search(None, f'TEXT "{query}"')
            nums = data[0].split() if data[0] else []
            if not nums:
                return f"No emails found for '{query}'."
            lines = _fetch_headers(conn, nums, max_items)
        return "\n".join(lines) if lines else f"No emails found for '{query}'."
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"


@tool("Send an email. Provide the recipient's email address, subject line, and message body.")
def send_email(to: str, subject: str, body: str) -> str:
    cfg = get_config()
    if not cfg.email_provider:
        return _NOT_CONFIGURED
    try:
        msg = MIMEText(body, "plain")
        msg["From"] = cfg.email_username
        msg["To"] = to
        msg["Subject"] = subject
        from agents.email_client import smtp_connection
        with smtp_connection() as conn:
            conn.sendmail(cfg.email_username, [to], msg.as_string())
        return f"Email sent to {to}."
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except smtplib.SMTPException as exc:
        return f"Failed to send email: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"
