from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_list_empty():
    with patch("core.shortcut_store._path") as mp:
        mp.return_value.__truediv__ = lambda *a: mp.return_value
        mp.return_value.exists.return_value = False
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/shortcuts")
    assert r.status_code == 200
    assert r.json()["shortcuts"] == []


@pytest.mark.asyncio
async def test_add_shortcut(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/shortcuts", json={"keyword": "weather", "message": "What is the weather today?"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["id"] == 1


@pytest.mark.asyncio
async def test_add_missing_keyword_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shortcuts", json={"message": "hello"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_add_missing_message_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shortcuts", json={"keyword": "hi"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_shortcut(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        from core.shortcut_store import add_shortcut
        sc_id = add_shortcut("test", "test message")
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete(f"/api/shortcuts/{sc_id}")
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_not_found_404(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/shortcuts/9999")
    assert r.status_code == 404


# ── Store unit tests ──────────────────────────────────────────────────────────

def test_match_shortcut_found(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        from core.shortcut_store import add_shortcut, match_shortcut
        add_shortcut("weather", "What is the weather today?")
        result = match_shortcut("check weather please")
    assert result == "What is the weather today?"


def test_match_shortcut_not_found(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        from core.shortcut_store import match_shortcut
        result = match_shortcut("something completely different")
    assert result is None


def test_match_shortcut_case_insensitive(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        from core.shortcut_store import add_shortcut, match_shortcut
        add_shortcut("WEATHER", "What is the weather?")
        result = match_shortcut("Tell me the Weather forecast")
    assert result == "What is the weather?"


@pytest.mark.asyncio
async def test_shortcut_applied_in_chat(tmp_path):
    with patch("core.shortcut_store._path", return_value=tmp_path / "sc.json"):
        from core.shortcut_store import add_shortcut
        add_shortcut("ping", "What is your status?")
        with patch("core.supervisor.run_turn") as mock_rt:
            mock_rt.return_value = ("pong", [])
            with patch("agents.chat_history.get_recent", return_value=[]):
                with patch("core.context_compactor.maybe_compact", side_effect=lambda x: x):
                    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
                        r = await c.post("/api/chat", json={"text": "ping"})
        # run_turn should have been called with the mapped message
        call_msgs = mock_rt.call_args[0][0]
        assert any(m["content"] == "What is your status?" for m in call_msgs)
