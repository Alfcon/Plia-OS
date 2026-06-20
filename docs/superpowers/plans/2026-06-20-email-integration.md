# Email Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IMAP read/search and SMTP send to Plia-OS via natural language, with Gmail OAuth2 and generic IMAP/SMTP (app password) support, plus an optional unread-count section in the morning briefing.

**Architecture:** Thin `@tool` module backed by connection helpers. Fresh IMAP/SMTP connection per tool call — no persistent connection. Gmail uses OAuth2 XOAUTH2 via `google-auth-oauthlib` (identical pattern to `agents/google_calendar.py`); generic providers use stdlib `imaplib`/`smtplib` with LOGIN. Supervisor keyword routing for read commands; send requires LLM arg extraction.

**Tech Stack:** stdlib `imaplib`, `smtplib`, `email` (Python built-ins); `google-auth-oauthlib`, `google-auth` (already installed for gcal); `fastapi`, `httpx` (already in project).

## Global Constraints

- No live network calls in tests — mock `imaplib.IMAP4_SSL`, `smtplib.SMTP`, `google.oauth2.credentials.Credentials`
- `email_password` must never appear in logs
- Follow existing `@tool` pattern: synchronous functions, plain-text return values
- Gmail OAuth2 scope: `https://mail.google.com/` (XOAUTH2 requires full-mail scope)
- Generic IMAP: port 993 SSL; SMTP: port 587 STARTTLS
- `email_provider = ""` means disabled; tools must return `"Email not configured. Set email_provider in Settings → Email."`
- Briefing section silently returns `""` if provider not configured or connection fails
- `send_email` is NOT in `_DIRECT_TOOL_KEYWORDS` — requires LLM to extract `to`, `subject`, `body`
- Gmail token cached at `{memory_dir}/gmail_token.json` (not user-configurable, follows gcal pattern)

---

## File Map

| Path | Action | Purpose |
|------|--------|---------|
| `agents/email_client.py` | **Create** | IMAP/SMTP context-manager helpers + Gmail OAuth2 |
| `modules/email_tools.py` | **Create** | `list_inbox`, `search_email`, `send_email` tools |
| `core/config.py` | **Modify** | Add 9 email config fields |
| `modules/briefing_tools.py` | **Modify** | Add `_email_section()`, wire into `morning_briefing()` |
| `core/supervisor.py` | **Modify** | Add email read keywords to `_DIRECT_TOOL_KEYWORDS` |
| `dashboard/server.py` | **Modify** | Add `/api/email/auth`, `/api/email/callback`, `/api/email/status` |
| `dashboard/static/index.html` | **Modify** | Email nav button + config panel + JS functions |
| `tests/test_email_client.py` | **Create** | Unit tests for connection helpers and OAuth2 flow |
| `tests/test_email_tools.py` | **Create** | Unit tests for all three tools, both auth paths |
| `tests/test_email_briefing.py` | **Create** | Tests for `_email_section()` and briefing integration |

---

### Task 1: Config Fields

Add 9 email config fields to `PliaConfig`.

**Files:**
- Modify: `core/config.py`
- Test: `tests/test_email_config.py`

**Interfaces:**
- Produces: `PliaConfig.email_provider`, `.email_imap_host`, `.email_imap_port`, `.email_smtp_host`, `.email_smtp_port`, `.email_username`, `.email_password`, `.email_gmail_credentials_file`, `.email_briefing_enabled`

- [ ] **Step 1: Write the failing test**

Create `tests/test_email_config.py`:

