from unittest.mock import patch, MagicMock
import httpx


def _mock_resp(html: str, status: int = 200):
    mock = MagicMock()
    mock.status_code = status
    mock.text = html
    mock.raise_for_status = MagicMock()
    return mock


def test_scrape_url_strips_html_tags():
    html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    with patch("httpx.get", return_value=_mock_resp(html)):
        from modules.example_module import scrape_url
        result = scrape_url("https://example.com")
    assert "Hello" in result
    assert "World" in result
    assert "<" not in result
    assert ">" not in result


def test_scrape_url_truncates_at_2000():
    html = "<p>" + "x" * 5000 + "</p>"
    with patch("httpx.get", return_value=_mock_resp(html)):
        from modules.example_module import scrape_url
        result = scrape_url("https://example.com")
    assert len(result) <= 2000


def test_scrape_url_collapses_whitespace():
    html = "<p>Hello   \n\n  World</p>"
    with patch("httpx.get", return_value=_mock_resp(html)):
        from modules.example_module import scrape_url
        result = scrape_url("https://example.com")
    assert "  " not in result


def test_scrape_url_http_error():
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        from modules.example_module import scrape_url
        result = scrape_url("https://bad.host")
    assert "Fetch error" in result


def test_scrape_url_empty_body():
    with patch("httpx.get", return_value=_mock_resp("   ")):
        from modules.example_module import scrape_url
        result = scrape_url("https://example.com")
    assert result == "(no content)"
