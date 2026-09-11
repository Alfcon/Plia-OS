from core.registry import tool


@tool(description="Search the web for current information. Returns top results with title, snippet, and URL.")
def search_web(query: str) -> str:
    from core.config import get_config
    from agents.web_search import search_ddg, search_google
    cfg = get_config()
    provider = cfg.web_search_default
    max_results = cfg.web_search_max_results
    if provider == "google" and cfg.google_search_api_key and cfg.google_search_cx:
        results = search_google(query, cfg.google_search_api_key, cfg.google_search_cx, max_results)
    else:
        results = search_ddg(query, max_results)
    if not results:
        return "No results found."
    return "\n\n".join(results)


@tool(description="Fetch and read the text content of a web page. Use for reading articles, docs, or any URL.")
def scrape_url(url: str) -> str:
    import re
    import httpx
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:2000] or "(no content)"
    except httpx.HTTPError as exc:
        return f"Fetch error: {exc}"