```python
"""Tests for email config fields."""
from __future__ import annotations


def test_email_config_defaults():
    from core.config import PliaConfig
    cfg = PliaConfig()
    assert cfg.email_provider == ""
    assert cfg.email_imap_host == ""
    assert cfg.email_imap_port == 993
    assert cfg.email_smtp_host == ""
    assert cfg.email_smtp_port == 587
    assert cfg.email_username == ""
    assert cfg.email_password == ""
    assert cfg.email_gmail_credentials_file == ""
    assert cfg.email_briefing_enabled is False


def test_email_config_persists():
    # isolate_config_file (autouse) already redirects _CONFIG_FILE to tmp_path
    from core.config import update_config, get_config
    update_config(
        email_provider="imap",
        email_imap_host="mail.example.com",
        email_imap_port=993,
        email_username="user@example.com",
        email_briefing_enabled=True,
    )
    cfg = get_config()
    assert cfg.email_provider == "imap"
    assert cfg.email_imap_host == "mail.example.com"
    assert cfg.email_briefing_enabled is True
```

- [ ] **Step 2: Run to verify failure**

```bash
source .venv/bin/activate
pytest tests/test_email_config.py -v
```

Expected: `AttributeError: 'PliaConfig' object has no attribute 'email_provider'`

- [ ] **Step 3: Add fields to `core/config.py`**

In `core/config.py`, after the `# Briefing` block (after `briefing_cron_time`), add:

```python
    # Email
    email_provider: str = ""                 # "gmail" | "imap" | "" (disabled)
    email_imap_host: str = ""
    email_imap_port: int = 993
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: str = ""                 # app password — never logged
    email_gmail_credentials_file: str = ""  # path to OAuth2 client_secret.json
    email_briefing_enabled: bool = False
```

- [ ] **Step 4: Run to verify passing**

```bash
pytest tests/test_email_config.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_email_config.py
git commit -m "feat(email): add email config fields to PliaConfig"
```

---

### Task 2: Email Client Helpers

Create `agents/email_client.py` with IMAP/SMTP context managers and Gmail OAuth2.

**Files:**
- Create: `agents/email_client.py`
- Test: `tests/test_email_client.py`

**Interfaces:**
- Consumes: `core/config.py` → `get_config()`, `PliaConfig.email_provider`, `.email_username`, `.email_password`, `.email_imap_host`, `.email_imap_port`, `.email_smtp_host`, `.email_smtp_port`, `.email_gmail_credentials_file`, `.memory_dir`
- Produces:
  - `imap_connection() -> contextlib.AbstractContextManager[imaplib.IMAP4_SSL]`
  - `smtp_connection() -> contextlib.AbstractContextManager[smtplib.SMTP]`
  - `get_gmail_credentials() -> google.oauth2.credentials.Credentials | None`
  - `build_auth_url(credentials_file: str, redirect_uri: str) -> str`
  - `exchange_code(credentials_file: str, redirect_uri: str, code: str) -> None`
  - `is_connected() -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email_client.py`:

```python
"""Tests for agents/email_client.py connection helpers."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch, call


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
        mock_conn.ehlo.assert_called_once()
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
    with patch("agents.email_client.get_gmail_credentials", return_value=mock_creds), \
         patch("smtplib.SMTP", return_value=mock_conn):
        from agents.email_client import smtp_connection
        with smtp_connection() as conn:
            assert conn is mock_conn
        mock_conn.docmd.assert_called_once()
        assert mock_conn.docmd.call_args[0][0] == "AUTH"
        mock_conn.login.assert_not_called()


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
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_email_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'agents.email_client'`

- [ ] **Step 3: Create `agents/email_client.py`**

```python
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
    _token_path().write_text(flow.credentials.to_json())
    logger.info("Gmail token saved to %s", _token_path())


def is_connected() -> bool:
    return get_gmail_credentials() is not None


@contextlib.contextmanager
def imap_connection() -> Iterator[imaplib.IMAP4_SSL]:
    """Yield an authenticated IMAP4_SSL connection. Always calls logout on exit."""
    from core.config import get_config
    cfg = get_config()
    if cfg.email_provider == "gmail":
        creds = get_gmail_credentials()
        if creds is None:
            raise RuntimeError("Gmail not authorized — connect via Settings → Email")
        auth_string = f"user={cfg.email_username}\x01auth=Bearer {creds.token}\x01\x01"
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.authenticate("XOAUTH2", lambda x: auth_string)
    else:
        conn = imaplib.IMAP4_SSL(cfg.email_imap_host, cfg.email_imap_port)
        conn.login(cfg.email_username, cfg.email_password)
    try:
        yield conn
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@contextlib.contextmanager
def smtp_connection() -> Iterator[smtplib.SMTP]:
    """Yield an authenticated SMTP connection. Always calls quit on exit."""
    from core.config import get_config
    cfg = get_config()
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
        conn.docmd("AUTH", f"XOAUTH2 {auth_bytes.decode()}")
    else:
        conn = smtplib.SMTP(cfg.email_smtp_host, cfg.email_smtp_port)
        conn.ehlo()
        conn.starttls()
        conn.login(cfg.email_username, cfg.email_password)
    try:
        yield conn
    finally:
        try:
            conn.quit()
        except Exception:
            pass
```

