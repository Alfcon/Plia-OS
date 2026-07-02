import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_extract_snippets_absolutizes_relative_urls():
    from modules.research_tools import _extract_snippets
    html = '<a href="/abs/2301.001">Quantum Turbulence in Superfluids</a> abstract text here'
    out = _extract_snippets(html, "https://arxiv.org/search/?q=x")
    assert out[0]["url"] == "https://arxiv.org/abs/2301.001"
    assert out[0]["title"] == "Quantum Turbulence in Superfluids"


def test_extract_snippets_filters_nav_and_boilerplate():
    from modules.research_tools import _extract_snippets
    html = (
        '<nav><a href="/home">Home</a></nav>'
        '<a href="https://x.org/login">Log in to your account</a>'
        '<a href="/donate">Donate</a>'
        '<a href="/paper/1">Magnetohydrodynamic Saltwater Generators</a> some context'
    )
    out = _extract_snippets(html, "https://x.org/search")
    assert [r["title"] for r in out] == ["Magnetohydrodynamic Saltwater Generators"]


def test_extract_snippets_dedupes_and_drops_self_link():
    from modules.research_tools import _extract_snippets
    html = (
        '<a href="https://x.org/search">the search page itself here</a>'
        '<a href="/p/1">A Genuine Result Title One</a> a'
        '<a href="/p/1">A Genuine Result Title One</a> b'
    )
    out = _extract_snippets(html, "https://x.org/search")
    assert len(out) == 1
    assert out[0]["url"] == "https://x.org/p/1"


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
        category="general",
    )
    assert "my-site" in result
    assert "added" in result.lower()


def test_add_research_site_invalid_slug():
    with patch("core.research_site_store.add_site") as mock_add:
        from modules.research_tools import add_research_site
        result = add_research_site(
            slug="My-SITE_Invalid",
            name="My Site",
            url="https://mysite.com/",
            search_url="https://mysite.com/search?q={query}",
            requires_login=False,
        )
    mock_add.assert_not_called()
    assert "Invalid slug" in result
    assert "lowercase letters, digits, and hyphens" in result


def test_add_research_site_with_category():
    with patch("core.research_site_store.add_site") as mock_add:
        from modules.research_tools import add_research_site
        result = add_research_site(
            slug="my-journal",
            name="My Journal",
            url="https://myjournal.com/",
            search_url="https://myjournal.com/search?q={query}",
            requires_login=False,
            category="academic",
        )
    mock_add.assert_called_once_with(
        slug="my-journal",
        name="My Journal",
        url="https://myjournal.com/",
        search_url="https://myjournal.com/search?q={query}",
        requires_login=False,
        category="academic",
    )
    assert "my-journal" in result
    assert "added" in result.lower()


def test_remove_research_site_calls_store():
    with patch("core.research_site_store.remove_site", return_value=True), \
         patch("core.credential_store.remove_credentials") as mock_remove_creds:
        from modules.research_tools import remove_research_site
        result = remove_research_site("arxiv")
    mock_remove_creds.assert_called_once_with("arxiv")
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


@pytest.mark.asyncio
async def test_research_search_returns_chat_results():
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?searchtype=all&query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/2301.00001">MHD Saltwater Research</a> Abstract about magnetohydrodynamics.'

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("MHD saltwater generators", sites="arxiv", output_formats="chat")

    assert "arXiv" in result
    assert "arxiv.org" in result


