import pytest
import numpy as np
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from core.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_generate_chatterbox_no_tts_service_returns_409(app):
    with patch("dashboard.server.get_tts_service", return_value=None):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/generate-chatterbox", json={"prompt": "hello"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_generate_chatterbox_chatterbox_not_loaded_returns_409(app):
    mock_svc = MagicMock()
    mock_svc._chatterbox = None

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs) if callable(fn) else fn

    with patch("dashboard.server.get_tts_service", return_value=mock_svc), \
         patch("asyncio.to_thread", side_effect=_fake_to_thread):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/generate-chatterbox", json={"prompt": "hello"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_generate_chatterbox_empty_prompt_returns_422(app):
    mock_svc = MagicMock()
    mock_svc._chatterbox = MagicMock()

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs) if callable(fn) else fn

    with patch("dashboard.server.get_tts_service", return_value=mock_svc), \
         patch("asyncio.to_thread", side_effect=_fake_to_thread):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/generate-chatterbox", json={"prompt": "   "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_generate_chatterbox_returns_filename(app, tmp_path):
    mock_svc = MagicMock()
    mock_svc._chatterbox = MagicMock()
    mock_svc._synthesise_chatterbox.return_value = np.zeros(24000, dtype=np.float32)

    async def _fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs) if callable(fn) else fn

    with patch("dashboard.server.get_tts_service", return_value=mock_svc), \
         patch("dashboard.server.UPLOADS_DIR", tmp_path), \
         patch("asyncio.to_thread", side_effect=_fake_to_thread):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/generate-chatterbox", json={"prompt": "hello world"})

    assert r.status_code == 200
    data = r.json()
    assert "filename" in data
    assert data["filename"].startswith("chatterbox_")
    assert data["filename"].endswith(".wav")
