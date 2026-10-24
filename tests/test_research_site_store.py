import json
from pathlib import Path
from unittest.mock import patch


def test_list_sites_returns_defaults(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import list_sites
        sites = list_sites()
    assert len(sites) == 14
    slugs = [s["slug"] for s in sites]
    assert "google-scholar" in slugs
    assert "arxiv" in slugs
    assert "sci-hub" in slugs


def test_get_site_returns_dict(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import get_site
        site = get_site("arxiv")
    assert site is not None
    assert site["name"] == "arXiv"
    assert "{query}" in site["search_url"]
    assert site["requires_login"] is False


def test_get_site_unknown_returns_none(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import get_site
        assert get_site("does-not-exist") is None


def test_add_site_persists(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import add_site, get_site
        add_site(
            slug="test-site",
            name="Test Site",
            url="https://example.com/",
            search_url="https://example.com/search?q={query}",
            requires_login=True,
            category="dev",
        )
        site = get_site("test-site")
    assert site is not None
    assert site["name"] == "Test Site"
    assert site["requires_login"] is True
    assert site["category"] == "dev"


def test_remove_site_returns_true_for_existing(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import remove_site, get_site
        removed = remove_site("arxiv")
        assert removed is True
        assert get_site("arxiv") is None


def test_remove_site_returns_false_for_missing(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import remove_site
        assert remove_site("no-such-site") is False


def test_set_credential_key_updates_site(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import set_credential_key, get_site
        result = set_credential_key("jstor", "plia-research")
        site = get_site("jstor")
    assert result is True
    assert site["credential_key"] == "plia-research"


def test_set_credential_key_returns_false_for_missing_slug(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import set_credential_key
        result = set_credential_key("no-such-site", "key")
    assert result is False


def test_list_sites_includes_slug_field(tmp_path):
    sites_file = tmp_path / "research_sites.json"
    with patch("core.research_site_store._SITES_FILE", sites_file):
        from core.research_site_store import list_sites
        sites = list_sites()
    for s in sites:
        assert "slug" in s
        assert s["slug"] != ""