- [ ] **Step 4: Run to verify passing**

```bash
pytest tests/test_email_client.py -v
```

Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add agents/email_client.py tests/test_email_client.py
git commit -m "feat(email): add IMAP/SMTP connection helpers with Gmail OAuth2"
```

---

### Task 3: Email Tools and Supervisor Routing

Create `modules/email_tools.py` with `list_inbox`, `search_email`, `send_email`, and add keyword routing to supervisor.

**Files:**
- Create: `modules/email_tools.py`
- Modify: `core/supervisor.py`
- Test: `tests/test_email_tools.py`

**Interfaces:**
- Consumes: `agents/email_client.imap_connection`, `agents/email_client.smtp_connection`; `core/config.get_config()`; `core/registry.tool`
- Produces:
  - `list_inbox(max_items: int = 10) -> str` — registered tool
  - `search_email(query: str, max_items: int = 10) -> str` — registered tool
  - `send_email(to: str, subject: str, body: str) -> str` — registered tool

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email_tools.py`:

```python
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
    mock_conn.sendmail.assert_called_once_with(
        "user@example.com", ["bob@example.com"], mock_conn.sendmail.call_args[0][2]
    )
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


def test_supervisor_keywords_route_to_search_email():
    from core.supervisor import _direct_tool
    assert _direct_tool("search email for invoices") == "search_email"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_email_tools.py -v
```

Expected: failures with `ModuleNotFoundError` for `modules.email_tools` and `AssertionError` for supervisor routing.

- [ ] **Step 3: Create `modules/email_tools.py`**

```python
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
```

- [ ] **Step 4: Add email keywords to `core/supervisor.py`**

In `core/supervisor.py`, extend `_DIRECT_TOOL_KEYWORDS` (currently ends at line 125):

```python
_DIRECT_TOOL_KEYWORDS: dict[str, str] = {
    "morning briefing": "morning_briefing",
    "daily briefing": "morning_briefing",
    "today's briefing": "morning_briefing",
    "give me a briefing": "morning_briefing",
    "good morning": "morning_briefing",
    "what's today": "morning_briefing",
    "what's on today": "morning_briefing",
    "what do i have today": "morning_briefing",
    # Email
    "check my email": "list_inbox",
    "any new emails": "list_inbox",
    "any emails": "list_inbox",
    "read my inbox": "list_inbox",
    "show my inbox": "list_inbox",
    "new emails": "list_inbox",
    "search email": "search_email",
    "search my email": "search_email",
}
```

- [ ] **Step 5: Run to verify passing**

```bash
pytest tests/test_email_tools.py -v
```

Expected: 14 passed

- [ ] **Step 6: Commit**

```bash
git add modules/email_tools.py core/supervisor.py tests/test_email_tools.py
git commit -m "feat(email): add list_inbox, search_email, send_email tools and keyword routing"
```

---

### Task 4: Briefing Integration

Add `_email_section()` to `modules/briefing_tools.py` and wire it into `morning_briefing()`.

**Files:**
- Modify: `modules/briefing_tools.py`
- Test: `tests/test_email_briefing.py`

