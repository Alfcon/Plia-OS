# Web Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the web agent stub with a real search node that routes to DuckDuckGo (default), Google Custom Search, or Playwright page-scrape based on the user's request.

**Architecture:** `agents/web_search.py` owns the three backends as pure functions; `agents/web.py` is the LangGraph node — it detects the provider from the user message, extracts the query via `call_llm`, dispatches to the correct backend, and returns results in `tool_results`. Playwright degrades gracefully if not installed.

**Tech Stack:** duckduckgo-search>=6.0, httpx (already in deps), playwright>=1.40 (optional), LangGraph (existing)

---

## File Structure

```
agents/
  web_search.py   NEW  — three search backends + async dispatcher
  web.py          MOD  — replace stub with real LangGraph node

pyproject.toml    MOD  — add duckduckgo-search to main deps; playwright as optional group

tests/agents/
  test_web_search.py  NEW  — unit tests for each backend (mocked I/O)
  test_web_node.py    NEW  — unit tests for web_node
```

---

### Task 1: agents/web_search.py — search backends

**Files:**
- Modify: `pyproject.toml`
- Create: `agents/web_search.py`
- Create: `tests/agents/test_web_search.py`

- [ ] **Step 1: Add duckduckgo-search to pyproject.toml**

Add `"duckduckgo-search>=6.0"` to the main `dependencies` list. Also add a new optional group for Playwright:

```toml
[project.optional-dependencies]
...existing groups...
playwright = ["playwright>=1.40"]
```

The full `dependencies` list in `[project]` should now include:
```toml
"duckduckgo-search>=6.0",
```

- [ ] **Step 2: Install duckduckgo-search**

```bash
/home/alfcon/Projects/Plia-OS/.venv/bin/pip install "duckduckgo-search>=6.0"
```

- [ ] **Step 3: Write the failing tests**

Create `tests/agents/test_web_search.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from agents.web_search import search_ddg, search_google, scrape_playwright, web_search


def test_search_ddg_returns_formatted_results():
    mock_result = [{"title": "Python", "body": "A language", "href": "https://python.org"}]
    with patch("agents.web_search.DDGS") as mock_cls:
        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = mock_result
        mock_cls.return_value.__enter__.return_value = mock_ddgs
        results = search_ddg("python language")
    assert len(results) == 1
    assert "Python" in results[0]
    assert "https://python.org" in results[0]


def test_search_ddg_error_returns_error_string():
    with patch("agents.web_search.DDGS") as mock_cls:
        mock_cls.return_value.__enter__.side_effect = RuntimeError("rate limited")
        results = search_ddg("query")
    assert len(results) == 1
    assert "error" in results[0].lower()


def test_search_google_returns_formatted_results():
    payload = {"items": [{"title": "PEP 8", "snippet": "Style guide", "link": "https://peps.python.org"}]}
    with patch("agents.web_search.httpx") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = payload
        mock_httpx.get.return_value = mock_resp
        results = search_google("python style", "key123", "cx456")
    assert len(results) == 1
    assert "PEP 8" in results[0]


def test_search_google_error_returns_error_string():
    with patch("agents.web_search.httpx") as mock_httpx:
        mock_httpx.get.side_effect = Exception("network error")
        results = search_google("query", "key", "cx")
    assert len(results) == 1
    assert "error" in results[0].lower()


@pytest.mark.asyncio
async def test_scrape_playwright_returns_truncated_text():
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.inner_text = AsyncMock(return_value="A" * 5000)
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    mock_p = AsyncMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw_cm = AsyncMock()
    mock_pw_cm.__aenter__ = AsyncMock(return_value=mock_p)
    mock_pw_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("agents.web_search.async_playwright", return_value=mock_pw_cm):
        result = await scrape_playwright("https://example.com", max_chars=100)
    assert len(result) == 100


@pytest.mark.asyncio
async def test_scrape_playwright_graceful_when_not_installed():
    with patch("agents.web_search.async_playwright", None):
        result = await scrape_playwright("https://example.com")
    assert "not installed" in result.lower()


@pytest.mark.asyncio
async def test_web_search_dispatches_to_ddg_by_default():
    from core.config import PliaConfig
    config = PliaConfig()
    with patch("agents.web_search.search_ddg", return_value=["result1"]) as mock_ddg:
        results = await web_search("python", "ddg", config)
    mock_ddg.assert_called_once_with("python")
    assert results == ["result1"]


@pytest.mark.asyncio
async def test_web_search_dispatches_to_google_when_configured():
    from core.config import PliaConfig
    config = PliaConfig()
    config.google_search_api_key = "key"
    config.google_search_cx = "cx"
    with patch("agents.web_search.search_google", return_value=["g_result"]) as mock_g:
        results = await web_search("python", "google", config)
    mock_g.assert_called_once_with("python", "key", "cx")
    assert results == ["g_result"]


@pytest.mark.asyncio
async def test_web_search_falls_back_to_ddg_when_google_keys_missing():
    from core.config import PliaConfig
    config = PliaConfig()  # no google keys
    with patch("agents.web_search.search_ddg", return_value=["ddg_result"]) as mock_ddg:
        results = await web_search("python", "google", config)
    mock_ddg.assert_called_once()
    assert results == ["ddg_result"]


@pytest.mark.asyncio
async def test_web_search_dispatches_to_playwright_for_url():
    from core.config import PliaConfig
    config = PliaConfig()
    with patch("agents.web_search.scrape_playwright", new_callable=AsyncMock, return_value="page text") as mock_pw:
        results = await web_search("https://example.com/page", "playwright", config)
    mock_pw.assert_called_once_with("https://example.com/page")
    assert results == ["page text"]
```

