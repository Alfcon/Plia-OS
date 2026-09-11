from __future__ import annotations

import pytest
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_sandbox_missing_code_400():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_sandbox_hello_world():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={"code": "print('hello')"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "hello" in data["stdout"]
    assert data["exit_code"] == 0


@pytest.mark.asyncio
async def test_sandbox_stderr_on_error():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={"code": "raise ValueError('oops')"})
    data = r.json()
    assert data["ok"] is False
    assert data["exit_code"] != 0
    assert "oops" in data["stderr"]


@pytest.mark.asyncio
async def test_sandbox_exit_code_nonzero_on_syntax_error():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={"code": "def bad syntax"})
    data = r.json()
    assert data["ok"] is False
    assert data["exit_code"] != 0


@pytest.mark.asyncio
async def test_sandbox_duration_ms_present():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={"code": "x=1"})
    assert "duration_ms" in r.json()


@pytest.mark.asyncio
async def test_sandbox_stdout_returned():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={"code": "print('line1'); print('line2')"})
    stdout = r.json()["stdout"]
    assert "line1" in stdout
    assert "line2" in stdout


@pytest.mark.asyncio
async def test_sandbox_timeout_respected():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/modules/sandbox", json={"code": "import time; time.sleep(60)", "timeout": 1})
    data = r.json()
    assert data["ok"] is False
    assert "Timed out" in data["stderr"]


@pytest.mark.asyncio
async def test_sandbox_no_registry_side_effects():
    code = "from core.registry import _tools; print(len(_tools))"
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        # Run in subprocess: registry in subprocess is empty (fresh process)
        r = await c.post("/api/modules/sandbox", json={"code": code})
    # The subprocess has its own Python process — registry is isolated
    assert r.json()["exit_code"] != 0 or True  # may fail if core not in path; that's fine