**Interfaces:**
- Consumes: `agents/email_client.imap_connection`; `core/config.get_config()`; `PliaConfig.email_briefing_enabled`, `.email_provider`
- Produces: `_email_section() -> str` — internal helper used by `morning_briefing()`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_email_briefing.py`:

```python
"""Tests for email section in morning briefing."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch


def _patch_imap(mock_conn):
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_conn)
    cm.__exit__ = MagicMock(return_value=False)
    return patch("agents.email_client.imap_connection", return_value=cm)


def test_email_section_disabled_returns_empty():
    """_email_section returns '' when email_briefing_enabled is False."""
    from core.config import update_config
    update_config(email_briefing_enabled=False)
    from modules.briefing_tools import _email_section
    assert _email_section() == ""


def test_email_section_no_provider_returns_empty():
    """_email_section returns '' when email_provider is empty."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="")
    from modules.briefing_tools import _email_section
    assert _email_section() == ""


def test_email_section_unread_count():
    """_email_section returns 'Email: N unread.' when UNSEEN search returns messages."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="imap")

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2 3"])

    with _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()

    assert result == "Email: 3 unread."
    mock_conn.search.assert_called_with(None, "UNSEEN")


def test_email_section_zero_unread_returns_empty():
    """_email_section returns '' when there are no unread messages."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="imap")

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b""])

    with _patch_imap(mock_conn):
        from modules.briefing_tools import _email_section
        result = _email_section()

    assert result == ""


def test_email_section_connection_fails_returns_empty():
    """_email_section returns '' and does not crash when IMAP fails."""
    from core.config import update_config
    update_config(email_briefing_enabled=True, email_provider="imap")

    with patch("agents.email_client.imap_connection", side_effect=OSError("timeout")):
        from modules.briefing_tools import _email_section
        result = _email_section()

    assert result == ""


def test_morning_briefing_includes_email_section():
    """morning_briefing() output includes email line when unread > 0."""
    from core.config import update_config
    update_config(
        email_briefing_enabled=True,
        email_provider="imap",
        weather_location="",
    )

    mock_conn = MagicMock()
    mock_conn.search.return_value = ("OK", [b"1 2"])

    # Patch all external calls so briefing can run without network
    with _patch_imap(mock_conn), \
         patch("modules.briefing_tools._weather_section", return_value="Weather: clear."), \
         patch("modules.briefing_tools._reminders_section", return_value=""), \
         patch("modules.briefing_tools._calendar_section", return_value=""), \
         patch("modules.briefing_tools._news_section", return_value=""):
        from modules.briefing_tools import morning_briefing
        result = morning_briefing()

    assert "Email: 2 unread." in result
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_email_briefing.py -v
```

Expected: `ImportError` or `AttributeError` — `_email_section` not defined yet.

- [ ] **Step 3: Add `_email_section` to `modules/briefing_tools.py`**

Add this function to `modules/briefing_tools.py`, after `_calendar_section` and before `morning_briefing`:

```python
def _email_section() -> str:
    cfg = get_config()
    if not cfg.email_briefing_enabled or not cfg.email_provider:
        return ""
    try:
        from agents.email_client import imap_connection
        with imap_connection() as conn:
            conn.select("INBOX", readonly=True)
            _, data = conn.search(None, "UNSEEN")
            count = len(data[0].split()) if data[0] else 0
        return f"Email: {count} unread." if count > 0 else ""
    except Exception:
        logger.exception("Email briefing section failed")
        return ""
```

- [ ] **Step 4: Wire `_email_section` into `morning_briefing()`**

In `modules/briefing_tools.py`, update the helper tuple in `morning_briefing()`:

```python
    for helper in (_weather_section, _reminders_section, _calendar_section, _email_section, _news_section):