@pytest.mark.asyncio
async def test_research_search_multiple_sites_gathered():
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
        {"slug": "loc", "name": "Library of Congress", "url": "https://www.loc.gov/", "search_url": "https://www.loc.gov/search/?q={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    by_slug = {s["slug"]: s for s in mock_sites}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '<a href="https://example.org/1">A Result Title Here</a> some context text.'

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", side_effect=lambda slug: by_slug.get(slug)), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response) as mock_fetch, \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("q", sites="arxiv,loc", output_formats="chat")

    assert mock_fetch.await_count == 2
    assert "arXiv" in result
    assert "Library of Congress" in result


@pytest.mark.asyncio
async def test_research_search_login_required_no_creds():
    mock_sites = [
        {"slug": "jstor", "name": "JSTOR", "url": "https://www.jstor.org/", "search_url": "https://www.jstor.org/action/doBasicSearch?Query={query}", "requires_login": True, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("test query", sites="jstor", output_formats="chat")

    assert "LOGIN REQUIRED" in result or "login required" in result.lower()
    assert "set_site_credentials" in result


@pytest.mark.asyncio
async def test_research_search_timeout_handled():
    import httpx
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("test", sites="arxiv", output_formats="chat")

    assert "Timeout" in result or "timeout" in result.lower()


@pytest.mark.asyncio
async def test_research_search_http_error_handled():
    import httpx
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = ""

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("test", sites="arxiv", output_formats="chat")

    assert "403" in result or "HTTP" in result


@pytest.mark.asyncio
async def test_research_search_tts_output_emits_speak():
    from unittest.mock import AsyncMock
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/001">Title One Paper Result</a> Some context here.'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html
    mock_emit = AsyncMock()

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", mock_emit):
        from modules.research_tools import research_search
        await research_search("test query", sites="arxiv", output_formats="chat,tts")

    speak_calls = [c for c in mock_emit.call_args_list if c.args[0] == "speak"]
    assert len(speak_calls) == 1
    assert "test query" in speak_calls[0].args[1]["message"]


@pytest.mark.asyncio
async def test_research_search_file_output_writes_file(tmp_path):
    mock_sites = [
        {"slug": "google", "name": "Google", "url": "https://google.com/", "search_url": "https://google.com/search?q={query}", "requires_login": False, "category": "general", "credential_key": None},
    ]
    fake_html = '<a href="https://example.com/abs/001">Paper Title Extended</a> Abstract text here.'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock), \
         patch("modules.research_tools._RESEARCH_DIR", tmp_path):
        from modules.research_tools import research_search
        result = await research_search("paper topic", sites="google", output_formats="chat,file")

    written = list(tmp_path.glob("*.md"))
    assert len(written) == 1
    assert "Paper Title" in written[0].read_text()


@pytest.mark.asyncio
async def test_research_search_browser_output_calls_xdg_open(tmp_path):
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    fake_html = '<a href="https://arxiv.org/abs/001">Browser Title Result</a>'
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = fake_html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock), \
         patch("subprocess.Popen") as mock_popen, \
         patch("modules.research_tools._RESEARCH_DIR", tmp_path):
        from modules.research_tools import research_search
        await research_search("browser test", sites="arxiv", output_formats="chat,browser")

    assert mock_popen.called
    args = mock_popen.call_args[0][0]
    assert args[0] == "xdg-open"


def test_parse_arxiv_extracts_results():
    from modules.research_tools import _parse_arxiv
    html = (
        '<li class="arxiv-result">'
        '<p class="list-title is-inline-block"><a href="/abs/2301.00001">arXiv:2301.00001</a></p>'
        '<p class="title is-5 mathjax">Magnetohydrodynamic Power from Seawater</p>'
        '<span class="abstract-full">We study MHD generators driven by saltwater flow.</span>'
        '</li>'
    )
    out = _parse_arxiv(html, "https://arxiv.org/search/?q=mhd")
    assert len(out) == 1
    assert out[0]["title"] == "Magnetohydrodynamic Power from Seawater"
    assert out[0]["url"] == "https://arxiv.org/abs/2301.00001"
    assert "saltwater" in out[0]["snippet"]


def test_parse_arxiv_malformed_returns_empty():
    from modules.research_tools import _parse_arxiv
    assert _parse_arxiv("<html>no results here</html>", "https://arxiv.org/") == []


@pytest.mark.asyncio
async def test_research_search_uses_arxiv_parser():
    mock_sites = [
        {"slug": "arxiv", "name": "arXiv", "url": "https://arxiv.org/", "search_url": "https://arxiv.org/search/?query={query}", "requires_login": False, "category": "academic", "credential_key": None},
    ]
    html = (
        '<li class="arxiv-result">'
        '<p class="list-title"><a href="/abs/9.9">arXiv:9.9</a></p>'
        '<p class="title is-5 mathjax">Deep Result From Arxiv Parser</p>'
        '<span class="abstract-full">body text</span>'
        '</li>'
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html

    with patch("core.research_site_store.list_sites", return_value=mock_sites), \
         patch("core.research_site_store.get_site", return_value=mock_sites[0]), \
         patch("core.credential_store.has_credentials", return_value=False), \
         patch("modules.research_tools._fetch", new_callable=AsyncMock, return_value=mock_response), \
         patch("core.events.emit", new_callable=AsyncMock):
        from modules.research_tools import research_search
        result = await research_search("q", sites="arxiv", output_formats="chat")

    assert "Deep Result From Arxiv Parser" in result
    assert "arxiv.org/abs/9.9" in result
