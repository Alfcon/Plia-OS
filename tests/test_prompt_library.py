from __future__ import annotations

import pytest
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── prompt_store unit tests ───────────────────────────────────────────────────

def test_save_and_list(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import save_prompt, list_prompts
        save_prompt("concise", "Be very brief.", "Short answers")
        save_prompt("verbose", "Be thorough and detailed.")
        prompts = list_prompts()
    names = [p["name"] for p in prompts]
    assert "concise" in names
    assert "verbose" in names


def test_get_prompt(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import save_prompt, get_prompt
        save_prompt("test", "Hello world.", "desc")
        p = get_prompt("test")
    assert p is not None
    assert p["text"] == "Hello world."
    assert p["description"] == "desc"


def test_get_prompt_missing(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import get_prompt
        result = get_prompt("nonexistent")
    assert result is None


def test_delete_prompt(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import save_prompt, delete_prompt, list_prompts
        save_prompt("to-delete", "Some text.")
        assert delete_prompt("to-delete") is True
        names = [p["name"] for p in list_prompts()]
    assert "to-delete" not in names


def test_delete_missing_returns_false(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import delete_prompt
        assert delete_prompt("nope") is False


def test_save_empty_name_raises(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import save_prompt
        with pytest.raises(ValueError, match="name"):
            save_prompt("", "some text")


def test_save_empty_text_raises(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import save_prompt
        with pytest.raises(ValueError, match="text"):
            save_prompt("myname", "")


def test_overwrite_preserves_created_at(tmp_path):
    with patch("agents.prompt_store._path", return_value=tmp_path / "prompts.json"):
        from agents.prompt_store import save_prompt, get_prompt
        save_prompt("p", "v1")
        first = get_prompt("p")["created_at"]
        save_prompt("p", "v2")
        second = get_prompt("p")["created_at"]
    assert first == second


# ── GET /api/prompts ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_prompts_empty():
    with patch("agents.prompt_store.list_prompts", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/prompts")
    assert r.status_code == 200
    assert r.json() == {"prompts": []}


@pytest.mark.asyncio
async def test_list_prompts_returns_items():
    items = [{"name": "short", "text": "Be brief.", "description": "", "created_at": 1, "updated_at": 1}]
    with patch("agents.prompt_store.list_prompts", return_value=items):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/prompts")
    assert r.json()["prompts"][0]["name"] == "short"


# ── POST /api/prompts ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_prompt_ok():
    with patch("agents.prompt_store.save_prompt") as mock_save:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/prompts", json={"name": "myp", "text": "Hello.", "description": "d"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    mock_save.assert_called_once_with("myp", "Hello.", "d")


@pytest.mark.asyncio
async def test_save_prompt_missing_name():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/prompts", json={"text": "Hello."})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_save_prompt_missing_text():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/prompts", json={"name": "x"})
    assert r.status_code == 422


# ── DELETE /api/prompts/{name} ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_prompt_ok():
    with patch("agents.prompt_store.delete_prompt", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/prompts/myp")
    assert r.status_code == 200
    assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_prompt_not_found():
    with patch("agents.prompt_store.delete_prompt", return_value=False):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/prompts/ghost")
    assert r.status_code == 404


# ── POST /api/prompts/{name}/apply ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_prompt_sets_system_prompt():
    saved = {"name": "short", "text": "Be brief.", "description": ""}
    with patch("agents.prompt_store.get_prompt", return_value=saved):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/prompts/short/apply")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["system_prompt"] == "Be brief."


@pytest.mark.asyncio
async def test_apply_prompt_not_found():
    with patch("agents.prompt_store.get_prompt", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/prompts/ghost/apply")
    assert r.status_code == 404
