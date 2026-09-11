from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


def _mock_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.asyncio
async def test_safe_command_runs():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, b"hello")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/shell", json={"command": "echo hello"})
    assert r.status_code == 200
    assert r.json()["stdout"] == "hello"


@pytest.mark.asyncio
async def test_fork_bomb_blocked_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": ":(){ :|:& };:"})
    assert r.status_code == 422
    assert "blocked" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_mkfs_blocked_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": "mkfs.ext4 /dev/sdb"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_dd_to_device_blocked_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": "dd if=/dev/zero of=/dev/sda"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_empty_command_422():
    async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
        r = await c.post("/api/shell", json={"command": ""})
    assert r.status_code == 422
