import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from core.main import create_app
from core import pipeline_registry, events


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


@pytest.mark.asyncio
async def test_pipeline_finally_unsubscribes_on_event():
    """start_pipeline() must remove pipeline._on_event from subscribers in finally."""
    mock_pipeline = MagicMock()
    mock_pipeline.load.side_effect = RuntimeError("no device")
    mock_pipeline._on_event = AsyncMock()

    with patch("voice.pipeline.VoicePipeline", return_value=mock_pipeline):
        task = asyncio.create_task(__import__("core.pipeline_runner", fromlist=["start_pipeline"]).start_pipeline())
        pipeline_registry.set_task(task)
        try:
            await task
        except Exception:
            pass

    assert mock_pipeline._on_event not in events._subscribers


@pytest.mark.asyncio
async def test_pipeline_finally_does_not_clobber_replaced_task():
    """If registry was updated to a new task before finally runs, finally must not clear it."""
    mock_pipeline = MagicMock()
    mock_pipeline.load.side_effect = RuntimeError("no device")
    mock_pipeline._on_event = AsyncMock()

    with patch("voice.pipeline.VoicePipeline", return_value=mock_pipeline):
        from core.pipeline_runner import start_pipeline
        task = asyncio.create_task(start_pipeline())
        pipeline_registry.set_task(task)

        # Simulate stop→start race: replace registry task before finally fires
        replacement = MagicMock(spec=asyncio.Task)
        pipeline_registry.set_task(replacement)

        try:
            await task
        except Exception:
            pass

    # finally saw get_task() is replacement ≠ current_task (task), so did not clear
    assert pipeline_registry.get_task() is replacement
