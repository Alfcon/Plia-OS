import pytest
from unittest.mock import patch, MagicMock


def test_fetch_news_returns_results():
    fake_result = [
        {"date": "2026-06-20T10:00:00", "title": "Big story", "source": "BBC", "url": "https://bbc.co.uk/1"}
    ]
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.news.return_value = fake_result
    with patch("modules.news_tools._DDGS", mock_ddgs):
        from modules.news_tools import fetch_news
        result = fetch_news("python", max_items=1)
    assert "Big story" in result
    assert "BBC" in result
    assert "bbc.co.uk" in result


def test_fetch_news_no_results():
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.news.return_value = []
    with patch("modules.news_tools._DDGS", mock_ddgs):
        from modules.news_tools import fetch_news
        result = fetch_news("obscure_topic_xyz")
    assert "No news found" in result


def test_fetch_news_ddgs_missing():
    with patch("modules.news_tools._DDGS", None):
        from modules.news_tools import fetch_news
        result = fetch_news("python")
    assert "not installed" in result.lower()


def test_fetch_rss_parses_feed():
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.feed.get.return_value = "Test Feed"
    entry = MagicMock()
    entry.get.side_effect = lambda k, d="": {
        "title": "Entry 1", "link": "https://example.com/1", "published": "2026-06-20T00:00:00"
    }.get(k, d)
    mock_feed.entries = [entry]

    mock_fp = MagicMock()
    mock_fp.parse.return_value = mock_feed
    with patch("modules.news_tools._feedparser", mock_fp):
        from modules.news_tools import fetch_rss
        result = fetch_rss("https://example.com/feed.rss")
    assert "Entry 1" in result
    assert "example.com/1" in result


def test_fetch_rss_empty_feed():
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.feed.get.return_value = "Empty Feed"
    mock_feed.entries = []

    mock_fp = MagicMock()
    mock_fp.parse.return_value = mock_feed
    with patch("modules.news_tools._feedparser", mock_fp):
        from modules.news_tools import fetch_rss
        result = fetch_rss("https://example.com/empty.rss")
    assert "no entries" in result.lower()


def test_fetch_rss_feedparser_missing():
    with patch("modules.news_tools._feedparser", None):
        from modules.news_tools import fetch_rss
        result = fetch_rss("https://example.com/feed.rss")
    assert "not installed" in result.lower()
