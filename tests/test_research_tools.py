import pytest
from unittest.mock import patch, MagicMock


def test_list_research_sites_shows_all(tmp_path):
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
        {"slug": "jstor", "name": "JSTOR", "url": "https://www.jstor.org/", "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}", "requires_login": True, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.credential_store.has_credentials", return_value=False):
        from modules.research_tools import list_research_sites
        result = list_research_sites()
    assert "arXiv" in result
    assert "JSTOR" in result
    assert "login required" in result.lower()


def test_list_research_sites_shows_credentials_stored(tmp_path):
    mock_sites = [
        {"slug": "jstor", "name": "JSTOR", "url": "https://www.jstor.org/", "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}", "requires_login": True, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.credential_store.has_credentials", return_value=True):
        from modules.research_tools import list_research_sites
        result = list_research_sites()
    assert "credentials stored" in result.lower()


def test_add_research_site_calls_store():
    with patch("core.research_site_store.add_site") as mock_add:
        from modules.research_tools import add_research_site
        result = add_research_site(
            slug="my-site",
            name="My Site",
            url="https://mysite.com/",
            search_url="https://mysite.com/search?q={query}",
            requires_login=False,
        )
    mock_add.assert_called_once_with(
        slug="my-site",
        name="My Site",
        url="https://mysite.com/",
        search_url="https://mysite.com/search?q={query}",
        requires_login=False,
    )
    assert "my-site" in result
    assert "added" in result.lower()


def test_remove_research_site_calls_store():
    with patch("core.research_site_store.remove_site", return_value=True):
        from modules.research_tools import remove_research_site
        result = remove_research_site("arxiv")
    assert "arxiv" in result
    assert "removed" in result.lower()


def test_remove_research_site_not_found():
    with patch("core.research_site_store.remove_site", return_value=False):
        from modules.research_tools import remove_research_site
        result = remove_research_site("no-such")
    assert "not found" in result.lower() or "no site" in result.lower()


def test_set_site_credentials_calls_credential_store():
    with patch("core.credential_store.set_credentials", return_value="Stored in system keyring.") as mock_set, \
         patch("core.research_site_store.get_site", return_value={"slug": "jstor", "name": "JSTOR", "requires_login": True, "credential_key": None}), \
         patch("core.research_site_store.set_credential_key"):
        from modules.research_tools import set_site_credentials
        result = set_site_credentials("jstor", "alice", "secret123")
    mock_set.assert_called_once_with("jstor", "alice", "secret123")
    assert "jstor" in result.lower()


def test_set_site_credentials_unknown_site():
    with patch("core.research_site_store.get_site", return_value=None):
        from modules.research_tools import set_site_credentials
        result = set_site_credentials("unknown-slug", "u", "p")
    assert "not found" in result.lower() or "no site" in result.lower()


def test_check_site_credentials_found():
    with patch("core.credential_store.has_credentials", return_value=True):
        from modules.research_tools import check_site_credentials
        result = check_site_credentials("jstor")
    assert "stored" in result.lower()
    assert "jstor" in result


def test_check_site_credentials_not_found():
    with patch("core.credential_store.has_credentials", return_value=False):
        from modules.research_tools import check_site_credentials
        result = check_site_credentials("jstor")
    assert "no credentials" in result.lower() or "not stored" in result.lower()


def test_remove_site_credentials_success():
    with patch("core.credential_store.remove_credentials", return_value=True):
        from modules.research_tools import remove_site_credentials
        result = remove_site_credentials("jstor")
    assert "removed" in result.lower()
    assert "jstor" in result


def test_remove_site_credentials_not_found():
    with patch("core.credential_store.remove_credentials", return_value=False):
        from modules.research_tools import remove_site_credentials
        result = remove_site_credentials("jstor")
    assert "no credentials" in result.lower() or "not found" in result.lower()
