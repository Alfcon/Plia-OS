# Email Integration Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IMAP read/search and SMTP send to Plia-OS via natural language, with Gmail OAuth2 and generic IMAP/SMTP (app password) support, and an optional unread-count section in the morning briefing.

**Architecture:** Thin `@tool` module (`modules/email_tools.py`) backed by connection helpers in `agents/email_client.py`. Fresh IMAP/SMTP connection per tool call — no persistent connection. Gmail uses OAuth2 XOAUTH2 via `google-auth-oauthlib` (identical pattern to `agents/google_calendar.py`); generic providers use stdlib `imaplib`/`smtplib` with app-password LOGIN. Spam display reads the server's existing `\Junk` / `\Spam` flag; no local inference.

**Tech Stack:** stdlib `imaplib`, `smtplib`, `email` (Python built-ins); `google-auth-oauthlib`, `google-auth` (already required for gcal); no new PyPI deps for the generic IMAP path.

## Global Constraints

- No live network calls in tests — mock `imaplib.IMAP4_SSL`, `smtplib.SMTP`, and `google.oauth2.credentials.Credentials`
- `email_password` must never appear in logs (use `***` if referenced)
- Follow existing `@tool` pattern: synchronous functions, plain-text return values
- Gmail OAuth2 scopes: `https://mail.google.com/` (IMAP XOAUTH2 requires full-mail scope)
- Generic IMAP: port 993 SSL default; SMTP: port 587 STARTTLS default
- `email_provider = ""` means disabled; tools must return a "not configured" message
- Briefing section silently returns `""` if provider not configured or connection fails
- `send_email` is NOT in `_DIRECT_TOOL_KEYWORDS` — requires LLM to extract `to`, `subject`, `body` args

---

## Files

| Path | Action | Purpose |
|------|--------|---------|
| `agents/email_client.py` | Create | IMAP/SMTP context-manager helpers; Gmail OAuth2 token management |
| `modules/email_tools.py` | Create | `list_inbox`, `search_email`, `send_email` tools |
| `core/config.py` | Modify | Add 8 email config fields |
| `briefing_tools.py` | Modify | Add `_email_section()`, wire into `morning_briefing()` |
| `core/supervisor.py` | Modify | Add email read keywords to `_DIRECT_TOOL_KEYWORDS` |
| `dashboard/server.py` | Modify | Add `/api/email/auth-url` and `/api/email/auth-callback` endpoints |
| `dashboard/static/index.html` | Modify | Email config panel (provider, credentials, test button, OAuth2 flow) |
| `tests/test_email_tools.py` | Create | Unit tests for all three tools, both auth paths |
| `tests/test_email_briefing.py` | Create | Briefing section test |

---

## Config Fields

Added to `PliaConfig` in `core/config.py`:

```python
# Email
email_provider: str = ""                  # "gmail" | "imap" | "" (disabled)
email_imap_host: str = ""
email_imap_port: int = 993
email_smtp_host: str = ""
email_smtp_port: int = 587
email_username: str = ""
email_password: str = ""                  # app password — never logged
email_gmail_credentials_file: str = ""   # path to OAuth2 client_secret.json
email_briefing_enabled: bool = False     # include unread count in morning_briefing
```

No `_LITERAL_CONSTRAINTS` entry needed — `email_provider` validated in tool layer, not config layer (allows `""` as valid disabled state).

---

## `agents/email_client.py`

Two public context managers and one OAuth2 helper:

```python
@contextlib.contextmanager
def imap_connection() -> Iterator[imaplib.IMAP4_SSL]:
    """Yield an authenticated IMAP4_SSL connection. Closes on exit."""
    cfg = get_config()
    if cfg.email_provider == "gmail":
        creds = _get_gmail_credentials()
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
    """Yield an authenticated SMTP connection. Closes on exit."""
    cfg = get_config()
    if cfg.email_provider == "gmail":
        creds = _get_gmail_credentials()
        conn = smtplib.SMTP("smtp.gmail.com", 587)
        conn.ehlo()
        conn.starttls()
        conn.docmd("AUTH", f"XOAUTH2 {base64.b64encode(f'user={cfg.email_username}\x01auth=Bearer {creds.token}\x01\x01'.encode()).decode()}")
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


def _get_gmail_credentials():
    """Return valid OAuth2 Credentials or raise RuntimeError."""
    # Identical pattern to agents/google_calendar.py::get_credentials()
    _SCOPES = ["https://mail.google.com/"]
    _TOKEN_FILENAME = "gmail_token.json"
    ...
```

`build_auth_url(credentials_file, redirect_uri)` and `exchange_code(credentials_file, redirect_uri, code)` mirror `agents/google_calendar.py` exactly, using `_SCOPES = ["https://mail.google.com/"]`.

