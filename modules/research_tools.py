from __future__ import annotations

import asyncio
import html as _html
import re as _re
import subprocess
from datetime import date
from pathlib import Path

from core.registry import tool


@tool(
    "List all registered research sites. Shows name, URL, login requirement, "
    "and whether credentials are stored."
)
def list_research_sites() -> str:
    from core.research_site_store import list_sites
    from core.credential_store import has_credentials
    sites = list_sites()
    if not sites:
        return "No research sites registered."
    lines = []
    for s in sites:
        login = ""
        if s["requires_login"]:
            stored = has_credentials(s["slug"])
            login = " [login required — credentials stored]" if stored else " [login required — no credentials stored]"
        lines.append(f"- **{s['slug']}**: {s['name']} ({s['category']}){login}")
        lines.append(f"  Search: {s['search_url']}")
    return "\n".join(lines)


@tool(
    "Add a custom site to the research registry. "
    "slug: short identifier (lowercase, hyphens only, e.g. 'my-journal'). "
    "name: display name. url: base URL. search_url: URL with {query} placeholder. "
    "requires_login: true if the site needs credentials. "
    "category: 'academic', 'dev', or 'general' (default: 'general')."
)
def add_research_site(
    slug: str,
    name: str,
    url: str,
    search_url: str,
    requires_login: bool = False,
    category: str = "general",
) -> str:
    from core.research_site_store import add_site
    if not _re.match(r"^[a-z0-9-]+$", slug):
        return f"Invalid slug '{slug}'. Use lowercase letters, digits, and hyphens only."
    add_site(slug=slug, name=name, url=url, search_url=search_url, requires_login=requires_login, category=category)
    return f"Site '{slug}' ({name}) added to research registry."


@tool("Remove a site from the research registry by its slug.")
def remove_research_site(slug: str) -> str:
    from core.research_site_store import remove_site
    from core.credential_store import remove_credentials
    if remove_site(slug):
        remove_credentials(slug)
        return f"Site '{slug}' removed from research registry."
    return f"No site with slug '{slug}' found."


@tool(
    "Store login credentials for a research site. "
    "site_slug must match a slug from list_research_sites. "
    "Credentials are stored in the system keyring or an encrypted file — never in plain text."
)
def set_site_credentials(site_slug: str, username: str, password: str) -> str:
    from core.research_site_store import get_site, set_credential_key
    from core.credential_store import set_credentials
    site = get_site(site_slug)
    if site is None:
        return f"No site with slug '{site_slug}' found. Run list_research_sites to see available sites."
    result = set_credentials(site_slug, username, password)
    # Record the key credentials are actually stored under (the slug), not the
    # keyring service name — the store retrieves by slug.
    set_credential_key(site_slug, site_slug)
    return f"{result} Credentials for '{site_slug}' ({site['name']}) are ready."


@tool(
    "Check whether credentials are stored for a research site. "
    "Never returns the password — only confirms presence or absence."
)
def check_site_credentials(site_slug: str) -> str:
    from core.credential_store import has_credentials
    if has_credentials(site_slug):
        return f"Credentials for '{site_slug}' are stored."
    return f"No credentials stored for '{site_slug}'."


@tool("Remove stored credentials for a research site.")
def remove_site_credentials(site_slug: str) -> str:
    from core.credential_store import remove_credentials
    if remove_credentials(site_slug):
        return f"Credentials for '{site_slug}' removed."
    return f"No credentials found for '{site_slug}'."


_RESEARCH_DIR = Path.home() / "research"


_BOILERPLATE_PHRASES = (
    "skip to", "sign in", "sign up", "log in", "learn more", "advanced search",
    "privacy policy", "cookie policy", "terms of service", "terms of use",
    "create account", "forgot password", "subscribe to",
)


def _extract_snippets(html: str, base_url: str, max_results: int = 10) -> list[dict]:
    from urllib.parse import urljoin
    html = _re.sub(
        r"<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>",
        "", html, flags=_re.DOTALL | _re.IGNORECASE,
    )
    pattern = _re.compile(
        r'<a[^>]+href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',
        _re.DOTALL | _re.IGNORECASE,
    )
    results: list[dict] = []
    seen: set[str] = set()
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        if url == base_url or url in seen:
            continue
        text = _re.sub(r"<[^>]+>", "", m.group(2))
        text = _re.sub(r"\s+", " ", text).strip()
        if len(text) < 15 or len(text) > 300:
            continue
        low = text.lower()
        if any(p in low for p in _BOILERPLATE_PHRASES):
            continue
        raw_after = html[m.end():m.end() + 600]
        snippet = _re.sub(r"<[^>]+>", " ", raw_after)
        snippet = _re.sub(r"\s+", " ", snippet).strip()[:200]
        results.append({"title": text, "url": url, "snippet": snippet})
        seen.add(url)
        if len(results) >= max_results:
            break
    return results


