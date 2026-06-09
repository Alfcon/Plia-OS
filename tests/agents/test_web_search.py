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