- [ ] **Step 4: Run tests — confirm they fail**

```bash
cd /home/alfcon/Projects/Plia-OS
.venv/bin/python -m pytest tests/agents/test_web_search.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.web_search'`

- [ ] **Step 5: Create agents/web_search.py**

```python
from __future__ import annotations
import re
import logging
import httpx
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None  # type: ignore[assignment]


def search_ddg(query: str, max_results: int = 3) -> list[str]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [f"{r['title']}: {r['body']} ({r['href']})" for r in results]
    except Exception as exc:
        logger.warning("DDG search error: %s", exc)
        return [f"Search error: {exc}"]


def search_google(query: str, api_key: str, cx: str, max_results: int = 3) -> list[str]:
    try:
        resp = httpx.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"q": query, "key": api_key, "cx": cx, "num": max_results},
            timeout=10.0,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [f"{i['title']}: {i['snippet']} ({i['link']})" for i in items[:max_results]]
    except Exception as exc:
        logger.warning("Google search error: %s", exc)
        return [f"Google search error: {exc}"]


async def scrape_playwright(url: str, max_chars: int = 2000) -> str:
    if async_playwright is None:
        return "Playwright not installed. Run: pip install playwright && playwright install chromium"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = await page.inner_text("body")
            await browser.close()
        return text[:max_chars]
    except Exception as exc:
        logger.warning("Playwright scrape error: %s", exc)
        return f"Scrape error: {exc}"


async def web_search(query_or_url: str, provider: str, config) -> list[str]:
    url_match = _URL_RE.search(query_or_url)
    if url_match or provider == "playwright":
        target = url_match.group(0) if url_match else query_or_url
        text = await scrape_playwright(target)
        return [text]
    if provider == "google" and config.google_search_api_key and config.google_search_cx:
        return search_google(query_or_url, config.google_search_api_key, config.google_search_cx)
    return search_ddg(query_or_url)
```

- [ ] **Step 6: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_web_search.py -v
```

Expected: 9 passed

- [ ] **Step 7: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥114)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml agents/web_search.py tests/agents/test_web_search.py
git commit -m "feat: add web search backends (DDG, Google, Playwright)"
```

---

### Task 2: agents/web.py — real LangGraph node

**Files:**
- Modify: `agents/web.py`
- Create: `tests/agents/test_web_node.py`

- [ ] **Step 1: Write failing tests**

