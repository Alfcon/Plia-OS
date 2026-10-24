import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_system_info_returns_expected_fields(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/system/info")
    assert r.status_code == 200
    data = r.json()
    for key in ("os", "cpu_percent", "cpu_count", "ram_total_gb", "ram_used_gb",
                "disk_total_gb", "disk_used_gb", "vram_gb", "gpu_name"):
        assert key in data, f"missing field: {key}"


@pytest.mark.asyncio
async def test_system_info_null_when_psutil_missing(app):
    with patch.dict("sys.modules", {"psutil": None}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/system/info")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["os"], str)


@pytest.mark.asyncio
async def test_system_capabilities_returns_dict(app):
    fake_caps = {"can_run_whisper": True, "can_run_kokoro": False}
    with patch("core.system_fit.capabilities", return_value=fake_caps):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/system/capabilities")
    assert r.status_code == 200
    assert r.json() == fake_caps


@pytest.mark.asyncio
async def test_shutdown_returns_status(app):
    with patch("asyncio.create_task"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/shutdown")
    assert r.status_code == 200
    assert r.json()["status"] == "shutting down"
