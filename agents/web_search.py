from __future__ import annotations
import asyncio
import re
import logging
import httpx
from ddgs import DDGS

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None  # type: ignore[assignment]


def _fmt_results(items: list[dict], title_key: str, body_key: str, url_key: str) -> list[str]:
    out = []
    for i, r in enumerate(items, 1):
        out.append(f"[{i}] {r[title_key]}\n{r[body_key]}\n{r[url_key]}")
    return out


def search_ddg(query: str, max_results: int = 5) -> list[str]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return _fmt_results(results, "title", "body", "href")
    except Exception as exc:
        logger.warning("DDG search error: %s", exc)
        return [f"Search error: {exc}"]


def search_google(query: str, api_key: str, cx: str, max_results: int = 5) -> list[str]:
    try:
        resp = httpx.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"q": query, "key": api_key, "cx": cx, "num": max_results},
            timeout=10.0,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return _fmt_results(
            [{"title": i["title"], "snippet": i["snippet"], "link": i["link"]} for i in items[:max_results]],
            "title", "snippet", "link",
        )
    except Exception as exc:
        logger.warning("Google search error: %s", exc)
        return [f"Google search error: {exc}"]


async def scrape_playwright(url: str, max_chars: int = 2000) -> str:
    if async_playwright is None:
        return "Playwright not installed. Run: pip install playwright && playwright install chromium"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                text = await page.inner_text("body")
            finally:
                await browser.close()
        return text[:max_chars]
    except Exception as exc:
        logger.warning("Playwright scrape error: %s", exc)
        return f"Scrape error: {exc}"


async def web_search(query_or_url: str, provider: str, config) -> list[str]:
    max_results = getattr(config, "web_search_max_results", 5)
    url_match = _URL_RE.search(query_or_url)
    if url_match or provider == "playwright":
        target = url_match.group(0) if url_match else query_or_url
        text = await scrape_playwright(target)
        return [text]
    if provider == "google":
        if config.google_search_api_key and config.google_search_cx:
            return await asyncio.to_thread(
                search_google, query_or_url, config.google_search_api_key, config.google_search_cx, max_results
            )
        logger.info("Google credentials not configured, falling back to DDG")
    return await asyncio.to_thread(search_ddg, query_or_url, max_results)
