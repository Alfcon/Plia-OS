from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_SITES_FILE = Path(
    os.environ.get(
        "PLIA_RESEARCH_SITES_FILE",
        str(
            Path(
                os.environ.get("PLIA_CONFIG_FILE", str(Path.home() / ".plia" / "config.json"))
            ).parent
            / "research_sites.json"
        ),
    )
)


def _default_sites() -> dict:
    return {
        "google-scholar": {
            "name": "Google Scholar",
            "url": "https://scholar.google.com/",
            "search_url": "https://scholar.google.com/scholar?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "worldcat": {
            "name": "WorldCat",
            "url": "https://www.worldcat.org/",
            "search_url": "https://www.worldcat.org/search?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "researchgate": {
            "name": "ResearchGate",
            "url": "https://www.researchgate.net/",
            "search_url": "https://www.researchgate.net/search?q={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "bepress": {
            "name": "bepress Network",
            "url": "https://works.bepress.com/",
            "search_url": "https://works.bepress.com/search/?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "google-books": {
            "name": "Google Books",
            "url": "https://books.google.com/",
            "search_url": "https://www.google.com/search?tbm=bks&q={query}",
            "requires_login": False,
            "category": "general",
            "credential_key": None,
        },
        "pubmed-central": {
            "name": "PubMed Central",
            "url": "https://www.ncbi.nlm.nih.gov/pmc/",
            "search_url": "https://www.ncbi.nlm.nih.gov/pmc/search/?query={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "loc": {
            "name": "Library of Congress",
            "url": "https://www.loc.gov/",
            "search_url": "https://www.loc.gov/search/?q={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "jstor": {
            "name": "JSTOR",
            "url": "https://www.jstor.org/",
            "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "sciencedirect": {
            "name": "ScienceDirect",
            "url": "https://www.sciencedirect.com/",
            "search_url": "https://www.sciencedirect.com/search?qs={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "academia-edu": {
            "name": "Academia.edu",
            "url": "https://www.academia.edu/",
            "search_url": "https://www.academia.edu/search?q={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "library-gov-au": {
            "name": "National Library of Australia",
            "url": "https://catalogue.nla.gov.au/",
            "search_url": "https://catalogue.nla.gov.au/Search/Home?lookfor={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "ieee-xplore": {
            "name": "IEEE Xplore",
            "url": "https://ieeexplore.ieee.org/",
            "search_url": "https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true&queryText={query}",
            "requires_login": True,
            "category": "academic",
            "credential_key": None,
        },
        "arxiv": {
            "name": "arXiv",
            "url": "https://arxiv.org/",
            "search_url": "https://arxiv.org/search/?searchtype=all&query={query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
        "sci-hub": {
            "name": "Sci-Hub",
            "url": "https://sci-hub.in/",
            "search_url": "https://sci-hub.in/{query}",
            "requires_login": False,
            "category": "academic",
            "credential_key": None,
        },
    }


def _load() -> dict:
    try:
        return json.loads(_SITES_FILE.read_text())
    except Exception as e:
        logging.warning(f"Failed to load research sites from {_SITES_FILE}: {e}")
        return _default_sites()


def _save(data: dict) -> None:
    _SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SITES_FILE.write_text(json.dumps(data, indent=2))


def list_sites() -> list[dict]:
    data = _load()
    return [{"slug": slug, **entry} for slug, entry in sorted(data.items())]


def get_site(slug: str) -> dict | None:
    data = _load()
    if slug not in data:
        return None
    return {"slug": slug, **data[slug]}


def add_site(
    slug: str,
    name: str,
    url: str,
    search_url: str,
    requires_login: bool = False,
    category: str = "general",
) -> None:
    data = _load()
    data[slug] = {
        "name": name,
        "url": url,
        "search_url": search_url,
        "requires_login": requires_login,
        "category": category,
        "credential_key": None,
    }
    _save(data)


def remove_site(slug: str) -> bool:
    data = _load()
    if slug not in data:
        return False
    del data[slug]
    _save(data)
    return True


def set_credential_key(slug: str, key: str) -> bool:
    data = _load()
    if slug not in data:
        return False
    data[slug]["credential_key"] = key
    _save(data)
    return True