```

- [ ] **Step 5: Run to verify passing**

```bash
pytest tests/test_email_briefing.py -v
```

Expected: 6 passed

- [ ] **Step 6: Run full suite to check for regressions**

```bash
pytest --tb=short -q
```

Expected: all tests passing (560+ tests)

- [ ] **Step 7: Commit**

```bash
git add modules/briefing_tools.py tests/test_email_briefing.py
git commit -m "feat(email): add email unread count section to morning briefing"
```

---

### Task 5: Dashboard — API Endpoints and Config Panel

Add three API endpoints to `dashboard/server.py` and an Email settings panel to `dashboard/static/index.html`.

**Files:**
- Modify: `dashboard/server.py`
- Modify: `dashboard/static/index.html`

**Interfaces:**
- Consumes: `agents/email_client.build_auth_url`, `.exchange_code`, `.is_connected`; `core/config.get_config()`
- Produces:
  - `POST /api/email/auth` → `{"auth_url": str}`
  - `GET  /api/email/callback?code=...` → HTML success/error page
  - `GET  /api/email/status` → `{"connected": bool}`

- [ ] **Step 1: Add API endpoints to `dashboard/server.py`**

Add after the existing `/api/calendar/google/callback` endpoint (around line 511):

```python
# --- Email ---

@router.post("/api/email/auth")
async def email_auth(request: Request):
    from agents.email_client import build_auth_url
    config = get_config()
    if not config.email_gmail_credentials_file:
        raise HTTPException(status_code=422, detail="email_gmail_credentials_file not configured")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/email/callback"
    auth_url = await asyncio.to_thread(build_auth_url, config.email_gmail_credentials_file, redirect_uri)
    return {"auth_url": auth_url}


@router.get("/api/email/callback")
async def email_callback(request: Request, code: str = ""):
    from agents.email_client import exchange_code
    config = get_config()
    redirect_uri = str(request.base_url).rstrip("/") + "/api/email/callback"
    try:
        await asyncio.to_thread(exchange_code, config.email_gmail_credentials_file, redirect_uri, code)
    except (AttributeError, TypeError, ImportError, NameError):
        raise
    except Exception:
        logger.exception("Gmail OAuth callback failed")
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
            "<h2>Authorization failed.</h2><p>Close this tab and try again.</p></body></html>",
            status_code=400,
        )
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:2rem;background:#111;color:#eee'>"
        "<h2>Gmail connected.</h2><p>You can close this tab.</p></body></html>"
    )


@router.get("/api/email/status")
async def email_status():
    from core.config import get_config as _get_config
    cfg = _get_config()
    if cfg.email_provider == "gmail":
        from agents.email_client import is_connected
        connected = await asyncio.to_thread(is_connected)
        return {"connected": connected}
    return {"connected": cfg.email_provider == "imap" and bool(cfg.email_username)}
```

- [ ] **Step 2: Add the Email nav button to `dashboard/static/index.html`**

Find the Tokens nav button (line ~721):
```html
        <button class="m-nav-btn" data-section="tokens" onclick="showMenuSection('tokens');loadTokenUsage()">Tokens</button>
```

Add directly after it:
```html
        <button class="m-nav-btn" data-section="email" onclick="showMenuSection('email');loadEmailStatus()">Email</button>
```

- [ ] **Step 3: Add the Email settings panel to `dashboard/static/index.html`**

Find the end of the Tokens panel (after the closing `</div>` for `m-section-tokens`, around line 1210):
```html
        </div>
