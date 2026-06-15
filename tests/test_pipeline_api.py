import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from core.main import create_app
from core import pipeline_registry


@pytest.fixture(autouse=True)
def reset_pipeline_registry():
    pipeline_registry.set_state("stopped")
    pipeline_registry.set_task(None)
    yield
    pipeline_registry.set_state("stopped")
    pipeline_registry.set_task(None)


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_pipeline_status_returns_state(app):
    pipeline_registry.set_state("armed")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/pipeline/status")
    assert r.status_code == 200
    assert r.json() == {"state": "armed"}


@pytest.mark.asyncio
async def test_pipeline_stop_cancels_task(app):
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    pipeline_registry.set_task(mock_task)
    pipeline_registry.set_state("armed")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/stop")
    assert r.status_code == 200
    assert r.json() == {"state": "stopped"}
    mock_task.cancel.assert_called_once()
    assert pipeline_registry.get_state() == "stopped"
    assert pipeline_registry.get_task() is None


@pytest.mark.asyncio
async def test_pipeline_stop_when_no_task_returns_stopped(app):
    pipeline_registry.set_task(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/stop")
    assert r.status_code == 200
    assert r.json() == {"state": "stopped"}


@pytest.mark.asyncio
async def test_pipeline_start_when_already_running_returns_current_state(app):
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.done.return_value = False
    pipeline_registry.set_task(mock_task)
    pipeline_registry.set_state("listening")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/pipeline/start")
    assert r.status_code == 200
    assert r.json() == {"state": "listening"}


@pytest.mark.asyncio
async def test_pipeline_start_when_stopped_creates_task(app):
    pipeline_registry.set_task(None)
    pipeline_registry.set_state("stopped")
    with patch("core.pipeline_runner.start_pipeline", new=AsyncMock()) as mock_start:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/pipeline/start")
    assert r.status_code == 200
    assert r.json()["state"] == "starting"
    assert pipeline_registry.get_task() is not None
