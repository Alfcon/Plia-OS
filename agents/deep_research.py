from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

_SCRAPE_CAP = 3000
_TEXT_BLOCK_CAP = 2000


def _parse_json_array(text: str) -> list | None:
    start = text.find("[")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, list):
                            return obj
                    except Exception:
                        pass
                    break
        start = text.find("[", start + 1)
    return None


async def _plan_queries(topic: str, max_subqueries: int) -> list[str]:
    from agents.llm import call_llm
    prompt = (
        f"Break this research topic into up to {max_subqueries} focused web-search "
        f"queries that together cover it well. Topic: {topic}\n"
        "Reply with ONLY a JSON array of query strings."
    )
    try:
        reply = await call_llm([{"role": "user", "content": prompt}])
        content = reply.get("content", "") if isinstance(reply, dict) else ""
        arr = _parse_json_array(content)
        queries = [str(q).strip() for q in arr if str(q).strip()] if arr else []
    except Exception as exc:
        logger.warning("Deep research plan failed: %s", exc)
        queries = []
    return queries[:max_subqueries] if queries else [topic]


def _ddg_search(query: str, per_query: int) -> list[dict]:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=per_query))
    except Exception as exc:
        logger.warning("Deep research DDG error: %s", exc)
        return []


async def _scrape(url: str) -> str:
    import httpx
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:_SCRAPE_CAP]
    except Exception:
        return ""


async def _web_sources(subqueries: list[str], per_query: int = 3) -> list[dict]:
    seen: set[str] = set()
    hits: list[dict] = []
    for sq in subqueries:
        for r in await asyncio.to_thread(_ddg_search, sq, per_query):
            url = r.get("href", "")
            if not url or url in seen:
                continue
            seen.add(url)
            hits.append({"title": r.get("title", ""), "url": url, "snippet": r.get("body", "")})
    texts = await asyncio.gather(*[_scrape(h["url"]) for h in hits])
    return [
        {"title": h["title"], "url": h["url"], "text": text or h["snippet"]}
        for h, text in zip(hits, texts)
    ]


async def _academic_sources(subqueries: list[str]) -> list[dict]:
    from modules.research_tools import research_search
    sources: list[dict] = []
    for sq in subqueries:
        try:
            blob = await research_search(sq, sites="all", output_formats="chat")
        except Exception as exc:
            logger.warning("Deep research academic error for %s: %s", sq, exc)
            continue
        sources.append({"title": sq, "url": "", "text": blob})
    return sources


async def _gather_sources(subqueries: list[str], source: str, per_query: int = 3) -> list[dict]:
    if source == "academic":
        return await _academic_sources(subqueries)
    if source == "both":
        return (await _web_sources(subqueries, per_query)) + (await _academic_sources(subqueries))
    return await _web_sources(subqueries, per_query)


def _numbered_blocks(sources: list[dict]) -> str:
    lines = []
    for n, s in enumerate(sources, 1):
        url = s.get("url") or "(no url)"
        text = (s.get("text") or "")[:_TEXT_BLOCK_CAP]
        lines.append(f"[{n}] {url}\n{text}")
    return "\n\n".join(lines)


async def _synthesize(topic: str, sources: list[dict]) -> str:
    from agents.llm import call_llm
    if not sources:
        return f"No sources gathered for '{topic}'."
    blocks = _numbered_blocks(sources)
    prompt = (
        f"Write a research report on: {topic}\n\n"
        f"Use ONLY these numbered sources; cite them inline as [n].\n\n{blocks}\n\n"
        "Format as Markdown with: a short summary; key findings (with [n] citations); "
        "a '## Gaps / what's still unknown' section; and a '## Sources' list mapping "
        "each [n] to its URL."
    )
    try:
        reply = await call_llm([{"role": "user", "content": prompt}])
        content = reply.get("content", "") if isinstance(reply, dict) else ""
        if content.strip():
            return content
    except Exception as exc:
        logger.warning("Deep research synthesis failed: %s", exc)
    return f"# Research: {topic}\n\n(Could not synthesize — raw sources below.)\n\n{blocks}"


async def run_deep_research(topic: str, source: str = "web", max_subqueries: int = 4,
                            output_formats: str = "chat") -> str:
    from datetime import date
    formats = {f.strip() for f in output_formats.split(",") if f.strip()}
    max_sq = max(1, min(int(max_subqueries), 8))
    subqueries = await _plan_queries(topic, max_sq)
    sources = await _gather_sources(subqueries, source, per_query=3)
    report = await _synthesize(topic, sources)

    if "file" in formats:
        try:
            from modules.research_tools import _RESEARCH_DIR, _query_slug
            _RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
            fpath = _RESEARCH_DIR / f"deepresearch_{_query_slug(topic)}_{date.today().isoformat()}.md"
            fpath.write_text(report)
            report += f"\n\nSaved to `{fpath}`."
        except Exception as exc:
            report += f"\n\n(File output failed: {exc})"

    if "browser" in formats:
        try:
            import html as _html
            import subprocess
            import tempfile
            from modules.research_tools import _query_slug
            page = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Research: "
                f"{_html.escape(topic)}</title></head><body>"
                "<pre style='white-space:pre-wrap;font-family:sans-serif;max-width:820px;margin:2em auto;'>"
                f"{_html.escape(report)}</pre></body></html>"
            )
            with tempfile.NamedTemporaryFile(
                prefix=f"deepresearch_{_query_slug(topic)}_", suffix=".html", delete=False
            ) as f:
                f.write(page.encode())
                fpath = f.name
            subprocess.Popen(["xdg-open", fpath])
            report += f"\n\nOpened in browser (`{fpath}`)."
        except FileNotFoundError:
            report += "\n\n(Browser output unavailable — xdg-open not found.)"
        except Exception as exc:
            report += f"\n\n(Browser output failed: {exc})"

    return report
