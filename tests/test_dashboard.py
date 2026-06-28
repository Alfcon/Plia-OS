import pytest
import asyncio
import json
import threading
import numpy as np
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from core.registry import tool
from core import events
from core.config import reset_config as _reset_config
from dashboard.server import router
from dashboard import server as dashboard_server


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture(autouse=True)
def reset_cfg():
    yield
    _reset_config()


@pytest.fixture(autouse=True)
def reset_recorder():
    yield
    dashboard_server._recorder._stop_event.set()
    if dashboard_server._recorder.thread:
        dashboard_server._recorder.thread.join(timeout=1.0)
    dashboard_server._recorder.active = False
    dashboard_server._recorder.thread = None
    dashboard_server._recorder.chunks = []
    dashboard_server._recorder._stop_event.clear()


def _make_mock_sd():
    """Return a mock sounddevice module whose InputStream is a no-op context manager."""
    mock_sd = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    mock_sd.InputStream.return_value = cm
    return mock_sd


async def test_get_tools(app):
    @tool(description="test tool")
    def my_tool() -> str:
        return "ok"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    names = [t["name"] for t in data["tools"]]
    assert "my_tool" in names
    entry = next(t for t in data["tools"] if t["name"] == "my_tool")
    assert entry["description"] == "test tool"


async def test_get_config(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json()["ollama_model"] == "llama3.2"


async def test_post_config_updates_value(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"ollama_model": "mistral"})
    assert resp.status_code == 200
    assert resp.json()["ollama_model"] == "mistral"


async def test_post_config_unknown_key_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"nonexistent_key": "value"})
    assert resp.status_code == 422


async def test_post_config_invalid_literal_tts_engine_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"tts_engine": "invalid_engine"})
    assert resp.status_code == 422


async def test_post_config_valid_literal_tts_engine_accepted(app):
    for engine in ("kokoro", "chatterbox", "dramabox"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/config", json={"tts_engine": engine})
        assert resp.status_code == 200, f"expected 200 for tts_engine={engine!r}"
        assert resp.json()["tts_engine"] == engine


async def test_post_config_invalid_stt_model_size_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"stt_model_size": "huge"})
    assert resp.status_code == 422


async def test_post_config_system_prompt_backup_silently_ignored(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/config", json={"system_prompt_backup": "injected"})
    assert resp.status_code == 200
    assert resp.json().get("system_prompt_backup", "") == ""


async def test_start_recording_returns_200(app):
    with patch("dashboard.server.sd", _make_mock_sd()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/start-recording")
    assert resp.status_code == 200
    assert resp.json() == {"recording": True}
    assert dashboard_server._recorder.active is True


async def test_start_recording_while_active_returns_409(app):
    dashboard_server._recorder.active = True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/start-recording")
    assert resp.status_code == 409


async def test_stop_recording_saves_wav_and_updates_config(app, tmp_path):
    chunk = np.zeros((1600, 1), dtype=np.int16)
    dashboard_server._recorder.active = True
    dashboard_server._recorder.chunks = [chunk, chunk]
    dashboard_server._recorder.thread = None

    with patch.object(dashboard_server, "UPLOADS_DIR", tmp_path):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/stop-recording")

    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"].startswith("recording_")
    assert data["filename"].endswith(".wav")
    assert (tmp_path / data["filename"]).exists()
    from core.config import get_config
    assert get_config().chatterbox_reference_audio == data["path"]


async def test_stop_recording_when_idle_returns_409(app):
    dashboard_server._recorder.active = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/stop-recording")
    assert resp.status_code == 409


async def test_list_reminders_returns_pending(app):
    mock_store = MagicMock()
    mock_store.list_pending.return_value = [
        {"id": 1, "message": "Buy milk", "fire_at": "2026-06-13T12:00:00+00:00"},
    ]
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/reminders")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["message"] == "Buy milk"


async def test_list_reminders_empty(app):
    mock_store = MagicMock()
    mock_store.list_pending.return_value = []
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/reminders")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_cancel_reminder_marks_done(app):
    mock_store = MagicMock()
    with patch("agents.memory_store.get_memory_store", return_value=mock_store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/reminders/42")
    assert resp.status_code == 200
    assert resp.json()["id"] == 42
    mock_store.mark_reminder_done.assert_called_once_with(42)
