from __future__ import annotations

import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


# ── Unit tests ────────────────────────────────────────────────────────────────

def test_set_and_get(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, get_var
        set_var("key1", "hello")
        assert get_var("key1") == "hello"


def test_get_missing(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import get_var
        assert get_var("nope") is None


def test_set_updates_existing(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, get_var
        set_var("k", "v1")
        set_var("k", "v2")
        assert get_var("k") == "v2"


def test_set_stores_description(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, list_vars
        set_var("k", "v", description="my desc")
        entries = list_vars()
        assert entries[0]["description"] == "my desc"


def test_set_stores_updated_at(tmp_path):
    t0 = int(time.time())
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, list_vars
        set_var("k", "v")
        entries = list_vars()
        assert entries[0]["updated_at"] >= t0


def test_list_vars_sorted(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, list_vars
        set_var("z", "1")
        set_var("a", "2")
        set_var("m", "3")
        names = [e["name"] for e in list_vars()]
        assert names == sorted(names)


def test_delete_var(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, delete_var, get_var
        set_var("x", "10")
        assert delete_var("x") is True
        assert get_var("x") is None


def test_delete_missing(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import delete_var
        assert delete_var("ghost") is False


def test_list_empty(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import list_vars
        assert list_vars() == []


def test_resolve_vars_substitutes(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, resolve_vars
        set_var("host", "localhost")
        assert resolve_vars("connect to {{vars.host}}:8080") == "connect to localhost:8080"


def test_resolve_vars_missing_unchanged(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import resolve_vars
        assert resolve_vars("{{vars.nope}}") == "{{vars.nope}}"


def test_resolve_vars_multiple(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        from agents.variable_store import set_var, resolve_vars
        set_var("a", "foo")
        set_var("b", "bar")
        assert resolve_vars("{{vars.a}}-{{vars.b}}") == "foo-bar"


def test_persist_across_calls(tmp_path):
    p = tmp_path / "v.json"
    with patch("agents.variable_store._vars_path", return_value=p):
        from agents.variable_store import set_var, get_var
        set_var("persist", "yes")
    # reload from disk
    with patch("agents.variable_store._vars_path", return_value=p):
        from agents.variable_store import get_var
        assert get_var("persist") == "yes"


# ── API tests ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_list_empty(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/vars")
    assert r.status_code == 200
    assert r.json()["vars"] == []


@pytest.mark.asyncio
async def test_api_set_and_list(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/vars", json={"name": "foo", "value": "bar", "description": "test"})
            assert r.status_code == 200
            r2 = await c.get("/api/vars")
    assert r2.json()["vars"][0]["name"] == "foo"
    assert r2.json()["vars"][0]["value"] == "bar"


@pytest.mark.asyncio
async def test_api_set_missing_name(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/vars", json={"value": "bar"})
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_api_set_empty_name(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/vars", json={"name": "  ", "value": "bar"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_delete(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/vars", json={"name": "x", "value": "1"})
            r = await c.delete("/api/vars/x")
            assert r.status_code == 200
            r2 = await c.get("/api/vars")
    assert r2.json()["vars"] == []


@pytest.mark.asyncio
async def test_api_delete_missing(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.delete("/api/vars/ghost")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_overwrite(tmp_path):
    with patch("agents.variable_store._vars_path", return_value=tmp_path / "v.json"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            await c.post("/api/vars", json={"name": "k", "value": "v1"})
            await c.post("/api/vars", json={"name": "k", "value": "v2"})
            r = await c.get("/api/vars")
    vars_ = r.json()["vars"]
    assert len(vars_) == 1
    assert vars_[0]["value"] == "v2"
