from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_shell_run_echo():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": "echo hello"})
    assert r.status_code == 200
    d = r.json()
    assert "hello" in d["stdout"]
    assert d["returncode"] == 0
    assert d["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_shell_nonzero_exit():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": "exit 42"})
    assert r.status_code == 200
    assert r.json()["returncode"] == 42


@pytest.mark.asyncio
async def test_shell_stderr_captured():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": "echo err >&2"})
    assert r.status_code == 200
    assert "err" in r.json()["stderr"]


@pytest.mark.asyncio
async def test_shell_empty_command_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_shell_history_stored():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        await c.post("/api/shell", json={"command": "echo history_test_marker"})
        r = await c.get("/api/shell/history")
    assert r.status_code == 200
    history = r.json()["history"]
    assert any("history_test_marker" in h["command"] for h in history)


@pytest.mark.asyncio
async def test_shell_timeout_capped():
    # timeout param > 30 should be capped; server should still respond
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": "echo ok", "timeout": 999})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_shell_history_endpoint_returns_list():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.get("/api/shell/history")
    assert r.status_code == 200
    assert "history" in r.json()
    assert isinstance(r.json()["history"], list)
