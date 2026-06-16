from unittest.mock import patch, MagicMock


def _cfg(provider="ddg", max_results=5, google_key="", google_cx=""):
    mock = MagicMock()
    mock.web_search_default = provider
    mock.web_search_max_results = max_results
    mock.google_search_api_key = google_key
    mock.google_search_cx = google_cx
    return mock


def test_search_web_uses_ddg_by_default():
    fake_results = ["[1] Title\nSnippet\nhttps://example.com"]
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("agents.web_search.search_ddg", return_value=fake_results) as mock_ddg:
        from modules.example_module import search_web
        result = search_web("python tips")
    mock_ddg.assert_called_once_with("python tips", 5)
    assert "Title" in result
    assert "example.com" in result


def test_search_web_uses_google_when_configured():
    fake_results = ["[1] Google Result\nSnippet\nhttps://google.com"]
    cfg = _cfg(provider="google", google_key="key123", google_cx="cx456")
    with patch("core.config.get_config", return_value=cfg), \
         patch("agents.web_search.search_google", return_value=fake_results) as mock_google:
        from modules.example_module import search_web
        result = search_web("weather today")
    mock_google.assert_called_once_with("weather today", "key123", "cx456", 5)
    assert "Google Result" in result


def test_search_web_falls_back_to_ddg_when_google_not_configured():
    fake_results = ["[1] DDG Result\nSnippet\nhttps://ddg.com"]
    cfg = _cfg(provider="google", google_key="", google_cx="")
    with patch("core.config.get_config", return_value=cfg), \
         patch("agents.web_search.search_ddg", return_value=fake_results) as mock_ddg, \
         patch("agents.web_search.search_google") as mock_google:
        from modules.example_module import search_web
        result = search_web("news")
    mock_ddg.assert_called_once()
    mock_google.assert_not_called()
    assert "DDG Result" in result


def test_search_web_empty_results():
    with patch("core.config.get_config", return_value=_cfg()), \
         patch("agents.web_search.search_ddg", return_value=[]):
        from modules.example_module import search_web
        result = search_web("xyzzy")
    assert "No results" in result


def test_search_web_respects_max_results():
    with patch("core.config.get_config", return_value=_cfg(max_results=3)), \
         patch("agents.web_search.search_ddg", return_value=["r1", "r2", "r3"]) as mock_ddg:
        from modules.example_module import search_web
        search_web("query")
    mock_ddg.assert_called_once_with("query", 3)