def _parse_arxiv(html: str, base_url: str) -> list[dict]:
    from urllib.parse import urljoin
    results: list[dict] = []
    for block in _re.findall(r'<li class="arxiv-result">(.*?)</li>', html, _re.DOTALL | _re.IGNORECASE):
        m_url = _re.search(r'<a href="([^"]*?/abs/[^"]*)"', block, _re.IGNORECASE)
        m_title = _re.search(r'<p class="title[^"]*">(.*?)</p>', block, _re.DOTALL | _re.IGNORECASE)
        if not m_url or not m_title:
            continue
        title = _re.sub(r"<[^>]+>", "", m_title.group(1))
        title = _re.sub(r"\s+", " ", title).strip()
        snippet = ""
        m_abs = _re.search(r'<span class="abstract-full[^"]*">(.*?)</span>', block, _re.DOTALL | _re.IGNORECASE)
        if m_abs:
            snippet = _re.sub(r"<[^>]+>", " ", m_abs.group(1))
            snippet = _re.sub(r"\s+", " ", snippet).strip()[:200]
        results.append({"title": title, "url": urljoin(base_url, m_url.group(1)), "snippet": snippet})
    return results


_SITE_PARSERS = {
    "arxiv": _parse_arxiv,
}


def _query_slug(query: str) -> str:
    return _re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50]


def _results_to_markdown(query: str, all_results: dict) -> str:
    lines = [f"# Research: {query}\n"]
    idx = 1
    for site_name, results in all_results.items():
        lines.append(f"\n## {site_name}\n")
        if isinstance(results, str):
            lines.append(results)
            continue
        for r in results:
            lines.append(f"{idx}. [{r['title']}]({r['url']})")
            if r["snippet"]:
                lines.append(f"   > {r['snippet']}\n")
            idx += 1
    return "\n".join(lines)


def _results_to_html(query: str, all_results: dict) -> str:
    rows = ""
    idx = 1
    for site_name, results in all_results.items():
        if isinstance(results, str):
            rows += f'<tr><td>{idx}</td><td>{_html.escape(site_name)}</td><td colspan="2"><em>{_html.escape(results)}</em></td></tr>'
            idx += 1
            continue
        for r in results:
            title_cell = f'<a href="{r["url"]}">{_html.escape(r["title"])}</a>'
            rows += f"<tr><td>{idx}</td><td>{_html.escape(site_name)}</td><td>{title_cell}</td><td>{_html.escape(r['snippet'])}</td></tr>"
            idx += 1
    return (
        f"<!DOCTYPE html><html><head><title>Research: {_html.escape(query)}</title>"
        "<style>body{font-family:sans-serif;max-width:1200px;margin:2em auto}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.5em;text-align:left}"
        "th{background:#eee}a{color:#0066cc}</style></head><body>"
        f"<h1>Research: {_html.escape(query)}</h1>"
        "<table><tr><th>#</th><th>Site</th><th>Title</th><th>Snippet</th></tr>"
        f"{rows}</table></body></html>"
    )


async def _fetch(url: str, **kwargs):
    """Async HTTP GET. Isolated so research_search never blocks the event loop
    and so tests have a single patch point."""
    import httpx
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await client.get(url, **kwargs)


