from __future__ import annotations
import email as _email_lib
import email.header as _email_header
import logging
import smtplib
from email.mime.text import MIMEText

from core.registry import tool

logger = logging.getLogger(__name__)

_NO_ACCOUNTS = "No email accounts configured. Add one via Settings → Email."


def _decode_header(value: str | None) -> str:
    if not value:
        return "Unknown"
    parts = _email_header.decode_header(value)
    decoded = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(chunk)
    return "".join(decoded)


def _fmt(value: str | None, limit: int = 80) -> str:
    return _decode_header(value)[:limit]


def _resolve(account_name: str) -> dict | None:
    """Return account dict by name, or the first account if name is empty."""
    from agents.email_store import get_account, get_default_account
    if account_name:
        return get_account(account_name)
    return get_default_account()


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
        subject = _decode_header(msg.get("Subject")) or "(no subject)"
        date = msg.get("Date") or ""
        is_spam = "\\Junk" in flags_str or "\\Spam" in flags_str
        spam_tag = " [SPAM]" if is_spam else ""
        lines.append(f"[{i}]\n  From: {from_}\n  Subject: {subject}{spam_tag}\n  Date: {date}")
    return lines


@tool(
    "List recent inbox emails. Returns sender, subject, date, and whether each is spam. "
    "Optionally specify an account name to use a non-default account."
)
def list_inbox(account: str = "", max_items: int = 10) -> str:
    acc = _resolve(account)
    if acc is None:
        return _NO_ACCOUNTS
    try:
        from agents.email_client import imap_connection
        with imap_connection(acc) as conn:
            conn.select("INBOX", readonly=True)
            _, data = conn.search(None, "ALL")
            nums = data[0].split() if data[0] else []
            if not nums:
                return f"[{acc['name']}] Inbox is empty."
            lines = _fetch_headers(conn, nums, max_items)
        prefix = f"[{acc['name']}] " if account else ""
        return prefix + ("\n".join(lines) if lines else "No messages found.")
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"


@tool(
    "Search emails by query. Gmail supports full search syntax "
    "(from:, subject:, is:unread, etc.). Generic IMAP uses keyword search. "
    "Optionally specify an account name."
)
def search_email(query: str, account: str = "", max_items: int = 10) -> str:
    acc = _resolve(account)
    if acc is None:
        return _NO_ACCOUNTS
    try:
        from agents.email_client import imap_connection
        safe_query = query.replace('"', "")
        with imap_connection(acc) as conn:
            conn.select("INBOX", readonly=True)
            if acc.get("provider") == "gmail":
                _, data = conn.search(None, f'X-GM-RAW "{safe_query}"')
            else:
                _, data = conn.search(None, f'TEXT "{safe_query}"')
            nums = data[0].split() if data[0] else []
            if not nums:
                return f"No emails found for '{query}'."
            lines = _fetch_headers(conn, nums, max_items)
        return "\n".join(lines) if lines else f"No emails found for '{query}'."
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"


@tool(
    "Send an email. Provide the recipient's address, subject line, and message body. "
    "Optionally specify an account name to send from a non-default account."
)
def send_email(to: str, subject: str, body: str, account: str = "") -> str:
    acc = _resolve(account)
    if acc is None:
        return _NO_ACCOUNTS
    try:
        msg = MIMEText(body, "plain")
        msg["From"] = acc["username"]
        msg["To"] = to
        msg["Subject"] = subject
        from agents.email_client import smtp_connection
        with smtp_connection(acc) as conn:
            conn.sendmail(acc["username"], [to], msg.as_string())
        return f"Email sent to {to}."
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except smtplib.SMTPException as exc:
        return f"Failed to send email: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"
