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


_SAMPLE_DF = b"""Filesystem     Type     Size  Used Avail Use% Mounted on
/dev/sda1      ext4      50G   20G   28G  42% /
tmpfs          tmpfs    2.0G  1.2M  2.0G   1% /dev/shm
/dev/sda2      ext4     100G   80G   15G  85% /home
"""


@pytest.mark.asyncio
async def test_disk_usage_ok():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_DF)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 3
    assert d["partitions"][0]["target"] == "/"
    assert d["partitions"][0]["percent"] == 42


@pytest.mark.asyncio
async def test_disk_usage_503_on_failure():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(1, b"", b"command failed")):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_disk_usage_fields():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_DF)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    p = r.json()["partitions"][0]
    for field in ("source", "fstype", "size", "used", "avail", "percent", "target"):
        assert field in p, f"missing: {field}"


@pytest.mark.asyncio
async def test_disk_usage_percent_int():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_DF)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    for p in r.json()["partitions"]:
        assert isinstance(p["percent"], int)


@pytest.mark.asyncio
async def test_disk_usage_home_partition():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_DF)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    home = next(p for p in r.json()["partitions"] if p["target"] == "/home")
    assert home["percent"] == 85
    assert home["source"] == "/dev/sda2"


@pytest.mark.asyncio
async def test_disk_usage_total_matches_partitions():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SAMPLE_DF)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    d = r.json()
    assert d["total"] == len(d["partitions"])


_SPACEY_DF = b"""Filesystem     Type     Size  Used Avail Use% Mounted on
/dev/sda1      ext4      50G   20G   28G  42% /
/dev/sda2      ext4     100G   80G   15G  85% /run/media/user/My USB Drive
"""


@pytest.mark.asyncio
async def test_disk_usage_mount_with_spaces():
    with patch("asyncio.create_subprocess_exec", return_value=_mock_proc(0, _SPACEY_DF)):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/disk")
    parts = r.json()["partitions"]
    spacey = next(p for p in parts if "sda2" in p["source"])
    assert spacey["target"] == "/run/media/user/My USB Drive"
