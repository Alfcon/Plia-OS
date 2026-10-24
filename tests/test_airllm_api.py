from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from httpx._transports.asgi import ASGITransport


def _make_app():
    from core.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_airllm_status_not_loaded():
    with patch("agents.airllm_backend._model", None), \
         patch("agents.airllm_backend._model_id", None):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/airllm/status")
    assert r.status_code == 200
    d = r.json()
    assert d["loaded"] is False
    assert d["model_id"] == ""
    assert "compression" in d
    assert "configured" in d


@pytest.mark.asyncio
async def test_airllm_status_loaded():
    mock_model = MagicMock()
    with patch("agents.airllm_backend._model", mock_model), \
         patch("agents.airllm_backend._model_id", "meta-llama/Llama-3.1-70B-Instruct"):
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.get("/api/airllm/status")
    assert r.status_code == 200
    d = r.json()
    assert d["loaded"] is True
    assert d["model_id"] == "meta-llama/Llama-3.1-70B-Instruct"


@pytest.mark.asyncio
async def test_airllm_unload():
    called = []

    def _fake_unload():
        called.append(True)

    with patch("agents.airllm_backend.unload", _fake_unload), \
         patch("dashboard.server.update_config") as mock_cfg:
        async with AsyncClient(transport=ASGITransport(app=_make_app()), base_url="http://test") as c:
            r = await c.post("/api/airllm/unload")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert called
    mock_cfg.assert_called_with(airllm_model="")
