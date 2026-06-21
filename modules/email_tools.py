from __future__ import annotations
import logging
import re
import smtplib
from email.mime.text import MIMEText
from email.utils import parseaddr

import httpx

from core.registry import tool

logger = logging.getLogger(__name__)

_NO_ACCOUNTS = "No email accounts configured. Add one via Settings → Email."
_SEP = "-" * 59


def _resolve(account_name: str) -> dict | None:
    from agents.email_store import get_account, get_default_account
    if account_name:
        return get_account(account_name)
    return get_default_account()


def _get_body(msg) -> str:
    text = (msg.text or "").strip()
    if not text and msg.html:
        text = re.sub(r"<[^>]+>", " ", msg.html)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_from(from_str: str) -> str:
    name, addr = parseaddr(from_str or "")
    if name and addr:
        return f"{name} - {addr}"
    return addr or from_str or "Unknown"


def _summarize_batch(bodies: list[str]) -> list[str]:
    """One sync Ollama call to summarize all email bodies. Falls back to truncation."""
    from core.config import get_config
    cfg = get_config()
    numbered = []
    for i, body in enumerate(bodies, 1):
        snippet = body.strip()[:600].replace("\n", " ") or "(empty)"
        numbered.append(f"{i}. {snippet}")
    prompt = (
        "Summarize each email body in one concise sentence. "
        "Reply with ONLY numbered lines matching the input numbers.\n\n"
        + "\n\n".join(numbered)
    )
    try:
        r = httpx.post(
            f"{cfg.ollama_url}/api/chat",
            json={
                "model": cfg.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=60,
        )
        content = r.json()["message"]["content"].strip()
        parsed: dict[int, str] = {}
        for line in content.splitlines():
            m = re.match(r"(\d+)[.):\-]\s*(.*)", line.strip())
            if m:
                parsed[int(m.group(1))] = m.group(2).strip()
        return [parsed.get(i + 1, body[:150].replace("\n", " ")) for i, body in enumerate(bodies)]
    except Exception:
        logger.exception("Email summarization failed")
        return [b[:150].replace("\n", " ") for b in bodies]


def _format_emails(msgs, summaries: list[str]) -> str:
    parts = [_SEP]
    for msg, summary in zip(msgs, summaries):
        parts.append(f"From:      | {_parse_from(msg.from_ or '')}")
        parts.append(f"Date Sent: | {msg.date_str or ''}")
        parts.append(f"Subject:   | {msg.subject or '(no subject)'}")
        parts.append(f"Body:      | {summary}")
        parts.append(_SEP)
    return "\n".join(parts)


@tool(
    "List recent inbox emails with summaries. Returns sender, subject, and a brief "
    "summary of each email body. Optionally specify an account name."
)
def list_inbox(account: str = "", max_items: int = 10) -> str:
    acc = _resolve(account)
    if acc is None:
        return _NO_ACCOUNTS
    try:
        from agents.email_client import imap_connection
        with imap_connection(acc) as mb:
            msgs = list(mb.fetch("ALL", limit=max_items, reverse=True, mark_seen=False))
        if not msgs:
            return f"[{acc['name']}] Inbox is empty."
        bodies = [_get_body(m) for m in msgs]
        summaries = _summarize_batch(bodies)
        return _format_emails(msgs, summaries)
    except RuntimeError as exc:
        return f"Email authentication failed: {exc}"
    except Exception as exc:
        return f"Could not connect to email server: {exc}"


@tool(
    "Search emails by query with summaries. Gmail supports full search syntax "
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
            msgs = list(mb.fetch(criteria, limit=max_items, reverse=True, mark_seen=False))
        if not msgs:
            return f"No emails found for '{query}'."
        bodies = [_get_body(m) for m in msgs]
        summaries = _summarize_batch(bodies)
        return _format_emails(msgs, summaries)
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