Create `tests/agents/test_web_node.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from agents.web import web_node


def _state(user_text, search_provider="ddg"):
    return {
        "messages": [{"role": "user", "content": user_text}],
        "tool_results": [],
        "memory_context": "",
        "active_agent": None,
        "search_provider": search_provider,
        "hop_count": 1,
    }


@pytest.mark.asyncio
async def test_web_node_returns_tool_results():
    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "python language"}
        mock_ws.return_value = ["Python: A language (https://python.org)"]
        update = await web_node(_state("search for python language"))
    assert update["active_agent"] == "web"
    assert any("Python" in r for r in update["tool_results"])


@pytest.mark.asyncio
async def test_web_node_detects_google_keyword():
    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "best python tutorials"}
        mock_ws.return_value = ["result"]
        await web_node(_state("search with google for best python tutorials"))
    args, _ = mock_ws.call_args
    assert args[1] == "google"


@pytest.mark.asyncio
async def test_web_node_detects_url_for_playwright():
    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "https://example.com"}
        mock_ws.return_value = ["page content"]
        await web_node(_state("open https://example.com and summarise it"))
    args, _ = mock_ws.call_args
    assert args[1] == "playwright"


@pytest.mark.asyncio
async def test_web_node_uses_state_provider_as_default():
    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.return_value = {"content": "latest news"}
        mock_ws.return_value = ["news result"]
        await web_node(_state("what is the latest news", search_provider="ddg"))
    args, _ = mock_ws.call_args
    assert args[1] == "ddg"


@pytest.mark.asyncio
async def test_web_node_llm_error_uses_raw_message_as_query():
    with patch("agents.web.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("agents.web.web_search", new_callable=AsyncMock) as mock_ws:
        mock_llm.side_effect = RuntimeError("llm down")
        mock_ws.return_value = ["result"]
        update = await web_node(_state("find something interesting"))
    query = mock_ws.call_args[0][0]
    assert "find something interesting" in query
    assert update["active_agent"] == "web"
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
.venv/bin/python -m pytest tests/agents/test_web_node.py -v 2>&1 | head -20
```

Expected: FAIL — `web_node` still returns the stub "[web] not yet implemented"

- [ ] **Step 3: Replace agents/web.py**

```python
from __future__ import annotations
import logging
import re
from typing import TYPE_CHECKING

from agents.llm import call_llm
from agents.web_search import web_search
from core.config import get_config

if TYPE_CHECKING:
    from core.supervisor import AgentState

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")

_EXTRACT_SYSTEM = (
    "Extract the search query or URL from the user's message. "
    "Output only the query string or URL, nothing else."
)

_GOOGLE_KEYWORDS = ("google", "search with google", "use google", "google search")
_PLAYWRIGHT_KEYWORDS = ("open ", "read this page", "visit ", "browse to", "go to http")


def _detect_provider(text: str, default: str) -> str:
    lower = text.lower()
    if _URL_RE.search(text):
        return "playwright"
    if any(kw in lower for kw in _GOOGLE_KEYWORDS):
        return "google"
    if any(kw in lower for kw in _PLAYWRIGHT_KEYWORDS):
        return "playwright"
    return default


async def web_node(state: "AgentState") -> dict:
    last_user = next(
        (m["content"] for m in reversed(state["messages"]) if m["role"] == "user"),
        "",
    )
    config = get_config()
    provider = _detect_provider(last_user, state.get("search_provider", "ddg"))

    try:
        msg = await call_llm([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": last_user},
        ])
        query = (msg.get("content") or last_user).strip() or last_user
    except Exception:
        query = last_user

    results = await web_search(query, provider, config)
    combined = "\n".join(results)
    logger.info("Web search (%s): %d results", provider, len(results))
    return {
        "tool_results": state["tool_results"] + [f"[web/{provider}]\n{combined}"],
        "active_agent": "web",
    }
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
.venv/bin/python -m pytest tests/agents/test_web_node.py -v
```

Expected: 5 passed

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all pass (≥123)

- [ ] **Step 6: Commit**

```bash
git add agents/web.py tests/agents/test_web_node.py
git commit -m "feat: implement web agent node with DDG/Google/Playwright routing"
```