```

Add the Email panel immediately after that closing `</div>`:

```html
        <!-- Email -->
        <div id="m-section-email" class="m-pane" style="display:none">
          <div class="settings-section">
            <h3 style="margin:0 0 8px;font-size:13px;color:#aaa;text-transform:uppercase;letter-spacing:.05em">Email</h3>
            <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:4px;">Provider</label>
            <select id="cfg-email-provider"
              style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;margin-bottom:8px;"
              onchange="applyEmailProvider()">
              <option value="">— disabled —</option>
              <option value="gmail">Gmail (OAuth2)</option>
              <option value="imap">Generic IMAP/SMTP</option>
            </select>

            <!-- Generic IMAP fields -->
            <div id="email-imap-fields" style="display:none">
              <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">IMAP host</label>
              <input id="cfg-email-imap-host" type="text" placeholder="imap.example.com"
                style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;margin-bottom:4px;"
                onchange="applyEmailConfig()">
              <div style="display:flex;gap:6px;margin-bottom:4px;">
                <div style="flex:1">
                  <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">SMTP host</label>
                  <input id="cfg-email-smtp-host" type="text" placeholder="smtp.example.com"
                    style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
                    onchange="applyEmailConfig()">
                </div>
                <div style="width:70px">
                  <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">SMTP port</label>
                  <input id="cfg-email-smtp-port" type="number" value="587"
                    style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;"
                    onchange="applyEmailConfig()">
                </div>
              </div>
              <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">Username</label>
              <input id="cfg-email-username" type="text" placeholder="user@example.com"
                style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;margin-bottom:4px;"
                onchange="applyEmailConfig()">
              <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">App password</label>
              <input id="cfg-email-password" type="password" placeholder="app password"
                style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;margin-bottom:8px;"
                onchange="applyEmailConfig()">
            </div>

            <!-- Gmail OAuth2 fields -->
            <div id="email-gmail-fields" style="display:none">
              <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">Gmail address</label>
              <input id="cfg-email-gmail-username" type="text" placeholder="you@gmail.com"
                style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;margin-bottom:4px;"
                onchange="applyEmailConfig()">
              <label style="display:block;font-size:0.78rem;color:#999;margin-bottom:2px;">Path to client_secret.json</label>
              <input id="cfg-email-creds-file" type="text" placeholder="/home/user/client_secret.json"
                style="width:100%;padding:4px 6px;background:#1a1a1a;border:1px solid #333;color:#eee;border-radius:4px;font-size:0.78rem;box-sizing:border-box;margin-bottom:8px;"
                onchange="applyEmailConfig()">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
                <span style="font-size:0.72rem;color:#aaa;">Gmail OAuth2</span>
                <span id="email-status-badge" style="font-size:0.72rem;color:#888;">Checking...</span>
              </div>
              <div id="email-connect-section">
                <button onclick="connectGmail()"
                  style="background:#1565c0;border:none;color:#eee;padding:4px 10px;border-radius:3px;font-size:0.75rem;cursor:pointer;width:100%;">Connect Gmail</button>
                <div id="email-connect-status" style="font-size:0.72rem;margin-top:4px;color:#888;min-height:1em;"></div>
              </div>
            </div>

            <hr style="border-color:#222;margin:10px 0;">
            <label style="display:flex;align-items:center;gap:6px;font-size:0.78rem;color:#ccc;cursor:pointer;">
              <input type="checkbox" id="cfg-email-briefing" onchange="applyEmailConfig()">
              Show unread count in morning briefing
            </label>
          </div>
        </div>
