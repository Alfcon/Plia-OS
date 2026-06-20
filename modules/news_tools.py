from __future__ import annotations
from core.registry import tool

try:
    from ddgs import DDGS as _DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS as _DDGS
    except ImportError:
        _DDGS = None  # type: ignore

try:
    import feedparser as _feedparser
except ImportError:
    _feedparser = None  # type: ignore


@tool("Search for recent news on a topic. Returns headlines with URLs and publish times.")
def fetch_news(query: str, max_items: int = 5) -> str:
    if _DDGS is None:
        return "ddgs not installed. Run: pip install ddgs"
    try:
        results = list(_DDGS().news(query, max_results=max(1, min(max_items, 20))))
    except Exception as exc:
        return f"News search failed: {exc}"

    if not results:
        return f"No news found for '{query}'."

    lines = []
    for r in results:
        title = r.get("title", "")
        if not title:
            continue
        date = r.get("date", "")[:10]
        source = r.get("source", "")
        url = r.get("url", "")
        lines.append(f"[{date}] {title} — {source}\n  {url}")
    if not lines:
        return f"No news found for '{query}'."
    return "\n\n".join(lines)


@tool("Fetch and parse an RSS feed URL. Returns recent item titles and links.")
def fetch_rss(url: str, max_items: int = 10) -> str:
    if _feedparser is None:
        return "feedparser not installed. Run: pip install feedparser"
    try:
        feed = _feedparser.parse(url)
    except Exception as exc:
        return f"RSS fetch failed: {exc}"

    if feed.bozo and not feed.entries:
        return f"Could not parse feed at {url}: {feed.bozo_exception}"

    title = feed.feed.get("title", url)
    entries = feed.entries[:max(1, min(max_items, 50))]
    if not entries:
        return f"Feed '{title}' has no entries."

    lines = [f"Feed: {title}"]
    for e in entries:
        pub = e.get("published", "")[:16]
        etitle = e.get("title", "(no title)")
        link = e.get("link", "")
        lines.append(f"• [{pub}] {etitle}\n  {link}")
    return "\n".join(lines)