---

## Tools (`modules/email_tools.py`)

### `list_inbox`

```python
@tool("List recent inbox emails. Returns sender, subject, date, and whether each is spam.")
def list_inbox(max_items: int = 10) -> str:
```

1. Guard: `if not cfg.email_provider: return "Email not configured."`
2. Open `imap_connection()`, `SELECT INBOX`
3. `SEARCH ALL` sorted by date descending, take last `max_items` UIDs
4. `FETCH` envelope: `FROM`, `SUBJECT`, `DATE`, `FLAGS`
5. Spam flag: check `\Junk` or `\Spam` in FLAGS
6. Return plain-text table: `[1] From: X | Subject: Y | Date: Z | SPAM` per line

### `search_email`

```python
@tool("Search emails. Gmail supports full search syntax (from:, subject:, etc.). Generic IMAP uses keyword search.")
def search_email(query: str, max_items: int = 10) -> str:
```

- Gmail path: `SEARCH X-GM-RAW "<query>"` (Gmail IMAP extension)
- Generic path: `SEARCH TEXT "<query>"` (IMAP RFC 3501 TEXT search)
- Same fetch/format as `list_inbox`

### `send_email`

```python
@tool("Send an email. Provide recipient address, subject line, and message body.")
def send_email(to: str, subject: str, body: str) -> str:
```

1. Guard: `if not cfg.email_provider: return "Email not configured."`
2. Build `MIMEText` (plain), set `From` to `cfg.email_username`, `To`, `Subject`
3. Open `smtp_connection()`, `sendmail(from, [to], msg.as_string())`
4. Return `"Email sent to <to>."`

---

## Briefing Integration

```python
def _email_section() -> str:
    if not get_config().email_briefing_enabled:
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

Inserted in `morning_briefing()` after `_calendar_section`, before `_news_section`.

---

## Supervisor Keyword Routing

In `core/supervisor.py`, `_DIRECT_TOOL_KEYWORDS`:

```python
"check my email": "list_inbox",
"any new emails": "list_inbox",
"any emails": "list_inbox",
"read my inbox": "list_inbox",
"show my inbox": "list_inbox",
"new emails": "list_inbox",
"search email": "search_email",
"search my email": "search_email",
```

`send_email` excluded — requires LLM to extract `to`, `subject`, `body` from user's message.

---

## Dashboard

### Config panel (new "Email" section in `index.html`)

Fields: Provider dropdown (`— disabled —` / `Gmail (OAuth2)` / `Generic IMAP`), IMAP host/port, SMTP host/port, username, password (masked), Gmail credentials file path, "Connect Gmail" OAuth2 button (shows auth URL in new tab), briefing-enabled checkbox.

Shows/hides IMAP fields vs Gmail fields based on provider selection.

### API endpoints (`dashboard/server.py`)

```
GET  /api/email/auth-url       → {"url": "<oauth2_auth_url>"}
POST /api/email/auth-callback  body: {"code": "..."}  → {"status": "ok"}
```

Same pattern as calendar's `/api/calendar/auth-url` and `/api/calendar/auth-callback`.

---

## Testing

### `tests/test_email_tools.py`

- `test_list_inbox_not_configured` — `email_provider=""` → `"Email not configured."`
- `test_list_inbox_imap` — mock `IMAP4_SSL`, verify LOGIN called, returns formatted lines
- `test_list_inbox_spam_flag` — mock message with `\Junk` flag → output contains "SPAM"
- `test_search_email_imap` — mock SEARCH TEXT, verify query passed
- `test_search_email_gmail_syntax` — `email_provider="gmail"` → uses `X-GM-RAW`
- `test_send_email_imap` — mock SMTP, verify `sendmail` called with correct args
- `test_send_email_gmail` — mock SMTP + OAuth2 credentials, verify XOAUTH2 auth
- `test_send_email_not_configured` — returns not-configured string

### `tests/test_email_briefing.py`

- `test_email_section_disabled` — `email_briefing_enabled=False` → `""`
- `test_email_section_unread` — mock `imap_connection` → 3 unread → `"Email: 3 unread."`
- `test_email_section_zero_unread` — 0 unread → `""`
- `test_email_section_connection_fails` — exception → `""` (no crash)
- `test_morning_briefing_includes_email` — integration: briefing output contains email line

---

## Error Handling

- Connection failure in any tool → return `"Could not connect to email server: <reason>."`
- Auth failure (bad password / expired OAuth2) → return `"Email authentication failed."`
- `send_email` SMTP error → return `"Failed to send email: <reason>."`
- All briefing errors → silent `""` (briefing must never crash)
- `email_password` scrubbed from all log output with `***`
