import httpx
import pytest
from unittest.mock import patch, MagicMock


def _mock_response(text="", status=200):
    m = MagicMock()
    m.text = text
    m.status_code = status
    m.raise_for_status = MagicMock()
    return m


# --- search_web ---

def test_search_web_ddg_default():
    with patch("agents.web_search.search_ddg", return_value=["Result 1\nhttp://a.com", "Result 2\nhttp://b.com"]) as mock_ddg:
        from modules.web_tools import search_web
        result = search_web("python asyncio")
    mock_ddg.assert_called_once()
    assert "Result 1" in result
    assert "Result 2" in result


def test_search_web_no_results():
    with patch("agents.web_search.search_ddg", return_value=[]):
        from modules.web_tools import search_web
        result = search_web("xyzzy nothing found")
    assert "No results" in result


def test_search_web_google_when_configured():
    with patch("core.config.get_config") as mock_cfg, \
         patch("agents.web_search.search_google", return_value=["Google result"]) as mock_google:
        cfg = MagicMock()
        cfg.web_search_default = "google"
        cfg.google_search_api_key = "key123"
        cfg.google_search_cx = "cx456"
        cfg.web_search_max_results = 5
        mock_cfg.return_value = cfg
        from modules.web_tools import search_web
        result = search_web("test query")
    mock_google.assert_called_once_with("test query", "key123", "cx456", 5)
    assert "Google result" in result


def test_search_web_falls_back_to_ddg_when_google_keys_missing():
    with patch("core.config.get_config") as mock_cfg, \
         patch("agents.web_search.search_ddg", return_value=["DDG result"]) as mock_ddg, \
         patch("agents.web_search.search_google") as mock_google:
        cfg = MagicMock()
        cfg.web_search_default = "google"
        cfg.google_search_api_key = ""
        cfg.google_search_cx = ""
        cfg.web_search_max_results = 5
        mock_cfg.return_value = cfg
        from modules.web_tools import search_web
        result = search_web("test")
    mock_google.assert_not_called()
    mock_ddg.assert_called_once()
    assert "DDG result" in result


# --- scrape_url ---

def test_scrape_url_strips_html():
    html = "<html><body><h1>Hello</h1><p>World content here</p></body></html>"
    with patch("httpx.get", return_value=_mock_response(text=html)):
        from modules.web_tools import scrape_url
        result = scrape_url("http://example.com")
    assert "Hello" in result
    assert "World content here" in result
    assert "<h1>" not in result


def test_scrape_url_truncates_at_2000():
    long_html = "<p>" + "x" * 5000 + "</p>"
    with patch("httpx.get", return_value=_mock_response(text=long_html)):
        from modules.web_tools import scrape_url
        result = scrape_url("http://example.com")
    assert len(result) <= 2000


def test_scrape_url_http_error():
    with patch("httpx.get", side_effect=httpx.HTTPError("connection refused")):
        from modules.web_tools import scrape_url
        result = scrape_url("http://bad.host")
    assert "Fetch error" in result


# --- get_weather ---

def test_get_weather_success():
    with patch("httpx.get", return_value=_mock_response(text="London: ⛅ +18°C")):
        from modules.web_tools import get_weather
        result = get_weather("London")
    assert "London" in result
    assert "18" in result


def test_get_weather_here_uses_empty_loc():
    captured = {}
    def fake_get(url, **kwargs):
        captured["url"] = url
        return _mock_response(text="Auto: ☀ +22°C")
    with patch("httpx.get", side_effect=fake_get):
        from modules.web_tools import get_weather
        get_weather("here")
    assert captured["url"].startswith("https://wttr.in/?")


def test_get_weather_http_error():
    with patch("httpx.get", side_effect=httpx.HTTPError("timeout")):
        from modules.web_tools import get_weather
        result = get_weather("Paris")
    assert "failed" in result.lower()
