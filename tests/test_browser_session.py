import json
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def _sessions_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLIA_CONFIG_FILE", str(tmp_path / "config.json"))
    return tmp_path


def test_save_and_has_session(_sessions_env):
    from core.browser_session import save_session, has_session, session_path
    assert has_session("jstor") is False
    save_session("jstor", {"cookies": [{"name": "x"}], "origins": []})
    assert has_session("jstor") is True
    p = session_path("jstor")
    assert json.loads(p.read_text())["cookies"][0]["name"] == "x"
    assert (p.stat().st_mode & 0o777) == 0o600


def test_has_session_false_for_empty_file(_sessions_env):
    from core.browser_session import session_path, has_session
    p = session_path("empty")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")
    assert has_session("empty") is False


def test_clear_session(_sessions_env):
    from core.browser_session import save_session, clear_session, has_session
    save_session("arxiv", {"cookies": [], "origins": []})
    assert clear_session("arxiv") is True
    assert has_session("arxiv") is False
    assert clear_session("arxiv") is False  # already gone


class _FakeLocator:
    def __init__(self, count):
        self._count = count
        self.first = MagicMock()
        self.first.fill = AsyncMock()
        self.first.click = AsyncMock()

    async def count(self):
        return self._count


def _fake_page(pw_count=1, user_count=1, submit_count=1):
    locs = {}

    def _loc(sel):
        if "password" in sel:
            return locs.setdefault("pw", _FakeLocator(pw_count))
        if "submit" in sel or "has-text" in sel:
            return locs.setdefault("submit", _FakeLocator(submit_count))
        return locs.setdefault("user", _FakeLocator(user_count))

    page = MagicMock()
    page.locator = MagicMock(side_effect=_loc)
    page.wait_for_load_state = AsyncMock()
    page._locs = locs
    return page


@pytest.mark.asyncio
async def test_scripted_login_fills_and_submits():
    from core.browser_session import _try_scripted_login
    page = _fake_page()
    ok = await _try_scripted_login(page, "alice", "secret")
    assert ok is True
    page._locs["user"].first.fill.assert_awaited_once_with("alice")
    page._locs["pw"].first.fill.assert_awaited_once_with("secret")
    page._locs["submit"].first.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_scripted_login_no_password_field_returns_false():
    from core.browser_session import _try_scripted_login
    page = _fake_page(pw_count=0)
    assert await _try_scripted_login(page, "u", "p") is False


@pytest.mark.asyncio
async def test_scripted_login_no_username_field_returns_false():
    from core.browser_session import _try_scripted_login
    page = _fake_page(user_count=0)
    assert await _try_scripted_login(page, "u", "p") is False


@pytest.mark.asyncio
async def test_scripted_login_swallows_exception():
    from core.browser_session import _try_scripted_login
    page = MagicMock()
    page.locator = MagicMock(side_effect=RuntimeError("boom"))
    assert await _try_scripted_login(page, "u", "p") is False


@pytest.mark.asyncio
async def test_finish_login_saves_and_closes(_sessions_env):
    import core.browser_session as bs
    from core.browser_session import has_session

    context = MagicMock()
    context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})
    browser = MagicMock()
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.stop = AsyncMock()
    bs._ACTIVE_LOGINS["jstor"] = {"pw": pw, "browser": browser, "context": context}

    msg = await bs.finish_login("jstor")

    assert "jstor" in msg
    assert has_session("jstor") is True
    browser.close.assert_awaited_once()
    pw.stop.assert_awaited_once()
    assert "jstor" not in bs._ACTIVE_LOGINS


@pytest.mark.asyncio
async def test_finish_login_no_active_returns_message():
    import core.browser_session as bs
    bs._ACTIVE_LOGINS.pop("ghost", None)
    msg = await bs.finish_login("ghost")
    assert "No login in progress" in msg


@pytest.mark.asyncio
async def test_start_login_playwright_absent_returns_hint(monkeypatch):
    import core.browser_session as bs
    monkeypatch.setattr(bs, "_import_async_playwright", lambda: None)
    msg = await bs.start_login("jstor", "https://jstor.org", "u", "p")
    assert "Playwright not installed" in msg


@pytest.mark.asyncio
async def test_finish_login_save_failure_reports_gracefully(_sessions_env, monkeypatch):
    import core.browser_session as bs
    context = MagicMock(); context.storage_state = AsyncMock(return_value={"cookies": []})
    browser = MagicMock(); browser.close = AsyncMock()
    pw = MagicMock(); pw.stop = AsyncMock()
    bs._ACTIVE_LOGINS["jstor"] = {"pw": pw, "browser": browser, "context": context}
    monkeypatch.setattr(bs, "save_session", MagicMock(side_effect=OSError("disk full")))
    msg = await bs.finish_login("jstor")
    assert "could not save" in msg.lower() or "disk full" in msg.lower()
    browser.close.assert_awaited_once()
    pw.stop.assert_awaited_once()
    assert "jstor" not in bs._ACTIVE_LOGINS


@pytest.mark.asyncio
async def test_start_login_context_failure_cleans_up(monkeypatch):
    import core.browser_session as bs
    browser = MagicMock(); browser.close = AsyncMock()
    browser.new_context = AsyncMock(side_effect=RuntimeError("ctx boom"))
    chromium = MagicMock(); chromium.launch = AsyncMock(return_value=browser)
    pw = MagicMock(); pw.chromium = chromium; pw.stop = AsyncMock()
    fake_instance = MagicMock(); fake_instance.start = AsyncMock(return_value=pw)
    monkeypatch.setattr(bs, "_import_async_playwright", lambda: (lambda: fake_instance))
    bs._ACTIVE_LOGINS.pop("jstor", None)
    msg = await bs.start_login("jstor", "https://jstor.org", "u", "p")
    assert "could not" in msg.lower()
    browser.close.assert_awaited_once()
    pw.stop.assert_awaited_once()
    assert "jstor" not in bs._ACTIVE_LOGINS


@pytest.mark.asyncio
async def test_authed_fetch_no_session_returns_false(_sessions_env):
    from core.browser_session import authed_fetch
    html, ok = await authed_fetch("jstor", "https://www.jstor.org/search?q=x")
    assert html is None and ok is False


@pytest.mark.asyncio
async def test_authed_fetch_playwright_absent_returns_false(_sessions_env, monkeypatch):
    import core.browser_session as bs
    bs.save_session("jstor", {"cookies": [], "origins": []})
    monkeypatch.setattr(bs, "_import_async_playwright", lambda: None)
    html, ok = await bs.authed_fetch("jstor", "https://www.jstor.org/search?q=x")
    assert html is None and ok is False
