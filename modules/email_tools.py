from __future__ import annotations
import logging
import smtplib
from email.mime.text import MIMEText

from core.registry import tool

logger = logging.getLogger(__name__)

_NO_ACCOUNTS = "No email accounts configured. Add one via Settings → Email."


def _resolve(account_name: str) -> dict | None:
    from agents.email_store import get_account, get_default_account
    if account_name:
        return get_account(account_name)
    return get_default_account()


def _format_msg(i: int, msg) -> str:
    is_spam = "\\Junk" in (msg.flags or ()) or "\\Spam" in (msg.flags or ())
    spam_tag = " [SPAM]" if is_spam else ""
    return (
        f"[{i}]\n"
        f"  From: {msg.from_ or 'Unknown'}\n"
        f"  Subject: {msg.subject or '(no subject)'}{spam_tag}\n"
        f"  Date: {msg.date_str or ''}"
    )


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
        with imap_connection(acc) as mb:
            msgs = list(mb.fetch("ALL", limit=max_items, reverse=True, bulk=True, mark_seen=False))
        if not msgs:
            return f"[{acc['name']}] Inbox is empty."
        lines = [_format_msg(i, msg) for i, msg in enumerate(msgs, 1)]
        prefix = f"[{acc['name']}] " if account else ""
        return prefix + "\n".join(lines)
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
        safe_q = query.replace('"', "")
        criteria = f'X-GM-RAW "{safe_q}"' if acc.get("provider") == "gmail" else f'TEXT "{safe_q}"'
        with imap_connection(acc) as mb:
            msgs = list(mb.fetch(criteria, limit=max_items, reverse=True, bulk=True, mark_seen=False))
        if not msgs:
            return f"No emails found for '{query}'."
        lines = [_format_msg(i, msg) for i, msg in enumerate(msgs, 1)]
        return "\n".join(lines)
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