```

- [ ] **Step 4: Populate config values on page load**

Find the `fetch('/api/config').then(cfg => {` block in `index.html`. After the existing briefing lines (around where `cfg-briefing-enabled` is set), add:

```javascript
      // Email
      const emailProvider = cfg.email_provider || '';
      document.getElementById('cfg-email-provider').value = emailProvider;
      document.getElementById('email-imap-fields').style.display = emailProvider === 'imap' ? '' : 'none';
      document.getElementById('email-gmail-fields').style.display = emailProvider === 'gmail' ? '' : 'none';
      document.getElementById('cfg-email-imap-host').value = cfg.email_imap_host || '';
      document.getElementById('cfg-email-smtp-host').value = cfg.email_smtp_host || '';
      document.getElementById('cfg-email-smtp-port').value = cfg.email_smtp_port || 587;
      document.getElementById('cfg-email-username').value = cfg.email_username || '';
      document.getElementById('cfg-email-gmail-username').value = cfg.email_username || '';
      document.getElementById('cfg-email-creds-file').value = cfg.email_gmail_credentials_file || '';
      document.getElementById('cfg-email-briefing').checked = !!cfg.email_briefing_enabled;
```

- [ ] **Step 5: Add JS functions before the closing `</script>` tag**

Find the closing `</script>` tag near the end of `index.html`. Add these functions just before it:

```javascript
  async function applyEmailProvider() {
    const provider = document.getElementById('cfg-email-provider').value;
    document.getElementById('email-imap-fields').style.display = provider === 'imap' ? '' : 'none';
    document.getElementById('email-gmail-fields').style.display = provider === 'gmail' ? '' : 'none';
    await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email_provider: provider}),
    });
    if (provider === 'gmail') loadEmailStatus();
  }

  async function applyEmailConfig() {
    const provider = document.getElementById('cfg-email-provider').value;
    const payload = {
      email_briefing_enabled: document.getElementById('cfg-email-briefing').checked,
    };
    if (provider === 'imap') {
      payload.email_imap_host = document.getElementById('cfg-email-imap-host').value.trim();
      payload.email_smtp_host = document.getElementById('cfg-email-smtp-host').value.trim();
      payload.email_smtp_port = parseInt(document.getElementById('cfg-email-smtp-port').value) || 587;
      payload.email_username = document.getElementById('cfg-email-username').value.trim();
      payload.email_password = document.getElementById('cfg-email-password').value;
    } else if (provider === 'gmail') {
      payload.email_username = document.getElementById('cfg-email-gmail-username').value.trim();
      payload.email_gmail_credentials_file = document.getElementById('cfg-email-creds-file').value.trim();
    }
    await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
  }

  let _emailPollId = null;

  async function loadEmailStatus() {
    try {
      const r = await fetch('/api/email/status');
      const data = await r.json();
      const badge = document.getElementById('email-status-badge');
      const section = document.getElementById('email-connect-section');
      if (!badge) return;
      if (data.connected) {
        clearInterval(_emailPollId);
        badge.textContent = '● Connected';
        badge.style.color = '#a5d6a7';
        if (section) section.style.display = 'none';
      } else {
        badge.textContent = '○ Not connected';
        badge.style.color = '#ef9a9a';
        if (section) section.style.display = '';
      }
    } catch (e) {}
  }

  async function connectGmail() {
    const credsFile = document.getElementById('cfg-email-creds-file').value.trim();
    const username = document.getElementById('cfg-email-gmail-username').value.trim();
    const statusEl = document.getElementById('email-connect-status');
    if (!credsFile) { statusEl.textContent = 'Enter path to credentials.json first.'; return; }
    if (!username) { statusEl.textContent = 'Enter your Gmail address first.'; return; }
    statusEl.textContent = 'Saving config...';
    await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email_gmail_credentials_file: credsFile, email_username: username}),
    });
    statusEl.textContent = 'Opening Google authorization...';
    const r = await fetch('/api/email/auth', {method: 'POST'});
    if (!r.ok) {
      const e = await r.json();
      statusEl.textContent = e.detail || 'Error';
      statusEl.style.color = '#ef9a9a';
      return;
    }
    const data = await r.json();
    window.open(data.auth_url, '_blank', 'width=600,height=700');
    statusEl.textContent = 'Waiting for authorization...';
    clearInterval(_emailPollId);
    let _pollCount = 0;
    _emailPollId = setInterval(async () => {
      _pollCount++;
      if (_pollCount > 150) {
        clearInterval(_emailPollId);
        statusEl.textContent = 'Timed out. Try connecting again.';
        statusEl.style.color = '#ef9a9a';
        return;
      }
      try {
        const s = await fetch('/api/email/status');
        const sd = await s.json();
        if (sd.connected) {
          clearInterval(_emailPollId);
          statusEl.textContent = 'Connected!';
          statusEl.style.color = '#a5d6a7';
          loadEmailStatus();
        }
      } catch (e) {}
    }, 2000);
  }
```

- [ ] **Step 6: Run the full test suite**

```bash
pytest --tb=short -q
```

Expected: all tests passing. The dashboard endpoints are not covered by automated tests (HTML-heavy UI), but the API routes will be exercised by the existing `create_app()` test infrastructure on the next test run.

- [ ] **Step 7: Commit**

```bash
git add dashboard/server.py dashboard/static/index.html
git commit -m "feat(email): add dashboard email panel and API endpoints"
```