@tool(
    "Search one or more research sites for a query. "
    "sites: comma-separated slugs (e.g. 'google-scholar,arxiv') or 'all' for all registered sites. "
    "output_formats: comma-separated subset of: chat, tts, browser, file. Default: chat. "
    "Returns numbered results — user can say 'read result 3' to get full content via scrape_url."
)
async def research_search(
    query: str,
    sites: str = "all",
    output_formats: str = "chat",
) -> str:
    import httpx
    from urllib.parse import quote_plus
    from core.research_site_store import list_sites, get_site
    from core.credential_store import has_credentials, get_credentials
    from core import events

    formats = {f.strip() for f in output_formats.split(",") if f.strip()}
    encoded = quote_plus(query)

    if sites.strip().lower() == "all":
        site_slugs = [s["slug"] for s in list_sites()]
    else:
        site_slugs = [s.strip() for s in sites.split(",") if s.strip()]

    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    async def _search_one(slug: str) -> tuple[str, object]:
        site = get_site(slug)
        if site is None:
            return slug, f"[Unknown site '{slug}']"

        site_name = site["name"]

        if site["requires_login"] and not has_credentials(slug):
            return site_name, (
                f"[LOGIN REQUIRED — use set_site_credentials('{slug}', username, password) to add credentials]"
            )

        url = site["search_url"].replace("{query}", encoded)
        request_kwargs: dict = {"headers": headers, "timeout": 15}

        if site["requires_login"]:
            creds = get_credentials(slug)
            if creds:
                request_kwargs["auth"] = (creds["username"], creds["password"])

        try:
            resp = await _fetch(url, **request_kwargs)
        except httpx.TimeoutException:
            return site_name, "[Timeout after 15s]"
        except Exception as exc:
            return site_name, f"[Fetch error: {type(exc).__name__}]"

        if resp.status_code != 200:
            if resp.status_code == 401 and site["requires_login"]:
                return site_name, "[HTTP 401 — credentials stored but site requires browser login (Phase 2)]"
            return site_name, f"[HTTP {resp.status_code}]"

        parser = _SITE_PARSERS.get(slug)
        snippets = parser(resp.text, url) if parser else _extract_snippets(resp.text, url)
        return site_name, (snippets if snippets else [{"title": "(no results parsed)", "url": url, "snippet": ""}])

    # Fetch all sites concurrently — one slow site no longer blocks the rest,
    # and the event loop is never blocked by a synchronous request.
    pairs = await asyncio.gather(*[_search_one(slug) for slug in site_slugs])
    all_results: dict = {}
    for name, result in pairs:
        all_results[name] = result

    # Build chat output (always)
    chat_lines = []
    idx = 1
    for site_name, results in all_results.items():
        chat_lines.append(f"## {site_name}")
        if isinstance(results, str):
            chat_lines.append(results)
            chat_lines.append("")
            continue
        for r in results:
            chat_lines.append(f"{idx}. [{r['title']}]({r['url']})")
            if r["snippet"]:
                chat_lines.append(f"   > {r['snippet']}")
            idx += 1
        chat_lines.append("")
    chat_output = "\n".join(chat_lines)

    # TTS output
    if "tts" in formats:
        total = sum(len(v) for v in all_results.values() if isinstance(v, list))
        site_count = len(all_results)
        top_titles = []
        for results in all_results.values():
            if isinstance(results, list):
                for r in results[:2]:
                    if r["title"] != "(no results parsed)":
                        top_titles.append(r["title"])
            if len(top_titles) >= 3:
                break
        top_str = ", ".join(top_titles[:3]) if top_titles else "none"
        tts_msg = (
            f"Found {total} results across {site_count} sites for '{query}'. "
            f"Top results: {top_str}."
        )
        await events.emit("speak", {"message": tts_msg})

    # File output
    if "file" in formats:
        try:
            _RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"{_query_slug(query)}_{date.today().isoformat()}.md"
            fpath = _RESEARCH_DIR / fname
            fpath.write_text(_results_to_markdown(query, all_results))
            chat_output += f"\n\nResults saved to `{fpath}`."
        except Exception as exc:
            chat_output += f"\n\n(File output failed: {exc})"

    # Browser output
    if "browser" in formats:
        try:
            import tempfile
            html = _results_to_html(query, all_results)
            slug = _query_slug(query)
            with tempfile.NamedTemporaryFile(
                prefix=f"plia_research_{slug}_", suffix=".html", delete=False
            ) as f:
                f.write(html.encode())
                fpath = f.name
            subprocess.Popen(["xdg-open", fpath])
            chat_output += f"\n\nOpened results in browser (`{fpath}`)."
        except FileNotFoundError:
            chat_output += "\n\n(Browser output unavailable — xdg-open not found.)"
        except Exception as exc:
            chat_output += f"\n\n(Browser output failed: {exc})"

    return chat_output
