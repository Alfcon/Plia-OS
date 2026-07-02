from __future__ import annotations

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
    "requires_login: true if the site needs credentials."
)
def add_research_site(
    slug: str,
    name: str,
    url: str,
    search_url: str,
    requires_login: bool = False,
) -> str:
    from core.research_site_store import add_site
    add_site(slug=slug, name=name, url=url, search_url=search_url, requires_login=requires_login)
    return f"Site '{slug}' ({name}) added to research registry."


@tool("Remove a site from the research registry by its slug.")
def remove_research_site(slug: str) -> str:
    from core.research_site_store import remove_site
    if remove_site(slug):
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
    set_credential_key(site_slug, "plia-research")
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


import re as _re
import subprocess
from datetime import date
from pathlib import Path

_RESEARCH_DIR = Path.home() / "research"


def _extract_snippets(html: str, max_results: int = 10) -> list[dict]:
    html = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=_re.DOTALL | _re.IGNORECASE)
    pattern = _re.compile(
        r'<a[^>]+href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>',
        _re.DOTALL | _re.IGNORECASE,
    )
    results = []
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        text = _re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not href.startswith("http") or len(text) < 5 or len(text) > 300:
            continue
        raw_after = html[m.end():m.end() + 600]
        snippet = _re.sub(r"<[^>]+>", " ", raw_after)
        snippet = _re.sub(r"\s+", " ", snippet).strip()[:200]
        results.append({"title": text, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


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
            rows += f'<tr><td>{idx}</td><td>{site_name}</td><td colspan="2"><em>{results}</em></td></tr>'
            idx += 1
            continue
        for r in results:
            title_cell = f'<a href="{r["url"]}">{r["title"]}</a>'
            rows += f"<tr><td>{idx}</td><td>{site_name}</td><td>{title_cell}</td><td>{r['snippet']}</td></tr>"
            idx += 1
    return (
        f"<!DOCTYPE html><html><head><title>Research: {query}</title>"
        "<style>body{font-family:sans-serif;max-width:1200px;margin:2em auto}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:.5em;text-align:left}"
        "th{background:#eee}a{color:#0066cc}</style></head><body>"
        f"<h1>Research: {query}</h1>"
        "<table><tr><th>#</th><th>Site</th><th>Title</th><th>Snippet</th></tr>"
        f"{rows}</table></body></html>"
    )


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

    all_results: dict = {}
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    for slug in site_slugs:
        site = get_site(slug)
        if site is None:
            all_results[slug] = f"[Unknown site '{slug}']"
            continue

        site_name = site["name"]

        if site["requires_login"] and not has_credentials(slug):
            all_results[site_name] = (
                f"[LOGIN REQUIRED — use set_site_credentials('{slug}', username, password) to add credentials]"
            )
            continue

        url = site["search_url"].replace("{query}", encoded)
        request_kwargs: dict = {"headers": headers, "timeout": 15, "follow_redirects": True}

        if site["requires_login"]:
            creds = get_credentials(slug)
            if creds:
                request_kwargs["auth"] = (creds["username"], creds["password"])

        try:
            resp = httpx.get(url, **request_kwargs)
        except httpx.TimeoutException:
            all_results[site_name] = "[Timeout after 15s]"
            continue
        except Exception as exc:
            all_results[site_name] = f"[Fetch error: {type(exc).__name__}]"
            continue

        if resp.status_code != 200:
            if resp.status_code == 401 and site["requires_login"]:
                all_results[site_name] = (
                    f"[HTTP 401 — credentials stored but site requires browser login (Phase 2)]"
                )
            else:
                all_results[site_name] = f"[HTTP {resp.status_code}]"
            continue

        snippets = _extract_snippets(resp.text)
        all_results[site_name] = snippets if snippets else [{"title": "(no results parsed)", "url": url, "snippet": ""}]

    # Build chat output (always)
    chat_lines = [f"## Research results for: {query}\n"]
    idx = 1
    for site_name, results in all_results.items():
        chat_lines.append(f"### {site_name}")
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
