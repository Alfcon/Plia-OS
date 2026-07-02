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
